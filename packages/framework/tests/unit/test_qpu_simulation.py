"""Exact circuit simulation must preserve the public QPU probability contract."""

from types import SimpleNamespace
import json

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.circuit import Parameter

from pivotq._internal.errors import ValidationError
from pivotq._internal.executors import LocalExecutor
from pivotq._internal.framework import (
    ComponentRegistry, ComponentSpec, ExecutionMode, FusionFramework, ResourceRequest,
)
from pivotq._internal.qpu_integration import QPUCircuitService, QuantumCircuitRequest
from pivotq._internal.qpu_integration.component import register_qpu_client
from pivotq._internal.qpu_integration.simulation import StatevectorQPUComponent, qpu_is_configured


@pytest.fixture
def simulation_service():
    registry = ComponentRegistry()
    framework = FusionFramework(LocalExecutor(registry))
    framework.register(
        ComponentSpec(
            component_id="test-exact-qpu",
            execution=ExecutionMode.ACTOR,
            resources=ResourceRequest(num_cpus=1),
            allowed_methods=("run_quantum_circuits",),
            stateful=True,
        ),
        StatevectorQPUComponent,
    )
    context = SimpleNamespace(run_id="exact-contract", raise_if_stop_requested=lambda: None)
    try:
        yield QPUCircuitService(framework, context, component_id="test-exact-qpu")
    finally:
        framework.close()
        registry.close()


def test_all_eight_basis_states_use_direct_logical_bit_order(simulation_service):
    requests = []
    states = [f"{index:03b}" for index in range(8)]
    for state in states:
        circuit = QuantumCircuit(3)
        for qubit, bit in enumerate(state):
            if bit == "1":
                circuit.x(qubit)
        requests.append(QuantumCircuitRequest(f"basis-{state}", circuit, "Z"))

    results = simulation_service.run_quantum_circuits(step=0, circuits=requests, shots=13)

    assert len(results) == 8
    for state, request, result in zip(states, requests, results):
        assert result["circuit_id"] == request.circuit_id
        assert result["measurement_basis"] == "Z"
        assert result["measurement_qubits"] == [0, 1, 2]
        assert result["shots"] == 13
        assert result["probabilities"] == {
            key: float(key == state) for key in states
        }


def test_basis_metadata_does_not_apply_another_rotation(simulation_service):
    # The application has already rotated X/Y measurement circuits into Z.
    # For this post-rotation |000> state a second H would incorrectly make
    # the distribution uniform; metadata must never change the probabilities.
    circuit = QuantumCircuit(3)
    before = circuit.copy()
    requests = [QuantumCircuitRequest(f"basis-{basis}", circuit, basis) for basis in "XYZ"]

    results = simulation_service.run_quantum_circuits(step=0, circuits=requests, shots=3000)

    assert [result["measurement_basis"] for result in results] == list("XYZ")
    assert all(result["probabilities"]["000"] == 1.0 for result in results)
    assert circuit == before


def test_probabilities_are_exact_and_independent_of_shots(simulation_service):
    circuit = QuantumCircuit(3)
    circuit.ry(0.731, 0)
    circuit.ry(0.413, 1)
    circuit.cx(0, 2)
    request = QuantumCircuitRequest("entangled.X", circuit, "X")

    one = simulation_service.run_quantum_circuits(step=0, circuits=[request], shots=1)[0]
    many = simulation_service.run_quantum_circuits(step=1, circuits=[request], shots=4096)[0]

    assert one["probabilities"] == many["probabilities"]
    assert any(0 < value < 1 for value in one["probabilities"].values())
    np.testing.assert_allclose(sum(one["probabilities"].values()), 1, atol=1e-14, rtol=0)
    assert StatevectorQPUComponent().describe()["real_hardware"] is False


@pytest.mark.parametrize("kind", ["two_qubits", "unbound", "measurement"])
def test_simulation_rejects_circuits_outside_unitary_three_qubit_contract(kind):
    circuit = QuantumCircuit(2 if kind == "two_qubits" else 3)
    if kind == "unbound":
        circuit.ry(Parameter("angle"), 0)
    if kind == "measurement":
        circuit.measure_all()
    request = QuantumCircuitRequest("invalid.Z", circuit, "Z")

    with pytest.raises(ValidationError):
        StatevectorQPUComponent().run_quantum_circuits(
            [request], shots=3000, request_id="invalid-contract",
        )


def test_disabled_simulation_preserves_zero_cpu_qpu_registration():
    registry = ComponentRegistry()
    framework = FusionFramework(LocalExecutor(registry), simulation=False)
    try:
        registration = register_qpu_client(framework, num_cpus=0)
        assert registration.spec.resources.num_cpus == 0
        assert framework.describe("qpu-circuits").resources.num_cpus == 0
        assert framework.resolve_execution("qpu-circuits").simulated is False
    finally:
        framework.close()
        registry.close()


@pytest.fixture
def no_qpu_configuration(monkeypatch):
    for name in ("QPU_DEVICE_CONFIG_FILE", "QPU_DEVICE_ID", "QPU_DEVICE_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("url, expected", [
    (None, False), ("", False), ("   ", False), ("http://device.invalid", True),
])
def test_global_qpu_configuration_is_detected_without_network(no_qpu_configuration, monkeypatch, url, expected):
    if url is not None:
        monkeypatch.setenv("QPU_DEVICE_URL", url)
    assert qpu_is_configured() is expected


@pytest.mark.parametrize("contents, device_id, expected", [
    ({"device-a": {"url": "http://device-a.invalid"}}, "device-a", True),
    ({"device-a": {"url": ""}}, "device-a", False),
    ({"device-a": {"url": "  "}}, "device-a", False),
    ({"device-a": {"url": None}}, "device-a", False),
    ({"device-a": {"url": "http://device-a.invalid"}}, "device-b", False),
])
def test_targeted_configuration_takes_precedence_over_global_endpoint(
    no_qpu_configuration, monkeypatch, tmp_path, contents, device_id, expected,
):
    path = tmp_path / "qpu.json"
    path.write_text(json.dumps(contents))
    monkeypatch.setenv("QPU_DEVICE_CONFIG_FILE", str(path))
    monkeypatch.setenv("QPU_DEVICE_ID", device_id)
    monkeypatch.setenv("QPU_DEVICE_URL", "http://unrelated-device.invalid")
    assert qpu_is_configured() is expected


def test_missing_qpu_configuration_file_means_unconfigured(no_qpu_configuration, monkeypatch, tmp_path):
    monkeypatch.setenv("QPU_DEVICE_CONFIG_FILE", str(tmp_path / "absent.json"))
    assert qpu_is_configured() is False


@pytest.mark.parametrize("contents, expected_error", [
    ("{broken", json.JSONDecodeError), ("[]", TypeError),
    ('{"device-a": {"url": 123}}', TypeError),
])
def test_invalid_qpu_configuration_is_not_treated_as_missing_hardware(
    no_qpu_configuration, monkeypatch, tmp_path, contents, expected_error,
):
    path = tmp_path / "qpu.json"
    path.write_text(contents)
    monkeypatch.setenv("QPU_DEVICE_CONFIG_FILE", str(path))
    monkeypatch.setenv("QPU_DEVICE_ID", "device-a")
    with pytest.raises(expected_error):
        qpu_is_configured()
