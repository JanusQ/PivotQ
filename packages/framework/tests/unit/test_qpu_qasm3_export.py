"""RX/RZ/CZ export preserves circuit semantics, measurements and metadata."""

from copy import deepcopy
import math
import re
from unittest.mock import patch

import numpy as np
import pytest
from qiskit import QuantumCircuit, qasm3
from qiskit.circuit import Parameter
from qiskit.quantum_info import Operator, Statevector

from pivotq._internal.errors import ValidationError
from pivotq._internal.qpu_integration import QuantumCircuitRequest
from pivotq._internal.qpu_integration.qasm3_export import (
    CircuitExportError, export_batch, export_qasm3, prepare_quantum_circuit_batch,
)


@pytest.fixture
def compiled_exports(monkeypatch):
    """Capture the actual compiled input while still running Qiskit's exporter."""
    captured = []
    real_dumps = qasm3.dumps

    def capture(circuit, *args, **kwargs):
        captured.append(circuit.copy())
        return real_dumps(circuit, *args, **kwargs)

    monkeypatch.setattr(qasm3, "dumps", capture)
    return captured


def assert_same_operator(original, compiled):
    # Operator.equiv intentionally ignores global phase; compare full matrices.
    np.testing.assert_allclose(
        Operator(compiled).data, Operator(original).data, atol=1e-12, rtol=0,
    )


def measurement_mapping(circuit):
    return [
        (circuit.find_bit(item.qubits[0]).index, circuit.find_bit(item.clbits[0]).index)
        for item in circuit.data if item.operation.name == "measure"
    ]


@pytest.mark.parametrize("basis", ["X", "Y", "Z"])
def test_export_preserves_circuit_measurements_phase_and_metadata(basis, compiled_exports):
    circuit = QuantumCircuit(3, 2)
    circuit.h(0)
    circuit.cx(0, 2)
    if basis == "Y":
        circuit.sdg(2)
        circuit.h(2)
    circuit.measure(2, 0)
    circuit.measure(0, 1)
    circuit.global_phase = 0.25
    circuit.metadata = {"measurement_basis": basis}
    before = circuit.copy()
    before_metadata = deepcopy(circuit.metadata)
    batch = prepare_quantum_circuit_batch(
        circuits=[QuantumCircuitRequest("../not-a-file", circuit, basis)], shots=64,
    )
    item, = export_batch(batch)
    compiled, = compiled_exports
    assert set(compiled.count_ops()) <= {"rx", "rz", "cz", "measure"}
    assert compiled.num_qubits == circuit.num_qubits
    assert compiled.num_clbits == circuit.num_clbits
    assert sorted(measurement_mapping(compiled)) == [(0, 1), (2, 0)]
    assert_same_operator(
        circuit.remove_final_measurements(inplace=False),
        compiled.remove_final_measurements(inplace=False),
    )
    assert item.content.startswith("OPENQASM 3.0;")
    assert item.filename == "circuit-000000.qasm"
    assert item.circuit_id == "../not-a-file"
    assert item.measurement_basis == basis
    assert circuit == before
    assert circuit.metadata == before_metadata


def test_export_rewrites_single_qubit_gates_and_keeps_cz_edges(compiled_exports):
    circuit = QuantumCircuit(3)
    circuit.rz(0.23, 0)
    circuit.h(1)
    circuit.sx(2)
    circuit.cz(0, 1)
    circuit.ry(-0.61, 0)
    circuit.rz(2.2, 2)
    circuit.cz(1, 2)
    circuit.global_phase = 0.31
    before = circuit.copy()
    export_qasm3(circuit)
    compiled, = compiled_exports
    assert set(compiled.count_ops()) <= {"rx", "rz", "cz"}
    assert compiled.num_qubits == 3
    assert [
        tuple(compiled.find_bit(bit).index for bit in item.qubits)
        for item in compiled.data if item.operation.name == "cz"
    ] == [(0, 1), (1, 2)]
    assert_same_operator(circuit, compiled)
    assert circuit == before


@pytest.mark.parametrize("qubit, logical_state", [(0, "100"), (1, "010"), (2, "001")])
def test_export_keeps_logical_qubit_order(qubit, logical_state, compiled_exports):
    circuit = QuantumCircuit(3)
    circuit.ry(math.pi, qubit)
    circuit.rz(0.37, (qubit + 1) % 3)
    circuit.cz(0, 1)
    circuit.cz(1, 2)
    export_qasm3(circuit)
    compiled, = compiled_exports
    assert_same_operator(circuit, compiled)
    probabilities = Statevector.from_instruction(compiled).probabilities_dict()
    # Qiskit labels are q2,q1,q0; the application contract is q0,q1,q2.
    assert max(probabilities, key=probabilities.get)[::-1] == logical_state


def test_opaque_input_is_rejected_by_compilation(compiled_exports):
    supplied = object()
    request = QuantumCircuitRequest("opaque", supplied, "Y")
    batch = prepare_quantum_circuit_batch(circuits=[request])
    with pytest.raises(CircuitExportError, match="QASM3 export failed"):
        export_batch(batch)
    assert compiled_exports == []


def test_export_preserves_unbound_rx_parameter(compiled_exports):
    theta = Parameter("theta")
    parameterized = QuantumCircuit(3)
    parameterized.rx(theta, 0)
    before = parameterized.copy()
    program = export_qasm3(parameterized)
    compiled, = compiled_exports
    assert program.startswith("OPENQASM 3.0;")
    assert set(compiled.parameters) == {theta}
    assert set(compiled.count_ops()) == {"rx"}
    assert_same_operator(
        parameterized.assign_parameters({theta: 0.43}),
        compiled.assign_parameters({theta: 0.43}),
    )
    assert parameterized == before


def test_export_adds_no_measurements_or_basis_rotations(compiled_exports):
    circuit = QuantumCircuit(3)
    circuit.rx(0.4, 1)
    program = export_batch(prepare_quantum_circuit_batch(
        circuits=[QuantumCircuitRequest("basis-only", circuit, "Y")],
    ))[0].content
    compiled, = compiled_exports
    assert compiled.count_ops() == {"rx": 1}
    assert compiled.num_clbits == 0
    assert_same_operator(circuit, compiled)
    assert "measure" not in program
    assert "sdg" not in program


def test_multiple_circuits_keep_ids_bases_filenames_and_input_metadata(compiled_exports):
    requests = []
    snapshots = []
    for index, basis in enumerate(("Z", "X", "Y")):
        circuit = QuantumCircuit(3)
        circuit.rz(0.17 + index * 0.23, index)
        circuit.ry(-0.38, (index + 1) % 3)
        circuit.metadata = {"basis": basis, "nested": {"sample": index}}
        snapshots.append((circuit.copy(), deepcopy(circuit.metadata)))
        requests.append(QuantumCircuitRequest(f"sample/{index}.{basis}", circuit, basis))

    items = export_batch(prepare_quantum_circuit_batch(circuits=requests))
    assert len(items) == len(compiled_exports) == 3
    for index, (item, request, compiled, snapshot) in enumerate(
        zip(items, requests, compiled_exports, snapshots)
    ):
        assert item.filename == f"circuit-{index:06d}.qasm"
        assert item.circuit_id == request.circuit_id
        assert item.measurement_basis == request.measurement_basis
        assert item.content.startswith("OPENQASM 3.0;")
        assert set(compiled.count_ops()) <= {"rx", "rz", "cz"}
        assert_same_operator(request.circuit, compiled)
        assert request.circuit == snapshot[0]
        assert request.circuit.metadata == snapshot[1]


@pytest.mark.parametrize("stage", ["qiskit.transpile", "qiskit.qasm3.dumps"])
def test_export_failure_is_explicit_and_does_not_include_payload_in_message(stage):
    circuit = QuantumCircuit(3)
    circuit.rz(0.4, 0)
    with patch(stage, side_effect=ValueError("private circuit data")):
        with pytest.raises(CircuitExportError, match="QASM3 export failed") as caught:
            export_qasm3(circuit)
    assert "private circuit data" not in str(caught.value)
    assert isinstance(caught.value.__cause__, ValueError)


@pytest.mark.parametrize("basis", ["", "x", "y", "XY", None, 1])
def test_invalid_basis_metadata(basis):
    with pytest.raises((ValueError, TypeError)):
        QuantumCircuitRequest("id", object(), basis)


@pytest.mark.parametrize("shots", [True, 0, -1, 1.5, "4"])
def test_shots_metadata_is_still_validated(shots):
    with pytest.raises(ValidationError):
        prepare_quantum_circuit_batch(
            circuits=[QuantumCircuitRequest("id", object(), "Z")], shots=shots,
        )


def test_request_ids_and_empty_batches():
    request = QuantumCircuitRequest("duplicate", object(), "Z")
    for circuits in ([], [request, request], "not requests", [object()]):
        with pytest.raises(ValidationError):
            prepare_quantum_circuit_batch(circuits=circuits)


@pytest.mark.parametrize("seed", range(12))
def test_linear_routing_preserves_full_operator_and_exported_edges(seed, compiled_exports):
    # Deliberately require routing, including nonadjacent input CZ/CX/SWAP.
    rng = np.random.default_rng(seed)
    circuit = QuantumCircuit(3)
    for layer in range(4):
        for q in range(3):
            circuit.ry(float(rng.uniform(-math.pi, math.pi)), q)
            circuit.rz(float(rng.uniform(-math.pi, math.pi)), q)
        first, second = rng.permutation(3)[:2].tolist()
        getattr(circuit, ("cz", "cx", "swap")[layer % 3])(first, second)
    circuit.cz(2, 0)
    before = circuit.copy()
    program = export_qasm3(circuit)
    compiled, = compiled_exports
    assert_same_operator(circuit, compiled)
    assert circuit == before
    assert set(compiled.count_ops()) <= {"rx", "rz", "cz"}
    edges = re.findall(r"cz q\[(\d+)\], q\[(\d+)\];", program)
    assert edges and set(edges) <= {("0", "1"), ("1", "2")}
    assert len(edges) == compiled.count_ops().get("cz", 0)
    assert "$" not in program


def test_routing_restores_state_before_terminal_measurements(compiled_exports):
    circuit = QuantumCircuit(3, 3)
    circuit.ry(0.4, 0)
    circuit.rx(-0.7, 2)
    circuit.cz(2, 0)
    circuit.cx(0, 2)
    circuit.barrier()
    circuit.measure([2, 0, 1], [0, 1, 2])
    export_qasm3(circuit)
    compiled, = compiled_exports
    assert measurement_mapping(compiled) == measurement_mapping(circuit)
    assert_same_operator(circuit.remove_final_measurements(inplace=False),
                         compiled.remove_final_measurements(inplace=False))


def test_topology_guard_rejects_an_illegal_compiler_output():
    from pivotq._internal.qpu_integration.qasm3_export import _enforce_cz_topology
    circuit = QuantumCircuit(3)
    circuit.cz(0, 2)
    with pytest.raises(ValueError, match="outside"):
        _enforce_cz_topology(circuit)
