"""QASM3 export in the RX/RZ/CZ basis on the physical 0--1--2 chain."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass

from pivotq._internal.local_timing import scope, span
from pivotq._internal.errors import ValidationError

from .contracts import QuantumCircuitRequest


DEFAULT_SHOTS = 3000
# CZ is symmetric; list both directions for Qiskit's directed coupling graph.
QPU_COUPLING_MAP = [[0, 1], [1, 0], [1, 2], [2, 1]]
QPU_CZ_EDGES = {(0, 1), (1, 2)}


class CircuitExportError(ValueError):
    """The Qiskit exporter could not represent an application circuit."""


@dataclass(frozen=True, slots=True)
class QASM3Circuit:
    """Internal upload item, not a device wire protocol or shared file path."""

    circuit_id: str
    measurement_basis: str
    filename: str
    content: str


@dataclass(frozen=True, slots=True)
class PreparedCircuitBatch:
    circuits: tuple[QuantumCircuitRequest, ...]
    shots: int


def prepare_quantum_circuit_batch(
    *, circuits: Sequence[QuantumCircuitRequest], shots: int = DEFAULT_SHOTS,
) -> PreparedCircuitBatch:
    """Validate request metadata only; leave circuit acceptance to Qiskit."""
    if isinstance(circuits, (str, bytes)):
        raise ValidationError("circuits must be a sequence of requests")
    requests = tuple(circuits)
    if not requests:
        raise ValidationError("circuits must not be empty")
    seen: set[str] = set()
    for request in requests:
        if not isinstance(request, QuantumCircuitRequest):
            raise ValidationError("each item must be a QuantumCircuitRequest")
        if request.circuit_id in seen:
            raise ValidationError("duplicate circuit_id in one batch")
        seen.add(request.circuit_id)
    if isinstance(shots, bool) or not isinstance(shots, int):
        raise ValidationError("shots must be an integer")
    if shots <= 0:
        raise ValidationError("shots must be greater than zero")
    return PreparedCircuitBatch(requests, shots)


def _restore_logical_order(compiled):
    """Undo routing permutations before the server reads physical probabilities.

    The HTTP result contract has no layout field. Emit an ordinary q register
    rather than Qiskit's physical $0 syntax, preserving q0/q1/q2 semantics.
    """
    from qiskit import QuantumCircuit, transpile

    output = QuantumCircuit(compiled.num_qubits, compiled.num_clbits)
    output.global_phase = compiled.global_phase
    output.metadata = deepcopy(compiled.metadata)
    for item in compiled.data:
        output.append(item.operation,
                      [compiled.find_bit(bit).index for bit in item.qubits],
                      [compiled.find_bit(bit).index for bit in item.clbits])
    positions = compiled.layout.final_index_layout(filter_ancillas=False)
    logical_at = [None] * compiled.num_qubits
    for logical, physical in enumerate(positions):
        logical_at[physical] = logical
    correction = QuantumCircuit(compiled.num_qubits)
    for logical in range(compiled.num_qubits):
        physical = logical_at.index(logical)
        while physical > logical:
            correction.swap(physical - 1, physical)
            logical_at[physical - 1], logical_at[physical] = logical_at[physical], logical_at[physical - 1]
            physical -= 1
    if correction.data:
        # Only adjacent swaps were added. Level 0 decomposes them without a
        # fresh layout optimization that could reintroduce a permutation.
        correction = transpile(
            correction, basis_gates=["rx", "rz", "cz"],
            coupling_map=QPU_COUPLING_MAP,
            initial_layout=list(range(compiled.num_qubits)),
            routing_method="none", optimization_level=0, seed_transpiler=0,
        )
        output.compose(correction, inplace=True)
    return output


def _enforce_cz_topology(circuit):
    """Check the actual exported gates and canonicalize symmetric CZ operands."""
    for index, item in enumerate(circuit.data):
        if item.operation.name == "cz":
            edge = tuple(sorted(circuit.find_bit(bit).index for bit in item.qubits))
            if edge not in QPU_CZ_EDGES:
                raise ValueError("CZ outside the 0--1--2 topology")
            circuit.data[index] = item.replace(qubits=tuple(circuit.qubits[i] for i in edge))
        elif len(item.qubits) > 1 and item.operation.name != "barrier":
            raise ValueError("Unsupported multi-qubit gate after topology compilation")


def export_qasm3(circuit: object) -> str:
    """Optimize and route on 0--1--2, restore logical order, then export QASM3.

    Transpilation returns a new circuit without changing the caller's circuit.
    Successful export is not evidence of acceptance by the physical device.
    """
    from qiskit import qasm3, transpile

    try:
        with span("qasm.transpile"):
            # Measure the restored logical wires, not their temporary routing
            # locations. Keep any nonterminal measurements inside the circuit.
            body = circuit.copy()
            terminal = []
            while body.data and body.data[-1].operation.name in {"measure", "barrier"}:
                terminal.append(body.data.pop())
            compiled = transpile(
                body,
                basis_gates=["rx", "rz", "cz"],
                coupling_map=QPU_COUPLING_MAP,
                initial_layout=list(range(body.num_qubits)),
                optimization_level=3,
                seed_transpiler=0,
            )
            compiled = _restore_logical_order(compiled)
            for item in reversed(terminal):
                compiled.append(item.operation,
                                [circuit.find_bit(bit).index for bit in item.qubits],
                                [circuit.find_bit(bit).index for bit in item.clbits])
            _enforce_cz_topology(compiled)
        with span("qasm.dumps"):
            return qasm3.dumps(compiled)
    except Exception as error:
        # Do not put circuit contents or the exporter's exception body in logs.
        raise CircuitExportError(
            f"QASM3 export failed ({type(error).__name__})"
        ) from error


def export_batch(batch: PreparedCircuitBatch) -> tuple[QASM3Circuit, ...]:
    return tuple(
        QASM3Circuit(
            request.circuit_id, request.measurement_basis,
            f"circuit-{index:06d}.qasm", _export_with_identity(request),
        )
        for index, request in enumerate(batch.circuits)
    )


def _export_with_identity(request):
    with scope(circuit_id=request.circuit_id):
        return export_qasm3(request.circuit)
