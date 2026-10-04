"""把对方框架接口适配成项目执行客户端"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping, Protocol
from uuid import uuid4

from ...execution.client import HeterogeneousExecutionClientAPI, LocalExecutionClient
from ...execution.contracts import (
    AIMDRunRequest,
    ActorCallRequest,
    ActorHandle,
    ActorRequest,
    ArtifactReference,
    TaskHandle,
    TaskRequest,
    TaskResult,
    TaskStatus,
)
from ...execution.quantum_worker import (
    ADAPT_STATEVECTOR_CPU_BACKEND,
    ADAPT_STATEVECTOR_GPU_BACKEND,
)


class FusionFrameworkProtocol(Protocol):
    """INTERFACE.md 已公开、且桥接层实际使用的最小框架表面。"""

    def submit(
        self,
        component_id: str,
        method: str,
        *args: Any,
        invocation_id: str,
        **kwargs: Any,
    ) -> Any: ...

    def result(self, handle: Any) -> Any: ...

    def release(self, handle: Any) -> None: ...


@dataclass(frozen=True)
class FusionComponentIds:
    """项目任务类型到融合框架 component_id 的稳定映射。"""

    quantum_cpu: str = "h2o-f2-quantum-features-cpu"
    quantum_gpu: str = "h2o-f2-quantum-features-gpu"
    quantum_qpu: str = "h2o-f2-quantum-features-qpu"
    classical_actor: str = "h2o-classical-predict"


@dataclass(frozen=True)
class _PendingInvocation:
    task: TaskRequest
    framework_handle: Any


_INVOCATION_ID_MAX_LENGTH = 128
_INVALID_INVOCATION_ID_CHARACTERS = re.compile(r"[^A-Za-z0-9_.-]+")


def _encode_invocation_id(operation: str, *identifiers: str) -> str:
    """生成符合融合框架字符集和长度限制的稳定 invocation ID。"""

    raw = ".".join((str(operation), *(str(identifier) for identifier in identifiers)))
    encoded = _INVALID_INVOCATION_ID_CHARACTERS.sub("-", raw).strip(".-_")
    if not encoded:
        encoded = "invocation"
    if encoded != raw or len(encoded) > _INVOCATION_ID_MAX_LENGTH:
        digest = sha256(raw.encode("utf-8")).hexdigest()[:24]
        suffix = f"-{digest}"
        prefix = encoded[: _INVOCATION_ID_MAX_LENGTH - len(suffix)].rstrip(".-_")
        encoded = f"{prefix or 'invocation'}{suffix}"
    if len(encoded) > _INVOCATION_ID_MAX_LENGTH:
        raise AssertionError("Encoded invocation ID exceeds the framework limit.")
    return encoded


def _error_record(error: Any) -> dict[str, Any]:
    if error is None:
        return {"type": "FusionFrameworkError", "message": "unknown framework error"}
    to_record = getattr(error, "to_record", None)
    if callable(to_record):
        record = to_record()
        if isinstance(record, Mapping):
            return dict(record)
    return {"type": type(error).__name__, "message": str(error)}


def _normalize_status(value: Any) -> TaskStatus:
    text = str(getattr(value, "value", value)).strip().lower()
    if text in {"queued", "pending", "created"}:
        return "queued"
    if text in {"running", "started", "executing"}:
        return "running"
    if text in {"succeeded", "success", "completed", "finished"}:
        return "succeeded"
    if text in {"cancelled", "canceled"}:
        return "cancelled"
    if text in {"failed", "failure", "error", "timeout", "timed_out"}:
        return "failed"
    return "running"


def _trace_context(values: Mapping[str, str]) -> Any:
    """Use the framework's bounded string metadata type when it is installed."""

    try:
        from pivotq._internal.models import StringMetadata
    except ImportError:
        # Keep this module importable before the framework package is delivered.
        return dict(values)
    return StringMetadata.from_mapping(dict(values))


class FusionExecutionClient(HeterogeneousExecutionClientAPI):
    """基于 FusionFramework 文档接口的项目客户端适配器。

    当前公开文档没有规定非阻塞状态、取消、逐调用等待超时和制品服务。
    本类对这些能力执行显式特性检测，不把缺失能力伪装成已经实现。
    """

    def __init__(
        self,
        framework: FusionFrameworkProtocol,
        *,
        component_ids: FusionComponentIds | None = None,
    ) -> None:
        self.framework = framework
        self.component_ids = component_ids or FusionComponentIds()
        self._pending: dict[str, _PendingInvocation] = {}
        self._completed: dict[str, TaskResult] = {}
        self._lock = RLock()

    def describe(self) -> dict[str, Any]:
        return {
            "name": "fusion_framework_execution_client_v1",
            "component_ids": {
                "quantum_cpu": self.component_ids.quantum_cpu,
                "quantum_gpu": self.component_ids.quantum_gpu,
                "quantum_qpu": self.component_ids.quantum_qpu,
                "classical_actor": self.component_ids.classical_actor,
            },
            "documented_framework_methods": ["submit", "result", "release"],
            "optional_framework_methods": ["status", "cancel", "download_artifact"],
            "per_result_timeout_supported": False,
        }

    def submit(self, request: TaskRequest | AIMDRunRequest) -> TaskHandle:
        task = request.to_task_request() if isinstance(request, AIMDRunRequest) else request
        if task.task_type != "quantum_features":
            raise ValueError(
                "FusionExecutionClient currently routes nested quantum_features tasks only. "
                "A heterogeneous aimd_run requires framework-supported nested submission."
            )
        component_id = self._quantum_component_id(task)
        with self._lock:
            if task.task_id in self._pending or task.task_id in self._completed:
                raise ValueError(f"Duplicate task_id: {task.task_id}")
            framework_handle = self.framework.submit(
                component_id,
                "execute",
                task,
                invocation_id=_encode_invocation_id("task", task.run_id, task.task_id),
                trace_context=_trace_context({
                    "operation": "task.execute",
                    "run_id": task.run_id,
                    "task_id": task.task_id,
                }),
            )
            self._pending[task.task_id] = _PendingInvocation(task, framework_handle)
        return TaskHandle(task_id=task.task_id, run_id=task.run_id)

    def status(self, handle: TaskHandle) -> TaskStatus:
        with self._lock:
            completed = self._completed.get(handle.task_id)
            if completed is not None:
                return completed.status
            try:
                pending = self._pending[handle.task_id]
            except KeyError as error:
                raise KeyError(f"Unknown task handle: {handle.task_id}") from error
        framework_status = getattr(self.framework, "status", None)
        if not callable(framework_status):
            return "running"
        return _normalize_status(framework_status(pending.framework_handle))

    def result(self, handle: TaskHandle, *, timeout_seconds: float | None = None) -> TaskResult:
        del timeout_seconds  # INTERFACE.md 只公开 ComponentSpec 级超时，没有 result 级超时。
        with self._lock:
            completed = self._completed.get(handle.task_id)
            if completed is not None:
                return completed
            try:
                pending = self._pending.pop(handle.task_id)
            except KeyError as error:
                raise KeyError(f"Unknown task handle: {handle.task_id}") from error

        release_error: Exception | None = None
        terminal = False
        try:
            invocation_result = self.framework.result(pending.framework_handle)
            terminal = True
            task_result = self._task_result_from_invocation(pending.task, invocation_result)
        except Exception as error:
            task_result = self._failed_task_result(pending.task, error)
        finally:
            if terminal:
                try:
                    self.framework.release(pending.framework_handle)
                except Exception as error:
                    release_error = error

        if release_error is not None:
            task_result = replace(
                task_result,
                metadata={
                    **dict(task_result.metadata),
                    "framework_release_error": {
                        "type": type(release_error).__name__,
                        "message": str(release_error),
                    },
                },
            )
        with self._lock:
            self._completed[handle.task_id] = task_result
        return task_result

    def cancel(self, handle: TaskHandle) -> bool:
        with self._lock:
            if handle.task_id in self._completed:
                return False
            pending = self._pending.get(handle.task_id)
            if pending is None:
                raise KeyError(f"Unknown task handle: {handle.task_id}")
        framework_cancel = getattr(self.framework, "cancel", None)
        if not callable(framework_cancel):
            return False
        cancelled = bool(framework_cancel(pending.framework_handle))
        if not cancelled:
            return False
        try:
            self.framework.release(pending.framework_handle)
        finally:
            with self._lock:
                self._pending.pop(handle.task_id, None)
                self._completed[handle.task_id] = TaskResult(
                    run_id=pending.task.run_id,
                    task_id=pending.task.task_id,
                    task_type=pending.task.task_type,
                    status="cancelled",
                )
        return True

    def download_artifact(
        self,
        artifact: ArtifactReference,
        destination_directory: str | Path,
    ) -> Path:
        framework_download = getattr(self.framework, "download_artifact", None)
        if callable(framework_download):
            return Path(framework_download(artifact, destination_directory))
        if artifact.uri.startswith("file://"):
            return LocalExecutionClient({}).download_artifact(artifact, destination_directory)
        raise NotImplementedError(
            "The provided FusionFramework API does not define artifact download for non-file URIs."
        )

    def create_actor(self, request: ActorRequest) -> ActorHandle:
        value = self._invoke_sync(
            self.component_ids.classical_actor,
            "create",
            request,
            invocation_id=_encode_invocation_id("actor-create", request.run_id, request.actor_id),
            trace_context={
                "operation": "actor.create",
                "run_id": request.run_id,
                "actor_id": request.actor_id,
            },
        )
        return value if isinstance(value, ActorHandle) else ActorHandle.from_dict(value)

    def call_actor(self, handle: ActorHandle, request: ActorCallRequest) -> TaskResult:
        try:
            value = self._invoke_sync(
                self.component_ids.classical_actor,
                "call",
                handle,
                request,
                invocation_id=_encode_invocation_id(
                    "actor-call",
                    request.run_id,
                    request.task_id,
                    handle.actor_id,
                ),
                trace_context={
                    "operation": "actor.call",
                    "run_id": request.run_id,
                    "task_id": request.task_id,
                    "actor_id": handle.actor_id,
                },
            )
            return value if isinstance(value, TaskResult) else TaskResult.from_dict(value)
        except Exception as error:
            return TaskResult(
                run_id=request.run_id,
                task_id=request.task_id,
                task_type=f"actor:{handle.actor_type}:{request.method}",
                status="failed",
                error={
                    "type": type(error).__name__,
                    "message": str(error),
                    "retryable": False,
                },
                metadata={"actor_id": handle.actor_id},
            )

    def terminate_actor(self, handle: ActorHandle) -> bool:
        return bool(
            self._invoke_sync(
                self.component_ids.classical_actor,
                "terminate",
                handle,
                invocation_id=_encode_invocation_id(
                    "actor-terminate",
                    handle.run_id,
                    handle.actor_id,
                    uuid4().hex,
                ),
                trace_context={
                    "operation": "actor.terminate",
                    "run_id": handle.run_id,
                    "actor_id": handle.actor_id,
                },
            )
        )

    def _quantum_component_id(self, task: TaskRequest) -> str:
        backend = str(task.payload.get("backend", ADAPT_STATEVECTOR_CPU_BACKEND))
        if backend == ADAPT_STATEVECTOR_CPU_BACKEND:
            return self.component_ids.quantum_cpu
        if backend == ADAPT_STATEVECTOR_GPU_BACKEND:
            return self.component_ids.quantum_gpu
        if backend == "framework_real_qpu":
            return self.component_ids.quantum_qpu
        raise ValueError(f"No FusionFramework component route for quantum backend: {backend}")

    def _invoke_sync(
        self,
        component_id: str,
        method: str,
        *args: Any,
        invocation_id: str,
        trace_context: Mapping[str, str],
    ) -> Any:
        framework_handle = self.framework.submit(
            component_id,
            method,
            *args,
            invocation_id=invocation_id,
            trace_context=_trace_context(trace_context),
        )
        terminal = False
        try:
            result = self.framework.result(framework_handle)
            terminal = True
            if not bool(getattr(result, "succeeded", False)):
                raise RuntimeError(str(_error_record(getattr(result, "error", None))))
            return result.value
        finally:
            if terminal:
                self.framework.release(framework_handle)

    @staticmethod
    def _task_result_from_invocation(task: TaskRequest, invocation_result: Any) -> TaskResult:
        if not bool(getattr(invocation_result, "succeeded", False)):
            error = _error_record(getattr(invocation_result, "error", None))
            return TaskResult(
                run_id=task.run_id,
                task_id=task.task_id,
                task_type=task.task_type,
                status="failed",
                error={**error, "retryable": bool(error.get("retryable", False))},
                metadata={"framework_status": str(getattr(invocation_result, "status", "failed"))},
            )
        value = invocation_result.value
        if isinstance(value, TaskResult):
            return value
        if isinstance(value, Mapping):
            return TaskResult.from_dict(value)
        raise TypeError("Fusion quantum component must return TaskResult or its mapping representation.")

    @staticmethod
    def _failed_task_result(task: TaskRequest, error: Exception) -> TaskResult:
        return TaskResult(
            run_id=task.run_id,
            task_id=task.task_id,
            task_type=task.task_type,
            status="failed",
            error={
                "type": type(error).__name__,
                "message": str(error),
                "retryable": False,
            },
        )
