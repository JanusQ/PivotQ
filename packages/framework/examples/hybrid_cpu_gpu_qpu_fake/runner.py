"""Run and verify one CPU -> CUDA GPU -> server-side fixed-response client chain."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from typing import Any

from qiskit import QuantumCircuit

from pivotq._internal.framework import FusionFramework
from pivotq._internal.jobs import RayJobDriverContext
from pivotq._internal.models import StringMetadata
from pivotq._internal.observability import export_trace_jsonl
from pivotq._internal.qpu_integration import (
    QPUCircuitService,
    QuantumCircuitRequest,
)
from pivotq._internal.qpu_integration.component import DEFAULT_QPU_COMPONENT_ID

from .registration import CPU_COMPONENT_ID, CPU_HEAD_RESOURCE, GPU_COMPONENT_ID


_SHOTS = 256


class HybridFakeValidationError(RuntimeError):
    """The bounded validation chain returned incorrect evidence."""


def run_validation(
    framework: FusionFramework,
    context: RayJobDriverContext,
) -> None:
    """Driver runner used by the Ray Job bootstrap."""

    collector = context.trace_collector
    if collector is None:
        raise RuntimeError("the validation job requires trace collection")

    prepare_handle = framework.submit(
        CPU_COMPONENT_ID,
        "prepare",
        invocation_id=f"{context.run_id}.cpu",
        trace_context=_trace_context(context.run_id, "cpu"),
    )
    gpu_handle = framework.submit(
        GPU_COMPONENT_ID,
        "compute",
        prepare_handle,
        invocation_id=f"{context.run_id}.gpu",
        trace_context=_trace_context(context.run_id, "gpu"),
    )
    try:
        gpu_result = framework.result(gpu_handle)
        if not gpu_result.succeeded or not isinstance(gpu_result.value, dict):
            raise HybridFakeValidationError("CPU/GPU framework chain failed")
        gpu_value = dict(gpu_result.value)
    finally:
        framework.release(gpu_handle)
        framework.release(prepare_handle)

    angle = float(gpu_value["angle_radians"])
    circuit = QuantumCircuit(3)
    circuit.rx(angle, 2)
    qpu_results = QPUCircuitService(framework, context).run_quantum_circuits(
        step=0,
        circuits=[
            QuantumCircuitRequest(
                circuit_id="gpu-derived-rx",
                circuit=circuit,
                measurement_basis="Z",
            )
        ],
        shots=_SHOTS,
    )

    traces = collector.snapshot()
    cluster = _cluster_snapshot()
    qpu_component_is_serial = (
        framework.describe(DEFAULT_QPU_COMPONENT_ID).max_concurrency == 1
    )
    checks = _validate(
        run_id=context.run_id,
        angle=angle,
        gpu_value=gpu_value,
        qpu_results=qpu_results,
        traces=traces,
        cluster=cluster,
        qpu_component_is_serial=qpu_component_is_serial,
    )
    trace_path = context.output_dir / f"{context.run_id}.hybrid-fake.trace.jsonl"
    result_path = context.output_dir / f"{context.run_id}.hybrid-fake.result.json"
    export_trace_jsonl(traces, trace_path)
    document = {
        "schema_version": 1,
        "run_id": context.run_id,
        "status": "passed",
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "framework_validation": True,
            "real_cuda_gpu_used": True,
            "logical_qpu_resource_used": False,
            "fixed_count_fixture_used": True,
            "qiskit_statevector_used": False,
            "qpu_hardware_used": False,
            "scientific_qpu_result": False,
        },
        "cluster": cluster,
        "gpu_stage": gpu_value,
        "qpu_results": qpu_results,
        "checks": checks,
        "trace": {
            "file": trace_path.name,
            "records": len(traces),
            "dropped_records": collector.dropped_records,
        },
    }
    _write_exclusive_json(result_path, document)
    print(json.dumps(document, ensure_ascii=False, sort_keys=True), flush=True)
    print("HYBRID_CPU_GPU_FAKE_QPU_RESULT=PASS", flush=True)


def _validate(
    *,
    run_id: str,
    angle: float,
    gpu_value: dict[str, Any],
    qpu_results: list[dict[str, Any]],
    traces: tuple[Any, ...],
    cluster: dict[str, Any],
    qpu_component_is_serial: bool,
) -> dict[str, Any]:
    by_invocation = {trace.invocation_id: trace for trace in traces}
    cpu_trace = by_invocation.get(f"{run_id}.cpu")
    gpu_trace = by_invocation.get(f"{run_id}.gpu")
    qpu_trace = by_invocation.get(f"{run_id}.qpu.000000")
    if cpu_trace is None or gpu_trace is None or qpu_trace is None:
        raise HybridFakeValidationError("expected CPU, GPU, and QPU traces")

    probabilities = qpu_results[0]["probabilities"] if len(qpu_results) == 1 else {}
    nodes = cluster["nodes"]
    node_by_resource = {
        resource: next(
            (node["node_id"] for node in nodes if node["resources"].get(resource, 0) >= 1),
            None,
        )
        for resource in (CPU_HEAD_RESOURCE, "GPU")
    }
    checks = {
        "two_alive_nodes": len(nodes) == 2,
        "required_resources_present": all(node_by_resource.values()),
        "cpu_on_designated_head": cpu_trace.node_id == node_by_resource[CPU_HEAD_RESOURCE],
        "gpu_on_gpu_node": gpu_trace.node_id == node_by_resource["GPU"],
        "qpu_client_on_server": qpu_trace.node_id == node_by_resource[CPU_HEAD_RESOURCE],
        "cpu_gpu_nodes_distinct": cpu_trace.node_id != gpu_trace.node_id,
        "cpu_client_nodes_same": cpu_trace.node_id == qpu_trace.node_id,
        "cuda_executed": gpu_value["runtime"].get("cuda_available") is True,
        "gpu_accelerator_assigned": bool(
            gpu_value["runtime"].get("accelerator_ids", {}).get("GPU")
        ),
        "gpu_angle_is_pi": math.isclose(angle, math.pi, rel_tol=0.0, abs_tol=1e-12),
        "qpu_actor_is_serial": qpu_component_is_serial,
        "client_server_placement": qpu_trace.resources.custom_resources_dict()
        == {CPU_HEAD_RESOURCE: 0.001},
        "qpu_result_identity": bool(qpu_results)
        and qpu_results[0].get("circuit_id") == "gpu-derived-rx",
        "measurement_basis_round_trip": bool(qpu_results)
        and qpu_results[0].get("measurement_basis") == "Z",
        "fixture_has_all_eight_states": set(probabilities) == {f"{state:03b}" for state in range(8)},
        "probabilities_sum_to_one": math.isclose(
            sum(float(value) for value in probabilities.values()),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-6,
        ),
        "fixed_response_100_is_one": probabilities.get("100") == 1.0,
    }
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise HybridFakeValidationError("failed checks: " + ", ".join(failed))
    return checks


def _cluster_snapshot() -> dict[str, Any]:
    import ray

    nodes = []
    for node in ray.nodes():
        if not node.get("Alive"):
            continue
        resources = {
            str(name): float(quantity)
            for name, quantity in dict(node.get("Resources", {})).items()
            if name in {"CPU", "GPU", "QPU", CPU_HEAD_RESOURCE}
        }
        nodes.append(
            {
                "node_id": str(node.get("NodeID")),
                "private_ip": str(node.get("NodeManagerAddress")),
                "resources": dict(sorted(resources.items())),
            }
        )
    nodes.sort(key=lambda item: item["private_ip"])
    return {
        "nodes": nodes,
        "cluster_resources": {
            str(name): float(quantity)
            for name, quantity in ray.cluster_resources().items()
            if name in {"CPU", "GPU", "QPU", CPU_HEAD_RESOURCE}
        },
    }


def _trace_context(run_id: str, stage: str) -> StringMetadata:
    return StringMetadata.from_mapping(
        {"run_id": run_id, "stage": stage, "validation_only": "true"}
    )


def _write_exclusive_json(path: Path, document: dict[str, Any]) -> None:
    path = path.resolve()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        if path.exists():
            raise FileExistsError(f"refusing to overwrite validation artifact: {path}")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


__all__ = ["HybridFakeValidationError", "run_validation"]
