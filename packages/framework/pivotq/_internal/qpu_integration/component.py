"""Serial client component on a framework server, owned by the current Job."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from threading import Lock
import os
import json
from pathlib import Path

from pivotq._internal.local_timing import flush, scope, span
from pivotq._internal.errors import ExecutionError, ResultUnknownError, ValidationError
from pivotq._internal.framework import ComponentSpec, ExecutionMode, FusionFramework, ResourceRequest
from pivotq._internal.framework.registry import ComponentRegistration

from .contracts import CircuitResult, QuantumCircuitRequest
from .device_adapter import (
    DeviceClientError, DeviceExecutionUnknownError, DeviceProtocolNotConfiguredError,
    DeviceResultError, QPUDeviceAdapter,
)
from .qasm3_export import DEFAULT_SHOTS, export_batch, prepare_quantum_circuit_batch


DEFAULT_QPU_COMPONENT_ID = "qpu-circuits"


@dataclass(frozen=True, slots=True)
class QPUClientFactory:
    # Explicit injection is for offline tests; the production default is the
    # HTTP adapter and never substitutes a simulator.
    adapter_factory: Callable[[], QPUDeviceAdapter] = QPUDeviceAdapter

    def __call__(self) -> QPUClientComponent:
        config_file = os.environ.get('QPU_DEVICE_CONFIG_FILE')
        if config_file and self.adapter_factory is QPUDeviceAdapter:
            device_id = os.environ.get('QPU_DEVICE_ID', '')
            try:
                device = json.loads(Path(config_file).read_text())[device_id]
                url, key = device['url'], device.get('api_key')
            except (OSError, ValueError, KeyError, TypeError):
                raise DeviceProtocolNotConfiguredError('Registered QPU node-local configuration is unavailable') from None
            return QPUClientComponent(adapter=QPUDeviceAdapter(server_url=url, api_key=key,
                probability_source='expr_prob', journal_dir=os.environ.get('QPU_JOB_JOURNAL_DIR'),
                timeout_seconds=device.get('timeout_seconds', 3600.0)))
        return QPUClientComponent(adapter=self.adapter_factory())


class QPUClientComponent:
    def __init__(self, *, adapter: QPUDeviceAdapter | None = None) -> None:
        self._adapter = adapter if adapter is not None else QPUDeviceAdapter()
        self._call_lock = Lock()
        self._closed = False

    def describe(self) -> dict[str, object]:
        return {
            "interface": "run_quantum_circuits", "blocking": True,
            "backend_max_concurrency": 1, "deployment": "framework_server",
            "input_format": "openqasm3", "result_format": "full-probabilities-3q-v1",
        }

    def run_quantum_circuits(
        self, circuits: Sequence[QuantumCircuitRequest], *,
        shots: int = DEFAULT_SHOTS, request_id: str,
    ) -> list[CircuitResult]:
        if not self._call_lock.acquire(blocking=False):
            raise RuntimeError("QPU client is busy; concurrent local calls are not queued")
        try:
            if self._closed:
                raise RuntimeError("QPU client is closed")
            if not isinstance(request_id, str) or not request_id.strip():
                raise ValueError("request_id must be nonempty text")
            with scope(request_id=request_id), span("qpu.component_call"):
                batch = prepare_quantum_circuit_batch(circuits=circuits, shots=shots)
                programs = export_batch(batch)
                try:
                    return self._adapter.execute_batch(
                        programs, shots=batch.shots, request_id=request_id,
                    )
                except (
                    DeviceClientError, DeviceExecutionUnknownError,
                    DeviceProtocolNotConfiguredError, DeviceResultError,
                ) as error:
                    # Only the production HTTP adapter owns the controlled diagnostic
                    # messages. Keep injected adapters on the generic error boundary.
                    if type(self._adapter) is not QPUDeviceAdapter:
                        raise
                    if isinstance(error, DeviceProtocolNotConfiguredError):
                        error_type = ValidationError
                    elif isinstance(error, (DeviceExecutionUnknownError, DeviceResultError)):
                        error_type = ResultUnknownError
                    else:
                        error_type = ExecutionError
                    raise error_type(
                        str(error), framework_job_id=request_id,
                    ) from None
        finally:
            self._call_lock.release()
            flush()

    def close(self) -> None:
        with self._call_lock:
            if not self._closed:
                self._adapter.close()
                self._closed = True


def build_qpu_client_spec(
    *, component_id: str = DEFAULT_QPU_COMPONENT_ID,
    num_cpus: float = 1.0,
    custom_resources: Mapping[str, int | float] | None = None,
    timeout_seconds: float | None = None,
) -> ComponentSpec:
    # Every Ray node is a prepared compute server; CPU capacity selects the node.
    return ComponentSpec(
        component_id=component_id, execution=ExecutionMode.ACTOR,
        resources=ResourceRequest(
            num_cpus=num_cpus,
            custom_resources=custom_resources or {},
        ),
        allowed_methods=("run_quantum_circuits",), stateful=True,
        max_concurrency=1, timeout_seconds=timeout_seconds,
    )


def register_qpu_client(
    framework: FusionFramework, *,
    adapter_factory: Callable[[], QPUDeviceAdapter] = QPUDeviceAdapter,
    component_id: str = DEFAULT_QPU_COMPONENT_ID,
    num_cpus: float = 1.0,
    custom_resources: Mapping[str, int | float] | None = None,
    timeout_seconds: float | None = None,
) -> ComponentRegistration:
    registration = framework.register(
        build_qpu_client_spec(
            component_id=component_id, num_cpus=num_cpus,
            custom_resources=custom_resources,
            timeout_seconds=timeout_seconds,
        ),
        QPUClientFactory(adapter_factory),
    )
    if not getattr(framework, "simulation", False):
        return registration
    from .simulation import StatevectorQPUComponent, qpu_is_configured

    framework.register_simulation_adapter(
        component_id,
        factory=StatevectorQPUComponent,
        resources=ResourceRequest(num_cpus=max(num_cpus, 0.25)),
        required_devices=("QPU",),
        availability=qpu_is_configured if adapter_factory is QPUDeviceAdapter else lambda: True,
        backend="qiskit_statevector",
    )
    return registration


__all__ = [
    "DEFAULT_QPU_COMPONENT_ID",
    "QPUClientComponent", "QPUClientFactory", "build_qpu_client_spec", "register_qpu_client",
]
