"""Cluster-side AIMD coordinator imported by ``pivotq._internal.jobs.driver``."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from ...execution import AIMDRunRequest, ResourceRequest, TaskResult, execute_aimd_run_task
from .fusion_client import FusionExecutionClient
from .qpu_circuit_adapter import FusionQPUCircuitFeatureExtractor
from .registration import (
    AIMD_CONFIG_OVERRIDES_ENV,
    AIMD_CONFIG_PATH_ENV,
    _load_job_config_from_environment,
)


AIMD_CHECKPOINT_PATH_ENV = "AIMD_CHECKPOINT_PATH"
AIMD_EXECUTION_MODE_ENV = "AIMD_EXECUTION_MODE"
AIMD_QUANTUM_TARGET_ENV = "AIMD_QUANTUM_TARGET"
AIMD_TASK_ID_ENV = "AIMD_TASK_ID"


def run_aimd(framework: Any, context: Any) -> None:
    """Run one complete AIMD application through the framework-owned Driver.

    The Driver owns ``framework`` and its Ray connection.  This function only
    creates the application-side client, runs the scientific coordinator, and
    persists a structured result before returning or raising.
    """

    context.raise_if_stop_requested()
    request = _build_request(context)
    scheduled_quantum_api = _build_qpu_adapter(framework, context, request)
    result = execute_aimd_run_task(
        request,
        nested_client=FusionExecutionClient(framework),
        stop_checker=context.raise_if_stop_requested,
        scheduled_quantum_api=scheduled_quantum_api,
    )
    _write_result(context, result)
    _export_trace(context)
    context.raise_if_stop_requested()

    if result.status != "succeeded":
        error = dict(result.error or {})
        raise RuntimeError(
            "AIMD application failed: "
            f"run_id={result.run_id}, task_id={result.task_id}, "
            f"error_type={error.get('type', 'UnknownError')}, "
            f"message={error.get('message', 'unknown error')}"
        )


def _build_qpu_adapter(framework: Any, context: Any, request: AIMDRunRequest):
    if request.quantum_target != "qpu":
        return None
    try:
        from pivotq._internal.qpu_integration import QPUCircuitService
    except ImportError as error:
        raise RuntimeError(
            "quantum_target='qpu' 需要融合框架提供 pivotq._internal.qpu_integration。"
        ) from error

    config = _load_job_config_from_environment()
    qpu_schedule = dict(dict(config["scheduling"])["quantum_targets"])["qpu"]
    execution = dict(dict(qpu_schedule).get("execution", {}))
    shots = int(execution.get("shots", 3000))
    raw_physical_qubits = execution.get("physical_qubits")
    physical_qubits = None
    if raw_physical_qubits not in (None, []):
        if not isinstance(raw_physical_qubits, (list, tuple)):
            raise ValueError("qpu.execution.physical_qubits 必须是列表或 null。")
        physical_qubits = tuple(str(value) for value in raw_physical_qubits)
    return FusionQPUCircuitFeatureExtractor(
        QPUCircuitService(framework, context),
        shots=shots,
        physical_qubits=physical_qubits,
    )


def _build_request(context: Any) -> AIMDRunRequest:
    config_path = _required_absolute_path(AIMD_CONFIG_PATH_ENV)
    checkpoint_path = _required_absolute_path(AIMD_CHECKPOINT_PATH_ENV)
    output_dir = Path(context.output_dir).expanduser().resolve()
    if not output_dir.is_absolute():
        raise ValueError("RayJobDriverContext.output_dir must be absolute.")

    config = _load_job_config_from_environment()
    coordinator = dict(dict(config["scheduling"])["coordinator"])
    resources = ResourceRequest.from_dict(dict(coordinator["resources"]))
    if resources.cpu <= 0.0 or resources.gpu > 0.0 or resources.qpu > 0.0:
        raise ValueError(
            "The AIMD Ray Job Driver must be a CPU-only coordinator; "
            "nested components own GPU/QPU resources."
        )

    execution_mode = os.environ.get(AIMD_EXECUTION_MODE_ENV, "heterogeneous")
    quantum_target = os.environ.get(AIMD_QUANTUM_TARGET_ENV, "gpu")
    task_id = os.environ.get(AIMD_TASK_ID_ENV, f"{context.run_id}.aimd")
    overrides = _mapping_from_environment(AIMD_CONFIG_OVERRIDES_ENV)
    return AIMDRunRequest(
        run_id=str(context.run_id),
        task_id=task_id,
        config_path=str(config_path),
        checkpoint_path=str(checkpoint_path),
        output_dir=str(output_dir),
        execution_mode=execution_mode,
        quantum_target=quantum_target,
        config_overrides=overrides,
        resources=resources,
        idempotency_key=str(context.run_id),
        metadata={
            "entrypoint": "pivotq._internal.jobs.driver",
            "integration": "single_h20_aimd.fusion_framework.v1",
        },
    )


def _required_absolute_path(environment_name: str) -> Path:
    value = os.environ.get(environment_name)
    if not value:
        raise RuntimeError(f"{environment_name} is required by the AIMD Ray Job runner.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(
            f"{environment_name} must be an absolute path visible on the Ray cluster."
        )
    if not path.is_file():
        raise FileNotFoundError(f"{environment_name} does not exist: {path}")
    return path.resolve()


def _mapping_from_environment(environment_name: str) -> dict[str, Any]:
    text = os.environ.get(environment_name, "").strip()
    if not text:
        return {}
    value = json.loads(text)
    if not isinstance(value, Mapping):
        raise ValueError(f"{environment_name} must contain a JSON object.")
    return dict(value)


def _write_result(context: Any, result: TaskResult) -> Path:
    destination = Path(context.output_dir) / f"{context.run_id}.aimd-result.json"
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def _export_trace(context: Any) -> Path | None:
    collector = context.trace_collector
    if collector is None:
        return None
    from pivotq._internal.observability import export_trace_jsonl

    return export_trace_jsonl(
        collector,
        Path(context.output_dir) / f"{context.run_id}.trace.jsonl",
    )


__all__ = [
    "AIMD_CHECKPOINT_PATH_ENV",
    "AIMD_CONFIG_OVERRIDES_ENV",
    "AIMD_EXECUTION_MODE_ENV",
    "AIMD_QUANTUM_TARGET_ENV",
    "AIMD_TASK_ID_ENV",
    "_build_qpu_adapter",
    "run_aimd",
]
