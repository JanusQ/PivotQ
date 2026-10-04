"""Ray Task/Actor executor built only on Ray public APIs."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from types import TracebackType
from typing import Any

import ray
from ray.exceptions import GetTimeoutError, RayError, RayTaskError
from ray.util.scheduling_strategies import NodeAffinitySchedulingStrategy

from pivotq._internal.errors import (
    CancellationError,
    ExecutionError,
    RayQuantumError,
    ResultUnknownError,
    TimeoutError as FrameworkTimeoutError,
    UnavailableError,
    ValidationError,
)
from pivotq._internal.executors.cleanup import (
    ActorCleanupRecord,
    ExecutorCleanupError,
    ExecutorCleanupReport,
    MAX_ACTOR_RECORDS,
    error_type,
)
from pivotq._internal.framework.component import (
    validate_component_instance,
    validate_invocation,
)
from pivotq._internal.framework.graph import resolve_result_references
from pivotq._internal.framework.models import (
    ComponentSpec,
    ExecutionMode,
    InvocationHandle,
    InvocationResult,
    InvocationSpec,
    InvocationStatus,
)
from pivotq._internal.framework.registry import (
    ComponentRegistration,
    ComponentRegistry,
)
from pivotq._internal.framework.resources import resource_request_to_ray_options
from pivotq._internal.observability.events import (
    TraceEvent,
    TraceEventJournal,
    TraceEventJournalConfig,
    TraceEventKind,
    TraceEventSource,
    build_trace_event,
)
from pivotq._internal.observability.trace import (
    TraceCollector,
    TraceRecord,
    build_trace_record,
    serialized_size,
    utc_now,
)


@dataclass(slots=True)
class _RayInvocationEntry:
    invocation: InvocationSpec
    registration: ComponentRegistration
    reference: ray.ObjectRef
    trace_reference: ray.ObjectRef | None = None
    expires_at_epoch: float | None = None
    result: InvocationResult | None = None
    submitted_at: datetime | None = None
    input_size_bytes: int = 0
    trace_recorded: bool = False
    event_finished_recorded: bool = False
    event_result_observed_recorded: bool = False


@dataclass(frozen=True, slots=True)
class _RayActorEntry:
    name: str
    handle: Any


@ray.remote
class _TraceEventJournalActor:
    """Own one Head-local v2 journal without consuming a logical CPU."""

    def __init__(self, config: TraceEventJournalConfig) -> None:
        self._journal = TraceEventJournal(config)

    def record(self, event: TraceEvent) -> int | None:
        return self._journal.record(event)

    def finalize(self) -> dict[str, Any]:
        return self._journal.finalize()


def _dependency_failure(
    invocation: InvocationSpec,
    dependency_results: tuple[object, ...],
) -> InvocationResult | None:
    for dependency_result in dependency_results:
        if (
            not isinstance(dependency_result, InvocationResult)
            or not dependency_result.succeeded
        ):
            return InvocationResult(
                invocation_id=invocation.invocation_id,
                component_id=invocation.component_id,
                status=InvocationStatus.FAILED,
                # Unknown external execution must retain its reconciliation
                # identifiers through every skipped downstream task.
                error=dependency_result.error if (
                    isinstance(dependency_result, InvocationResult)
                    and isinstance(dependency_result.error, ResultUnknownError)
                ) else ExecutionError(
                    "a required dependency did not succeed",
                    framework_job_id=invocation.invocation_id,
                ),
            )
    return None


def _has_expired(expires_at_epoch: float | None) -> bool:
    return expires_at_epoch is not None and time.time() >= expires_at_epoch


def _invoke_component(
    instance: object,
    invocation: InvocationSpec,
    expires_at_epoch: float | None,
    dependency_results: tuple[object, ...],
) -> InvocationResult:
    if _has_expired(expires_at_epoch):
        return _timeout_result(invocation)

    try:
        method = getattr(instance, invocation.method)
        args = resolve_result_references(
            invocation.args,
            dependency_results,
        )
        kwargs = resolve_result_references(
            invocation.kwargs_dict(),
            dependency_results,
        )
        value = method(*args, **kwargs)
    except RayQuantumError as error:
        return _failure_result(invocation, error)
    except Exception as error:
        return _failure_result(
            invocation,
            ExecutionError(
                f"external component raised {type(error).__name__}",
                framework_job_id=invocation.invocation_id,
            ),
        )

    if _has_expired(expires_at_epoch):
        return _timeout_result(invocation)
    try:
        return InvocationResult(
            invocation_id=invocation.invocation_id,
            component_id=invocation.component_id,
            status=InvocationStatus.SUCCEEDED,
            value=value,
        )
    except (TypeError, ValueError):
        return _failure_result(
            invocation,
            ExecutionError(
                "external component returned a non-serializable value",
                framework_job_id=invocation.invocation_id,
            ),
        )


@ray.remote
def _execute_component_task(
    registration: ComponentRegistration,
    invocation: InvocationSpec,
    expires_at_epoch: float | None,
    trace_submitted_at: datetime | None,
    trace_input_size_bytes: int,
    trace_event_sink: Any | None,
    trace_event_run_id: str | None,
    *dependency_results: object,
) -> InvocationResult | tuple[InvocationResult, TraceRecord]:
    execution_started_monotonic = time.monotonic()
    scheduled_at = utc_now()
    started_at = scheduled_at
    task_id, actor_id, node_id = _runtime_ids()
    _send_trace_event(
        trace_event_sink,
        invocation,
        registration.spec,
        event=TraceEventKind.STARTED,
        source=TraceEventSource.WORKER,
        status=InvocationStatus.RUNNING,
        occurred_at=started_at,
        run_id=trace_event_run_id,
        task_id=task_id,
        actor_id=actor_id,
        node_id=node_id,
    )
    dependency_failure = _dependency_failure(
        invocation,
        dependency_results,
    )
    if dependency_failure is not None:
        result = dependency_failure
    elif _has_expired(expires_at_epoch):
        result = _timeout_result(invocation)
    else:
        instance: object | None = None
        result: InvocationResult | None = None
        try:
            instance = _construct_component(registration)
            result = _invoke_component(
                instance,
                invocation,
                expires_at_epoch,
                dependency_results,
            )
        except RayQuantumError as error:
            result = _failure_result(invocation, error)
        except Exception as error:
            result = _failure_result(
                invocation,
                ExecutionError(
                    f"external component construction raised "
                    f"{type(error).__name__}",
                    framework_job_id=invocation.invocation_id,
                ),
            )
        finally:
            if instance is not None:
                try:
                    _close_component(instance)
                except Exception as error:
                    if result is None or result.succeeded:
                        result = _failure_result(
                            invocation,
                            ExecutionError(
                                f"external component close raised "
                                f"{type(error).__name__}",
                                framework_job_id=invocation.invocation_id,
                            ),
                        )
        if result is None:
            result = _failure_result(
                invocation,
                ExecutionError(
                    "Ray Task completed without a framework result",
                    framework_job_id=invocation.invocation_id,
                ),
            )
    return _ray_output(
        registration.spec,
        invocation,
        result,
        trace_submitted_at=trace_submitted_at,
        trace_input_size_bytes=trace_input_size_bytes,
        scheduled_at=scheduled_at,
        started_at=started_at,
        execution_started_monotonic=execution_started_monotonic,
        trace_event_sink=trace_event_sink,
        trace_event_run_id=trace_event_run_id,
        runtime_ids=(task_id, actor_id, node_id),
    )


@ray.remote
class _ComponentActor:
    def __init__(self, registration: ComponentRegistration) -> None:
        self._component_spec = registration.spec
        self._instance: object | None = None
        self._construction_error: RayQuantumError | None = None
        self._closed = False
        try:
            self._instance = _construct_component(registration)
        except RayQuantumError as error:
            self._construction_error = error
        except Exception as error:
            self._construction_error = ExecutionError(
                f"external component construction raised {type(error).__name__}"
            )

    def invoke(
        self,
        invocation: InvocationSpec,
        expires_at_epoch: float | None,
        trace_submitted_at: datetime | None,
        trace_input_size_bytes: int,
        trace_event_sink: Any | None,
        trace_event_run_id: str | None,
        *dependency_results: object,
    ) -> InvocationResult | tuple[InvocationResult, TraceRecord]:
        execution_started_monotonic = time.monotonic()
        scheduled_at = utc_now()
        started_at = scheduled_at
        task_id, actor_id, node_id = _runtime_ids()
        _send_trace_event(
            trace_event_sink,
            invocation,
            self._component_spec,
            event=TraceEventKind.STARTED,
            source=TraceEventSource.WORKER,
            status=InvocationStatus.RUNNING,
            occurred_at=started_at,
            run_id=trace_event_run_id,
            task_id=task_id,
            actor_id=actor_id,
            node_id=node_id,
        )
        dependency_failure = _dependency_failure(
            invocation,
            dependency_results,
        )
        if dependency_failure is not None:
            result = dependency_failure
        elif self._closed:
            result = _failure_result(
                invocation,
                UnavailableError(
                    "Ray component Actor is closed",
                    framework_job_id=invocation.invocation_id,
                ),
            )
        elif self._construction_error is not None:
            result = _failure_result(invocation, self._construction_error)
        elif self._instance is None:
            result = _failure_result(
                invocation,
                ExecutionError(
                    "Ray component Actor has no component instance",
                    framework_job_id=invocation.invocation_id,
                ),
            )
        else:
            result = _invoke_component(
                self._instance,
                invocation,
                expires_at_epoch,
                dependency_results,
            )
        return _ray_output(
            self._component_spec,
            invocation,
            result,
            trace_submitted_at=trace_submitted_at,
            trace_input_size_bytes=trace_input_size_bytes,
            scheduled_at=scheduled_at,
            started_at=started_at,
            execution_started_monotonic=execution_started_monotonic,
            trace_event_sink=trace_event_sink,
            trace_event_run_id=trace_event_run_id,
            runtime_ids=(task_id, actor_id, node_id),
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        instance = self._instance
        self._instance = None
        if instance is not None:
            _close_component(instance)


class RayExecutor:
    """Map framework invocations to Ray Tasks, Actors, and ObjectRefs.

    Ray initialization and shutdown remain the caller's responsibility.
    Actor instances are executor-owned, named with an executor-scoped ID, and
    killed during ``close()`` after a bounded best-effort component close.
    """

    def resource_capacities(self) -> tuple[dict[str, float], ...]:
        """Installed capacity per live node, including resources currently busy."""
        return tuple(dict(node["Resources"]) for node in ray.nodes() if node.get("Alive"))

    def __init__(
        self,
        registry: ComponentRegistry,
        *,
        actor_namespace: str | None = None,
        actor_close_timeout_seconds: float = 5.0,
        trace_collector: TraceCollector | None = None,
        trace_event_journal: TraceEventJournalConfig | None = None,
    ) -> None:
        if not isinstance(registry, ComponentRegistry):
            raise TypeError("registry must be a ComponentRegistry")
        if actor_namespace is not None:
            actor_namespace = _require_text(
                "actor_namespace",
                actor_namespace,
            )
        actor_close_timeout_seconds = _require_positive_number(
            "actor_close_timeout_seconds",
            actor_close_timeout_seconds,
        )
        if trace_collector is not None and not isinstance(
            trace_collector,
            TraceCollector,
        ):
            raise TypeError("trace_collector must be a TraceCollector or None")
        if trace_event_journal is not None and not isinstance(
            trace_event_journal,
            TraceEventJournalConfig,
        ):
            raise TypeError(
                "trace_event_journal must be a TraceEventJournalConfig or None"
            )
        if not ray.is_initialized():
            raise UnavailableError(
                "Ray must be initialized by the caller before RayExecutor"
            )

        self._registry = registry
        self._actor_namespace = actor_namespace
        self._actor_close_timeout_seconds = actor_close_timeout_seconds
        self._trace_collector = trace_collector
        self._trace_event_run_id = (
            None if trace_event_journal is None else trace_event_journal.run_id
        )
        self._trace_event_sink = _create_trace_event_sink(trace_event_journal)
        self._executor_id = uuid.uuid4().hex
        self._entries: dict[str, _RayInvocationEntry] = {}
        self._reserved_ids: set[str] = set()
        self._actors: dict[str, _RayActorEntry] = {}
        self._lock = RLock()
        self._submission_lock = RLock()
        self._closed = False
        self._cleanup_report = ExecutorCleanupReport()

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def registry(self) -> ComponentRegistry:
        return self._registry

    @property
    def cleanup_report(self) -> ExecutorCleanupReport:
        with self._lock:
            return self._cleanup_report

    def submit(self, invocation: InvocationSpec) -> InvocationHandle:
        """Submit one invocation and return an ObjectRef-backed handle."""

        if not isinstance(invocation, InvocationSpec):
            raise TypeError("invocation must be an InvocationSpec")

        with self._submission_lock:
            self._ensure_open()
            self._ensure_ray_initialized()
            registration = self._registry.get(invocation.component_id)
            try:
                validate_invocation(registration.spec, invocation)
            except (TypeError, ValueError) as error:
                raise ValidationError(
                    str(error),
                    framework_job_id=invocation.invocation_id,
                ) from None
            event_submitted_at = (
                utc_now()
                if self._trace_collector is not None
                or self._trace_event_sink is not None
                else None
            )
            submitted_at = (
                event_submitted_at if self._trace_collector is not None else None
            )
            input_size_bytes = (
                serialized_size((invocation.args, invocation.kwargs))
                if submitted_at is not None
                else 0
            )

            dependency_references = self._reserve_invocation(invocation)
            _send_trace_event(
                self._trace_event_sink,
                invocation,
                registration.spec,
                event=TraceEventKind.SUBMITTED,
                source=TraceEventSource.DRIVER,
                status=InvocationStatus.QUEUED,
                occurred_at=event_submitted_at,
                run_id=self._trace_event_run_id,
            )
            try:
                event_finished_recorded = False
                expires_at_epoch = _calculate_expiration_epoch(
                    invocation,
                    registration,
                )
                if _has_expired(expires_at_epoch):
                    result = _timeout_result(invocation)
                    reference = ray.put(result)
                    trace_reference = self._put_driver_trace(
                        invocation,
                        registration,
                        result,
                        submitted_at=submitted_at,
                        input_size_bytes=input_size_bytes,
                    )
                    self._send_driver_finished_event(
                        invocation,
                        registration,
                        result,
                    )
                    event_finished_recorded = True
                else:
                    reference, trace_reference = self._submit_remote(
                        registration,
                        invocation,
                        expires_at_epoch,
                        dependency_references,
                        submitted_at=submitted_at,
                        input_size_bytes=input_size_bytes,
                    )
                entry = _RayInvocationEntry(
                    invocation=invocation,
                    registration=registration,
                    reference=reference,
                    trace_reference=trace_reference,
                    expires_at_epoch=expires_at_epoch,
                    submitted_at=submitted_at,
                    input_size_bytes=input_size_bytes,
                    event_finished_recorded=event_finished_recorded,
                )
            except RayQuantumError as error:
                self._send_driver_finished_event(
                    invocation,
                    registration,
                    _failure_result(invocation, error),
                )
                raise
            except Exception as error:
                try:
                    failure = _failure_result(
                        invocation,
                        ExecutionError(
                            f"Ray submission raised {type(error).__name__}",
                            framework_job_id=invocation.invocation_id,
                        ),
                    )
                    reference = ray.put(failure)
                    self._send_driver_finished_event(
                        invocation,
                        registration,
                        failure,
                    )
                    entry = _RayInvocationEntry(
                        invocation=invocation,
                        registration=registration,
                        reference=reference,
                        trace_reference=self._put_driver_trace(
                            invocation,
                            registration,
                            failure,
                            submitted_at=submitted_at,
                            input_size_bytes=input_size_bytes,
                        ),
                        expires_at_epoch=None,
                        result=failure,
                        submitted_at=submitted_at,
                        input_size_bytes=input_size_bytes,
                        event_finished_recorded=True,
                    )
                except Exception:
                    raise UnavailableError(
                        "Ray rejected the invocation submission",
                        framework_job_id=invocation.invocation_id,
                    ) from None
            finally:
                with self._lock:
                    self._reserved_ids.discard(invocation.invocation_id)

            with self._lock:
                self._ensure_open_locked()
                self._entries[invocation.invocation_id] = entry
            return _handle_for(invocation, entry.reference)

    def result(self, handle: InvocationHandle) -> InvocationResult:
        """Resolve an ObjectRef while enforcing framework timeout semantics."""

        entry = self._get_entry(handle)
        with self._lock:
            cached_result = entry.result
        if cached_result is not None:
            self._drain_ready_traces()
            self._record_result_observed_event(entry, cached_result)
            return cached_result

        remaining = _remaining_timeout_seconds(entry.expires_at_epoch)
        if remaining == 0.0:
            return self._mark_timed_out(entry)

        driver_terminal_required = False
        try:
            resolved = ray.get(entry.reference, timeout=remaining)
        except GetTimeoutError:
            return self._mark_timed_out(entry)
        except Exception as error:
            driver_terminal_required = True
            resolved = _failure_result(
                entry.invocation,
                ExecutionError(
                    f"Ray execution raised {type(error).__name__}",
                    framework_job_id=entry.invocation.invocation_id,
                ),
            )

        if not isinstance(resolved, InvocationResult):
            driver_terminal_required = True
            resolved = _failure_result(
                entry.invocation,
                ExecutionError(
                    "Ray invocation returned an invalid framework result",
                    framework_job_id=entry.invocation.invocation_id,
                ),
            )

        with self._lock:
            if entry.result is None:
                entry.result = resolved
            result = entry.result
        self._drain_ready_traces()
        if driver_terminal_required:
            self._record_driver_finished_event(entry, result)
        self._record_result_observed_event(entry, result)
        return result

    def poll(self, handle: InvocationHandle) -> InvocationResult | None:
        """Return a terminal result only once its Ray object is locally ready."""
        entry = self._get_entry(handle)
        with self._lock:
            if entry.result is not None:
                return entry.result
        if _remaining_timeout_seconds(entry.expires_at_epoch) == 0:
            return self.result(handle)
        ready, _ = ray.wait([entry.reference], timeout=0)
        return self.result(handle) if ready else None

    def wait(self, handles: tuple[InvocationHandle, ...], *, num_returns: int = 1,
             timeout: float | None = None) -> tuple[tuple[InvocationHandle, ...], tuple[InvocationHandle, ...]]:
        from .base import validate_wait
        validate_wait(handles, num_returns, timeout)
        entries = {handle.invocation_id: self._get_entry(handle) for handle in handles}
        deadline = None if timeout is None else time.monotonic() + timeout
        while handles:
            ready = tuple(handle for handle in handles if self.poll(handle) is not None)
            ready_ids = {handle.invocation_id for handle in ready}
            pending = tuple(handle for handle in handles if handle.invocation_id not in ready_ids)
            if len(ready) >= num_returns or not pending:
                return ready, pending
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            if remaining == 0:
                return ready, pending
            limits = [_remaining_timeout_seconds(entries[handle.invocation_id].expires_at_epoch)
                      for handle in pending]
            limits = [limit for limit in limits if limit is not None]
            if remaining is not None:
                limits.append(remaining)
            ray.wait([entries[handle.invocation_id].reference for handle in pending],
                     num_returns=min(num_returns - len(ready), len(pending)),
                     timeout=min(limits) if limits else None)
        return (), ()

    def flush_traces(self) -> None:
        """Collect only ready trace objects; never wait for unfinished calls."""
        self._drain_ready_traces()

    def invoke(self, invocation: InvocationSpec) -> InvocationResult:
        """Submit and synchronously resolve one invocation."""

        return self.result(self.submit(invocation))

    def release(self, handle: InvocationHandle) -> None:
        """Drop the Driver's retained ObjectRef after the result is terminal."""

        entry = self._get_entry(handle)
        with self._lock:
            resolved = entry.result is not None
        if not resolved:
            try:
                ready, _ = ray.wait([entry.reference], timeout=0)
            except Exception:
                ready = []
            if not ready:
                raise ValidationError(
                    "cannot release an invocation while work is still running",
                    framework_job_id=entry.invocation.invocation_id,
                )
            self.result(handle)

        with self._lock:
            current = self._entries.get(entry.invocation.invocation_id)
            if current is entry:
                self._entries.pop(entry.invocation.invocation_id, None)

    def close(self) -> None:
        """Cancel outstanding work and release all executor-owned Actors."""

        with self._submission_lock:
            with self._lock:
                if self._closed:
                    return
                self._closed = True
                entries = tuple(self._entries.values())
                actors = tuple(sorted(self._actors.items()))
                self._actors.clear()

        if not ray.is_initialized():
            return

        self._drain_ready_traces()
        for entry in entries:
            if entry.result is None:
                cancellation = InvocationResult(
                    invocation_id=entry.invocation.invocation_id,
                    component_id=entry.invocation.component_id,
                    status=InvocationStatus.CANCELLED,
                    error=CancellationError(
                        "Ray invocation was cancelled during executor close",
                        framework_job_id=entry.invocation.invocation_id,
                    ),
                )
                self._record_driver_terminal(
                    entry,
                    cancellation,
                )
                self._record_driver_finished_event(entry, cancellation)
            _cancel_reference(entry.reference)
            if entry.trace_reference is not None:
                _cancel_reference(entry.trace_reference)

        records: list[ActorCleanupRecord] = []
        for component_id, actor in actors:
            close_reference: ray.ObjectRef | None = None
            cooperative_state = "failed"
            cooperative_error = None
            try:
                close_reference = actor.handle.close.remote()
            except Exception as error:
                cooperative_error = error_type(error)
            else:
                try:
                    ray.get(close_reference, timeout=self._actor_close_timeout_seconds)
                    cooperative_state = "succeeded"
                except RayTaskError as error:
                    # RayTaskError(GetTimeoutError) also inherits GetTimeoutError.
                    # A remote close failure is never a Driver wait timeout.
                    cooperative_error = error_type(error)
                except GetTimeoutError as error:
                    cooperative_state = "timed_out"
                    cooperative_error = error_type(error)
                except Exception as error:
                    cooperative_error = error_type(error)
            if cooperative_state != "succeeded":
                if close_reference is not None:
                    try:
                        _cancel_reference(close_reference)
                    except Exception:
                        pass  # The close and termination outcomes remain authoritative.
            termination_mode = {
                "succeeded": "normal_after_close",
                "timed_out": "fallback_after_timeout",
                "failed": "fallback_after_error",
            }[cooperative_state]
            termination_state, termination_error = "requested", None
            try:
                ray.kill(actor.handle, no_restart=True)
            except Exception as error:
                termination_state, termination_error = "failed", error_type(error)
            if len(records) < MAX_ACTOR_RECORDS:
                records.append(ActorCleanupRecord(
                    component_id=component_id,
                    actor_name=actor.name,
                    # Ray 2.31 ActorHandle exposes no public Actor ID accessor.
                    actor_id=None,
                    cooperative_state=cooperative_state,
                    cooperative_error_type=cooperative_error,
                    timeout_seconds=self._actor_close_timeout_seconds,
                    termination_state=termination_state,
                    termination_mode=termination_mode,
                    termination_error_type=termination_error,
                ))

        report = ExecutorCleanupReport.completed(records, total=len(actors))
        with self._lock:
            self._cleanup_report = report

        _finalize_trace_event_sink(
            self._trace_event_sink,
            timeout_seconds=self._actor_close_timeout_seconds,
        )
        self._trace_event_sink = None

        if report.outcome != "clean":
            raise ExecutorCleanupError(report)

    def __enter__(self) -> RayExecutor:
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _ensure_open(self) -> None:
        with self._lock:
            self._ensure_open_locked()

    def _ensure_open_locked(self) -> None:
        if self._closed:
            raise UnavailableError("Ray executor is closed")

    def _ensure_ray_initialized(self) -> None:
        if not ray.is_initialized():
            raise UnavailableError(
                "Ray was shut down while RayExecutor was active"
            )

    def _reserve_invocation(
        self,
        invocation: InvocationSpec,
    ) -> tuple[ray.ObjectRef, ...]:
        with self._lock:
            self._ensure_open_locked()
            if (
                invocation.invocation_id in self._entries
                or invocation.invocation_id in self._reserved_ids
            ):
                raise ValidationError(
                    f"invocation {invocation.invocation_id!r} already exists",
                    framework_job_id=invocation.invocation_id,
                )

            dependency_references: list[ray.ObjectRef] = []
            for dependency_id in invocation.dependencies:
                dependency = self._entries.get(dependency_id)
                if dependency is None:
                    raise ValidationError(
                        f"dependency {dependency_id!r} is not available",
                        framework_job_id=invocation.invocation_id,
                    )
                if dependency.result is None:
                    dependency_references.append(dependency.reference)
                else:
                    dependency_references.append(ray.put(dependency.result))
            self._reserved_ids.add(invocation.invocation_id)
            return tuple(dependency_references)

    def _submit_remote(
        self,
        registration: ComponentRegistration,
        invocation: InvocationSpec,
        expires_at_epoch: float | None,
        dependency_references: tuple[ray.ObjectRef, ...],
        *,
        submitted_at: datetime | None,
        input_size_bytes: int,
    ) -> tuple[ray.ObjectRef, ray.ObjectRef | None]:
        tracing = submitted_at is not None
        if registration.spec.execution is ExecutionMode.ACTOR:
            actor = self._actor_for(registration)
            method = actor.invoke
            if tracing:
                method = method.options(num_returns=2)
            submitted = method.remote(
                invocation,
                expires_at_epoch,
                submitted_at,
                input_size_bytes,
                self._trace_event_sink,
                self._trace_event_run_id,
                *dependency_references,
            )
            if tracing:
                result_reference, trace_reference = submitted
                return result_reference, trace_reference
            return submitted, None

        options: dict[str, Any] = resource_request_to_ray_options(
            registration.spec.resources
        )
        options.update(
            {
                "max_retries": 0,
                "retry_exceptions": False,
            }
        )
        if tracing:
            options["num_returns"] = 2
        submitted = _execute_component_task.options(**options).remote(
            registration,
            invocation,
            expires_at_epoch,
            submitted_at,
            input_size_bytes,
            self._trace_event_sink,
            self._trace_event_run_id,
            *dependency_references,
        )
        if tracing:
            result_reference, trace_reference = submitted
            return result_reference, trace_reference
        return submitted, None

    def _actor_for(self, registration: ComponentRegistration) -> Any:
        component_id = registration.spec.component_id
        existing = self._actors.get(component_id)
        if existing is not None:
            return existing.handle

        name = f"ray-quantum-{self._executor_id}-{component_id}"
        options: dict[str, Any] = resource_request_to_ray_options(
            registration.spec.resources
        )
        options.update(
            {
                "name": name,
                "get_if_exists": True,
                "max_concurrency": registration.spec.max_concurrency,
                "max_restarts": 0,
                "max_task_retries": 0,
            }
        )
        if self._actor_namespace is not None:
            options["namespace"] = self._actor_namespace
        handle = _ComponentActor.options(**options).remote(registration)
        self._actors[component_id] = _RayActorEntry(
            name=name,
            handle=handle,
        )
        return handle

    def _get_entry(
        self,
        handle: InvocationHandle,
    ) -> _RayInvocationEntry:
        if not isinstance(handle, InvocationHandle):
            raise TypeError("handle must be an InvocationHandle")
        with self._lock:
            entry = self._entries.get(handle.invocation_id)
            if (
                entry is None
                or handle.component_id != entry.invocation.component_id
                or handle.reference != entry.reference
            ):
                raise ValidationError(
                    "invocation handle is not owned by this executor",
                    framework_job_id=handle.invocation_id,
                )
            return entry

    def _mark_timed_out(
        self,
        entry: _RayInvocationEntry,
    ) -> InvocationResult:
        with self._lock:
            if entry.result is None:
                entry.result = _timeout_result(entry.invocation)
            result = entry.result
        self._record_driver_terminal(entry, result)
        self._record_driver_finished_event(entry, result)
        self._record_result_observed_event(entry, result)
        _cancel_reference(entry.reference)
        if entry.trace_reference is not None:
            _cancel_reference(entry.trace_reference)
        return result

    def _put_driver_trace(
        self,
        invocation: InvocationSpec,
        registration: ComponentRegistration,
        result: InvocationResult,
        *,
        submitted_at: datetime | None,
        input_size_bytes: int,
    ) -> ray.ObjectRef | None:
        if submitted_at is None:
            return None
        finished_at = utc_now()
        trace = build_trace_record(
            invocation,
            registration.spec,
            result,
            backend="ray",
            submitted_at=submitted_at,
            scheduled_at=None,
            started_at=None,
            finished_at=finished_at,
            result_observed_at=finished_at,
            input_size_bytes=input_size_bytes,
            output_size_bytes=0,
        )
        return ray.put(trace)

    def _send_driver_finished_event(
        self,
        invocation: InvocationSpec,
        registration: ComponentRegistration,
        result: InvocationResult,
    ) -> None:
        _send_trace_event(
            self._trace_event_sink,
            invocation,
            registration.spec,
            event=TraceEventKind.FINISHED,
            source=TraceEventSource.DRIVER,
            status=result.status,
            run_id=self._trace_event_run_id,
            error_code=None if result.error is None else result.error.code,
        )

    def _record_driver_finished_event(
        self,
        entry: _RayInvocationEntry,
        result: InvocationResult,
    ) -> None:
        with self._lock:
            if entry.event_finished_recorded:
                return
            entry.event_finished_recorded = True
        self._send_driver_finished_event(
            entry.invocation,
            entry.registration,
            result,
        )

    def _record_result_observed_event(
        self,
        entry: _RayInvocationEntry,
        result: InvocationResult,
    ) -> None:
        with self._lock:
            if entry.event_result_observed_recorded:
                return
            entry.event_result_observed_recorded = True
        _send_trace_event(
            self._trace_event_sink,
            entry.invocation,
            entry.registration.spec,
            event=TraceEventKind.RESULT_OBSERVED,
            source=TraceEventSource.DRIVER,
            status=result.status,
            run_id=self._trace_event_run_id,
            error_code=None if result.error is None else result.error.code,
        )

    def _record_driver_terminal(
        self,
        entry: _RayInvocationEntry,
        result: InvocationResult,
    ) -> None:
        collector = self._trace_collector
        submitted_at = entry.submitted_at
        if collector is None or submitted_at is None:
            return
        with self._lock:
            if entry.trace_recorded:
                return
            entry.trace_recorded = True
        finished_at = utc_now()
        try:
            collector.record(
                build_trace_record(
                    entry.invocation,
                    entry.registration.spec,
                    result,
                    backend="ray",
                    submitted_at=submitted_at,
                    scheduled_at=None,
                    started_at=None,
                    finished_at=finished_at,
                    result_observed_at=finished_at,
                    input_size_bytes=entry.input_size_bytes,
                    output_size_bytes=0,
                )
            )
        except Exception:
            pass

    def _drain_ready_traces(self) -> None:
        collector = self._trace_collector
        if collector is None or not ray.is_initialized():
            return
        with self._lock:
            candidates = tuple(
                entry
                for entry in self._entries.values()
                if entry.trace_reference is not None
                and not entry.trace_recorded
            )
        if not candidates:
            return
        references = [
            entry.trace_reference
            for entry in candidates
            if entry.trace_reference is not None
        ]
        try:
            ready, _ = ray.wait(
                references,
                num_returns=len(references),
                timeout=0,
            )
        except Exception:
            return
        ready_set = set(ready)
        for entry in candidates:
            reference = entry.trace_reference
            if reference is None or reference not in ready_set:
                continue
            with self._lock:
                if entry.trace_recorded:
                    continue
                entry.trace_recorded = True
            try:
                trace = ray.get(reference)
                if isinstance(trace, TraceRecord):
                    collector.record(trace.observed())
            except Exception:
                # Trace collection is fail-open and never changes the result.
                pass


def _ray_output(
    component_spec: ComponentSpec,
    invocation: InvocationSpec,
    result: InvocationResult,
    *,
    trace_submitted_at: datetime | None,
    trace_input_size_bytes: int,
    scheduled_at: datetime,
    started_at: datetime,
    execution_started_monotonic: float,
    trace_event_sink: Any | None,
    trace_event_run_id: str | None,
    runtime_ids: tuple[str | None, str | None, str | None],
) -> InvocationResult | tuple[InvocationResult, TraceRecord | None]:
    finished_at = utc_now()
    task_id, actor_id, node_id = runtime_ids
    _send_trace_event(
        trace_event_sink,
        invocation,
        component_spec,
        event=TraceEventKind.FINISHED,
        source=TraceEventSource.WORKER,
        status=result.status,
        occurred_at=finished_at,
        run_id=trace_event_run_id,
        task_id=task_id,
        actor_id=actor_id,
        node_id=node_id,
        error_code=None if result.error is None else result.error.code,
        duration_seconds=max(0.0, time.monotonic() - execution_started_monotonic),
    )
    if trace_submitted_at is None:
        return result
    try:
        trace = build_trace_record(
            invocation,
            component_spec,
            result,
            backend="ray",
            submitted_at=trace_submitted_at,
            scheduled_at=scheduled_at,
            started_at=started_at,
            finished_at=finished_at,
            task_id=task_id,
            actor_id=actor_id,
            node_id=node_id,
            input_size_bytes=trace_input_size_bytes,
            output_size_bytes=(
                serialized_size(result.value) if result.succeeded else 0
            ),
        )
    except Exception:
        trace = None
    return result, trace


def _send_trace_event(
    sink: Any | None,
    invocation: InvocationSpec,
    component_spec: ComponentSpec,
    *,
    event: TraceEventKind,
    source: TraceEventSource,
    status: InvocationStatus,
    run_id: str | None,
    occurred_at: datetime | None = None,
    task_id: str | None = None,
    actor_id: str | None = None,
    node_id: str | None = None,
    error_code: str | None = None,
    duration_seconds: float | None = None,
) -> None:
    """Submit one payload-free event without affecting invocation outcome."""

    if sink is None or run_id is None:
        return
    try:
        trace_event = build_trace_event(
            invocation,
            component_spec,
            event=event,
            source=source,
            status=status,
            backend="ray",
            occurred_at=occurred_at,
            task_id=task_id,
            actor_id=actor_id,
            node_id=node_id,
            error_code=error_code,
            duration_seconds=duration_seconds,
            run_id=run_id,
        )
        sink.record.remote(trace_event)
    except Exception:
        # Incremental trace collection is fail-open like the v1 collector.
        pass


def _create_trace_event_sink(
    config: TraceEventJournalConfig | None,
) -> Any | None:
    if config is None:
        return None
    try:
        context = ray.get_runtime_context()
        node_id = _runtime_id(context, "get_node_id")
        if node_id is None:
            return None
        return _TraceEventJournalActor.options(
            num_cpus=0,
            max_restarts=1,
            max_task_retries=0,
            scheduling_strategy=NodeAffinitySchedulingStrategy(
                node_id=node_id,
                soft=False,
            ),
        ).remote(config)
    except Exception:
        return None


def _finalize_trace_event_sink(
    sink: Any | None,
    *,
    timeout_seconds: float,
) -> None:
    if sink is None:
        return
    try:
        ray.get(sink.finalize.remote(), timeout=timeout_seconds)
    except Exception:
        pass
    finally:
        try:
            ray.kill(sink, no_restart=True)
        except Exception:
            pass


def _runtime_ids() -> tuple[str | None, str | None, str | None]:
    try:
        context = ray.get_runtime_context()
    except Exception:
        return None, None, None
    return (
        _runtime_id(context, "get_task_id"),
        _runtime_id(context, "get_actor_id"),
        _runtime_id(context, "get_node_id"),
    )


def _runtime_id(context: object, method_name: str) -> str | None:
    try:
        value = getattr(context, method_name)()
        hex_method = getattr(value, "hex", None)
        text = hex_method() if callable(hex_method) else str(value)
    except Exception:
        return None
    if not text or set(text) <= {"0"}:
        return None
    return text


def _handle_for(
    invocation: InvocationSpec,
    reference: ray.ObjectRef,
) -> InvocationHandle:
    return InvocationHandle(
        invocation_id=invocation.invocation_id,
        component_id=invocation.component_id,
        reference=reference,
    )


def _timeout_result(invocation: InvocationSpec) -> InvocationResult:
    return InvocationResult(
        invocation_id=invocation.invocation_id,
        component_id=invocation.component_id,
        status=InvocationStatus.TIMED_OUT,
        error=FrameworkTimeoutError(
            "Ray invocation exceeded its deadline or timeout",
            framework_job_id=invocation.invocation_id,
        ),
    )


def _failure_result(
    invocation: InvocationSpec,
    error: RayQuantumError,
) -> InvocationResult:
    if isinstance(error, FrameworkTimeoutError):
        status = InvocationStatus.TIMED_OUT
    elif isinstance(error, CancellationError):
        status = InvocationStatus.CANCELLED
    else:
        status = InvocationStatus.FAILED
    return InvocationResult(
        invocation_id=invocation.invocation_id,
        component_id=invocation.component_id,
        status=status,
        error=error,
    )


def _construct_component(
    registration: ComponentRegistration,
) -> object:
    instance = registration.factory()
    try:
        return validate_component_instance(registration.spec, instance)
    except Exception:
        try:
            _close_component(instance)
        except Exception:
            pass
        raise


def _close_component(instance: object) -> None:
    close = getattr(instance, "close", None)
    if callable(close):
        close()


def _calculate_expiration_epoch(
    invocation: InvocationSpec,
    registration: ComponentRegistration,
) -> float | None:
    now_epoch = time.time()
    candidates: list[float] = []
    if registration.spec.timeout_seconds is not None:
        candidates.append(
            now_epoch + registration.spec.timeout_seconds
        )
    if invocation.deadline is not None:
        candidates.append(invocation.deadline.timestamp())
    return min(candidates) if candidates else None


def _remaining_timeout_seconds(
    expires_at_epoch: float | None,
) -> float | None:
    if expires_at_epoch is None:
        return None
    return max(0.0, expires_at_epoch - time.time())


def _cancel_reference(reference: ray.ObjectRef) -> None:
    try:
        ray.cancel(reference, force=False, recursive=True)
    except RayError:
        pass


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} must not be empty")
    if value != value.strip():
        raise ValueError(f"{name} must not have surrounding whitespace")
    return value


def _require_positive_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    normalized = float(value)
    if normalized <= 0 or normalized == float("inf") or normalized != normalized:
        raise ValueError(f"{name} must be finite and greater than zero")
    return normalized


__all__ = ["RayExecutor"]
