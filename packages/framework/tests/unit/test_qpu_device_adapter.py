"""Completeness, eight-state results, bit-order and client-lifecycle contracts."""

from dataclasses import replace
import pickle
from threading import Event, Thread

import pytest
from qiskit import QuantumCircuit

from pivotq._internal.qpu_integration import QuantumCircuitRequest
from pivotq._internal.qpu_integration.component import (
    QPUClientComponent, QPUClientFactory, build_qpu_client_spec,
)
from pivotq._internal.qpu_integration.device_adapter import (
    DeviceCircuitResult, DeviceExecutionUnknownError, DeviceProtocolNotConfiguredError,
    DeviceResultError, QPUDeviceAdapter, normalize_results,
)
from pivotq._internal.qpu_integration.qasm3_export import QASM3Circuit
from tests.fixtures.qpu_device_fake import RecordingDeviceAdapter


def programs():
    return [QASM3Circuit("id", "Y", "circuit-000000.qasm", "OPENQASM 3.0;")]


def complete(**changes):
    return replace(DeviceCircuitResult(
        "id", 100, (0, 1, 2), complete=True, counts={"100": 75, "001": 25, "000": 0},
    ), **changes)


def normalize(items):
    return normalize_results(items, circuits=programs(), shots=100)


def test_counts_expand_to_all_eight_states_with_logical_bit_order_and_basis():
    result, = normalize([complete()])
    assert result == {
        "circuit_id": "id", "shots": 100, "measurement_basis": "Y",
        "measurement_qubits": [0, 1, 2], "probabilities": {
            "000": 0.0, "001": 0.25, "010": 0.0, "011": 0.0,
            "100": 0.75, "101": 0.0, "110": 0.0, "111": 0.0,
        },
    }
    assert list(result["probabilities"]) == ["000", "001", "010", "011", "100", "101", "110", "111"]


def test_device_probabilities_expand_zeros_and_preserve_circuit_order():
    first = complete(counts=None, probabilities={"010": 1.0, "111": 0.0})
    second = replace(first, circuit_id="second", probabilities={"100": 1.0})
    requests = programs() + [QASM3Circuit("second", "X", "circuit-000001.qasm", "")]
    result = normalize_results([second, first], circuits=requests, shots=100)
    assert [item["circuit_id"] for item in result] == ["id", "second"]
    assert result[0]["probabilities"] == {
        "000": 0.0, "001": 0.0, "010": 1.0, "011": 0.0,
        "100": 0.0, "101": 0.0, "110": 0.0, "111": 0.0,
    }
    assert result[1]["measurement_basis"] == "X"


def test_unconfirmed_full_distribution_is_not_accepted():
    full = {f"{state:03b}": 0.125 for state in range(8)}
    with pytest.raises(DeviceResultError, match="completeness"):
        normalize([complete(complete=False, counts=None, probabilities=full)])


@pytest.mark.parametrize("changes", [
    {"complete": False}, {"complete": 1}, {"shots": 99}, {"shots": True},
    {"measurement_qubits": (0, 1)}, {"measurement_qubits": (0, 1, 2, 3)},
    {"measurement_qubits": (2, 1, 0)}, {"measurement_qubits": (False, 1, 2)},
    {"counts": {"0": 100}}, {"counts": {"0000": 100}}, {"counts": {"00x": 100}},
    {"counts": {"000": 99}}, {"counts": {"000": 100.0}},
    {"counts": {"000": -1, "001": 101}}, {"counts": {}},
    {"counts": None}, {"probabilities": {"000": 1.0}},
    {"counts": None, "probabilities": {"000": float("nan")}},
    {"counts": None, "probabilities": {"000": float("inf")}},
    {"counts": None, "probabilities": {"000": True}},
    {"counts": None, "probabilities": {"000": "1"}},
    {"counts": None, "probabilities": {"000": 0.5}},
    {"counts": None, "probabilities": {"000": 1.1, "001": -0.1}},
])
def test_rejects_unconfirmed_incomplete_or_inconsistent_results(changes):
    with pytest.raises(DeviceResultError):
        normalize([complete(**changes)])


@pytest.mark.parametrize("items", [[], [complete(circuit_id="foreign")], [complete(), complete()]])
def test_missing_foreign_duplicate_ids(items):
    with pytest.raises(DeviceResultError):
        normalize(items)


def test_default_adapter_never_claims_a_result():
    with pytest.raises(DeviceProtocolNotConfiguredError, match="device_adapter.py"):
        QPUDeviceAdapter().execute_batch(programs(), shots=100, request_id="run-1")


def test_unknown_execution_is_not_retried():
    adapter = RecordingDeviceAdapter()
    adapter.failure = DeviceExecutionUnknownError("fixture response lost")
    with pytest.raises(DeviceExecutionUnknownError):
        adapter.execute_batch(programs(), shots=100, request_id="run-1")
    assert len(adapter.exchanges) == 1


def test_factory_spec_and_cleanup_are_server_owned():
    factory = pickle.loads(pickle.dumps(QPUClientFactory(RecordingDeviceAdapter)))
    client = factory()
    spec = build_qpu_client_spec()
    assert spec.resources.custom_resources_dict() == {}
    assert spec.resources.num_cpus == 1
    assert spec.resources.num_gpus == 0
    assert spec.max_concurrency == 1
    assert client.describe()["deployment"] == "framework_server"
    request = QuantumCircuitRequest("id", QuantumCircuit(3), "Y")
    result = client.run_quantum_circuits([request], shots=100, request_id="run-1")
    assert result[0]["probabilities"] == {
        "000": 0.0, "001": 0.0, "010": 0.0, "011": 0.0,
        "100": 1.0, "101": 0.0, "110": 0.0, "111": 0.0,
    }
    client.close()
    client.close()
    assert client._adapter.close_count == 1
    with pytest.raises(RuntimeError, match="closed"):
        client.run_quantum_circuits([request], request_id="run-2")


def test_concurrent_direct_calls_do_not_build_an_unbounded_queue():
    entered, finish = Event(), Event()
    class Blocking(RecordingDeviceAdapter):
        def _exchange(self, *args, **kwargs):
            entered.set()
            assert finish.wait(5)
            return super()._exchange(*args, **kwargs)
    client = QPUClientComponent(adapter=Blocking())
    request = QuantumCircuitRequest("id", QuantumCircuit(3), "Z")
    failures = []
    def run():
        try:
            client.run_quantum_circuits([request], request_id="one")
        except Exception as error:
            failures.append(error)
    thread = Thread(target=run)
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(RuntimeError, match="busy"):
            client.run_quantum_circuits([request], request_id="two")
    finally:
        finish.set()
        thread.join(5)
        client.close()
    assert not thread.is_alive()
    assert not failures
