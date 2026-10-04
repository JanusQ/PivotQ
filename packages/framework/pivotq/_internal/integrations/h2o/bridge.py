"""Framework-owned registration and runner using AIMD's existing injection API."""

from dataclasses import replace
from copy import deepcopy
import json
import os

from pivotq._internal.framework import ResourceRequest
from pivotq._internal.qpu_integration import QPUCircuitService
from pivotq._internal.qpu_integration.component import DEFAULT_QPU_COMPONENT_ID


def register_components(framework):
    from single_h20_aimd.integration.fusion_framework.registration import register_components as original
    from single_h20_aimd.integration.fusion_framework.fusion_client import FusionComponentIds
    from .adapters import CPUClassicalSessionsComponent, CPUQuantumFeaturesComponent

    original(framework)
    if not framework.simulation:
        return
    ids = FusionComponentIds()
    logical_hardware = json.loads(os.environ.get('AIMD_LOGICAL_HARDWARE_JSON', '{}'))
    if logical_hardware.get('classical_predict') == 'cpu':
        registered = framework.unregister(ids.classical_actor)
        framework.register(replace(
            registered.spec, resources=ResourceRequest(num_cpus=max(registered.spec.resources.num_cpus, 0.25)),
        ), registered.factory)
    for component_id, factory, backend in (
        (ids.quantum_gpu, CPUQuantumFeaturesComponent, "adapt_water_statevector"),
        (ids.classical_actor, CPUClassicalSessionsComponent, "torch_cpu"),
    ):
        requested = framework.describe(component_id).resources
        if not requested.num_gpus:
            # A logical CPU target is already registered as CPU. Calling it
            # a GPU fallback would corrupt the framework's execution report.
            continue
        framework.register_simulation_adapter(
            component_id,
            factory=factory,
            resources=ResourceRequest(num_cpus=max(requested.num_cpus, 0.25)),
            required_devices=("GPU",),
            backend=backend,
        )


def _simulation_client(framework, logical_hardware):
    """Translate CPU choices at the application/framework request boundary.

    The frozen application's scheduler retains GPU-shaped deployment defaults.
    Logical CPU requests use its existing CPU backend before the framework sees
    them, so both requested and effective resources describe the user's choice.
    """
    from single_h20_aimd.execution import ResourceRequest as ApplicationResources
    from single_h20_aimd.integration.fusion_framework.fusion_client import FusionExecutionClient

    class LogicalTargetClient(FusionExecutionClient):
        def submit(self, request):
            if logical_hardware.get('quantum_features') == 'cpu':
                payload = deepcopy(request.payload)
                payload['backend'] = 'adapt_water_statevector'
                payload['quantum_request'].setdefault('execution_spec', {}).update(
                    device='cpu', mode='exact_statevector', gradient_method='none',
                )
                request = replace(request, payload=payload, resources=ApplicationResources(
                    cpu=max(request.resources.cpu, 0.25), memory_bytes=request.resources.memory_bytes,
                ))
            return super().submit(request)

        def create_actor(self, request):
            if logical_hardware.get('classical_predict') == 'cpu':
                payload = deepcopy(request.payload)
                payload.update(device='cpu', require_gpu=False)
                request = replace(request, payload=payload, resources=ApplicationResources(
                    cpu=max(request.resources.cpu, 0.25), memory_bytes=request.resources.memory_bytes,
                ))
            return super().create_actor(request)

    return LogicalTargetClient(framework)


def run(framework, context):
    from single_h20_aimd.execution import execute_aimd_run_task
    from single_h20_aimd.integration.fusion_framework.runner import (
        _build_request, _build_qpu_adapter, _write_result, _export_trace, run_aimd,
    )
    from single_h20_aimd.integration.fusion_framework.registration import _load_job_config_from_environment
    from .adapters import SimulatedQPUCircuitFeatureExtractor

    if not framework.simulation:
        return run_aimd(framework, context)

    context.raise_if_stop_requested()
    logical_hardware = json.loads(os.environ.get('AIMD_LOGICAL_HARDWARE_JSON', '{}'))
    request = _build_request(context)
    quantum_api = None
    if request.quantum_target == "qpu":
        selection = framework.resolve_execution(DEFAULT_QPU_COMPONENT_ID)
        if selection.simulated:
            config = _load_job_config_from_environment()
            execution = config["scheduling"]["quantum_targets"]["qpu"].get("execution", {})
            quantum_api = SimulatedQPUCircuitFeatureExtractor(
                QPUCircuitService(framework, context),
                shots=int(execution.get("shots", 3000)),
                physical_qubits=execution.get("physical_qubits") or None,
            )
        else:
            quantum_api = _build_qpu_adapter(framework, context, request)
    result = execute_aimd_run_task(
        request,
        nested_client=_simulation_client(framework, logical_hardware),
        stop_checker=context.raise_if_stop_requested,
        scheduled_quantum_api=quantum_api,
    )
    outputs = dict(result.outputs)
    # Original AIMD describes requested GPU/QPU targets. Preserve that declaration
    # explicitly while the framework owns the authoritative execution report.
    outputs["requested_execution"] = outputs.pop("execution", {})
    if logical_hardware:
        outputs["requested_execution"].update(
            quantum_target=logical_hardware.get('quantum_features', request.quantum_target),
            classical_actor_target=logical_hardware.get('classical_predict', 'gpu'),
        )
    outputs["runtime_execution"] = framework.execution_report()
    if isinstance(quantum_api, SimulatedQPUCircuitFeatureExtractor):
        outputs["runtime_execution"]["qpu_simulation"] = {
            **quantum_api.describe(), **quantum_api.execution_counters(),
        }
    result = replace(result, outputs=outputs)
    _write_result(context, result)
    _export_trace(context)
    context.raise_if_stop_requested()
    if result.status != "succeeded":
        raise RuntimeError(f"AIMD application failed: {result.error}")
