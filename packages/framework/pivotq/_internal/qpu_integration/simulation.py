"""Ideal three-qubit CPU implementation of the QPU circuit interface.

The application has already applied measurement-basis rotations. Probabilities
are exact; the echoed shots value is compatibility information, not sampling.
"""

from __future__ import annotations

from collections.abc import Sequence
import json
import os
from pathlib import Path
from threading import Lock

from pivotq._internal.errors import ValidationError

from .contracts import CircuitResult, QuantumCircuitRequest
from .qasm3_export import DEFAULT_SHOTS, prepare_quantum_circuit_batch


def qpu_is_configured() -> bool:
    """Inspect configuration without connecting to a physical device.

    A configured endpoint is considered available even if it is busy/offline.
    Connection and execution failures remain errors and are never retried on CPU.
    """
    config_file = os.environ.get("QPU_DEVICE_CONFIG_FILE")
    if config_file:
        try:
            device = json.loads(Path(config_file).read_text())[os.environ.get("QPU_DEVICE_ID", "")]
            url = device.get("url")
            if url is None:
                return False
            if not isinstance(url, str):
                raise TypeError("Configured QPU URL must be text")
            return bool(url.strip())
        except (FileNotFoundError, KeyError):
            return False
    return bool(os.environ.get("QPU_DEVICE_URL", "").strip())


class StatevectorQPUComponent:
    """Serial exact-probability replacement; never creates a device adapter."""

    def __init__(self) -> None:
        self._closed = False
        self._call_lock = Lock()

    def describe(self) -> dict[str, object]:
        return {
            "interface": "run_quantum_circuits",
            "backend": "qiskit_statevector",
            "device": "cpu",
            "simulation": True,
            "mode": "exact_probabilities",
            "real_hardware": False,
            "effective_shots": None,
            "total_physical_executions": 0,
            "noise": False,
            "result_bit_order": "q0,q1,q2 left-to-right",
        }

    def run_quantum_circuits(
        self, circuits: Sequence[QuantumCircuitRequest], *,
        shots: int = DEFAULT_SHOTS, request_id: str,
    ) -> list[CircuitResult]:
        from qiskit import QuantumCircuit
        from qiskit.quantum_info import Statevector

        if not self._call_lock.acquire(blocking=False):
            raise RuntimeError("QPU simulator is busy; concurrent local calls are not queued")
        try:
            if self._closed:
                raise RuntimeError("QPU simulator is closed")
            if not isinstance(request_id, str) or not request_id.strip():
                raise ValueError("request_id must be nonempty text")
            batch = prepare_quantum_circuit_batch(circuits=circuits, shots=shots)
            results: list[CircuitResult] = []
            for request in batch.circuits:
                circuit = request.circuit
                if not isinstance(circuit, QuantumCircuit) or circuit.num_qubits != 3:
                    raise ValidationError("QPU simulation requires a three-qubit QuantumCircuit")
                # Reject stochastic/dynamic operations instead of silently sampling.
                if circuit.num_parameters or any(
                    item.operation.name in {"measure", "reset", "initialize"}
                    or item.clbits or getattr(item.operation, "condition", None) is not None
                    for item in circuit.data
                ):
                    raise ValidationError("Exact QPU simulation requires a bound, unitary circuit without measurements")
                values = Statevector.from_instruction(circuit).probabilities()
                values = values / values.sum()
                # Qiskit's array index is q2q1q0; the public API uses q0q1q2.
                probabilities = {
                    f"{index:03b}": float(values[int(f"{index:03b}"[::-1], 2)])
                    for index in range(8)
                }
                results.append({
                    "circuit_id": request.circuit_id,
                    "shots": batch.shots,
                    "measurement_basis": request.measurement_basis,
                    "measurement_qubits": [0, 1, 2],
                    "probabilities": probabilities,
                    "simulation": {**self.describe(), "requested_shots": batch.shots},
                })
            return results
        finally:
            self._call_lock.release()

    def close(self) -> None:
        with self._call_lock:
            self._closed = True
