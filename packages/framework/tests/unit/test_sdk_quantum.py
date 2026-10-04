"""Public quantum execution: measured semantics and offline device exchange."""

import json
import pickle

import httpx
import pytest
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.circuit import Parameter

from pivotq import Runtime
from pivotq.quantum import QuantumResult, _LabSettings, _prepare
from pivotq._internal.errors import ResultUnknownError, RetryAdvice
from pivotq._internal.qpu_integration.device_adapter import QPUDeviceAdapter


@pytest.fixture(autouse=True)
def isolated_device_config(monkeypatch):
    for name in (
        "QPU_DEVICE_CONFIG_FILE", "QPU_DEVICE_ID", "QPU_DEVICE_URL", "QPU_DEVICE_API_KEY",
        "QPU_PROBABILITY_SOURCE", "QPU_JOB_JOURNAL_DIR", "QPU_RESULT_ARCHIVE_DIR",
    ):
        monkeypatch.delenv(name, raising=False)


def test_five_qubit_ghz_samples_and_seed_preserve_input():
    circuit = QuantumCircuit(5)
    circuit.h(0)
    for target in range(1, 5):
        circuit.cx(0, target)
    circuit.measure_all()
    original = circuit.copy()
    with Runtime() as runtime:
        backend = runtime.quantum_backend("simulator")
        first = runtime.get(backend.submit(circuit, shots=1024, seed=11))
        second = runtime.get(backend.submit(circuit, shots=1024, seed=11))
    assert isinstance(first, QuantumResult)
    assert first.counts == second.counts
    assert set(first.counts) == {"00000", "11111"}
    assert sum(first.counts.values()) == 1024
    assert first.probabilities == {key: count / 1024 for key, count in first.counts.items()}
    assert abs(first.probabilities["11111"] - 0.5) < 0.06
    assert first.bit_order == "c[n-1]...c0"
    assert first.backend == "simulator" and first.is_simulated
    assert pickle.loads(pickle.dumps(first)) == first
    assert circuit == original


def test_no_measurements_uses_qubit_order_not_unused_classical_register():
    circuit = QuantumCircuit(3, 1)
    circuit.x(0)
    with Runtime() as runtime:
        result = runtime.get(runtime.quantum_backend("simulator").submit(circuit, shots=7))
    assert result.counts == {"001": 7}
    assert result.bit_order == "q[n-1]...q0"


def test_partial_reordered_measurement_flattens_registers_and_sums_marginals():
    circuit = QuantumCircuit(QuantumRegister(3), ClassicalRegister(2, "a"), ClassicalRegister(1, "b"))
    circuit.x(0)
    circuit.h(1)  # Unmeasured randomness is marginalized.
    circuit.measure(0, 2)
    circuit.measure(2, 0)
    with Runtime() as runtime:
        result = runtime.get(runtime.quantum_backend("simulator").submit(circuit, shots=99, seed=5))
    assert result.counts == {"100": 99}


def test_circuit_reference_connects_classical_quantum_classical_tasks():
    def circuit_factory():
        circuit = QuantumCircuit(4)
        circuit.x(3)
        return circuit

    with Runtime() as runtime:
        circuit = runtime.submit(circuit_factory)
        measured = runtime.quantum_backend("simulator").submit(circuit, shots=17)
        answer = runtime.submit(lambda item: item.probabilities["1000"], measured)
        assert runtime.get(answer) == 1
        runtime.release(answer, measured, circuit)


@pytest.mark.parametrize("case", ["unbound", "mid_measure", "reset", "initialize", "duplicate_qubit", "duplicate_classical", "dynamic", "nested_reset"])
def test_unsupported_circuits_rejected_before_execution(case):
    circuit = QuantumCircuit(3, 3)
    if case == "unbound":
        circuit.rx(Parameter("theta"), 0)
    elif case == "mid_measure":
        circuit.measure(0, 0)
        circuit.x(1)
    elif case == "reset":
        circuit.reset(0)
    elif case == "initialize":
        circuit.initialize([1, 0], 0)
    elif case == "duplicate_qubit":
        circuit.measure(0, 0)
        circuit.measure(0, 1)
    elif case == "duplicate_classical":
        circuit.measure(0, 0)
        circuit.measure(1, 0)
    elif case == "dynamic":
        with circuit.if_test((circuit.clbits[0], 0)):
            circuit.x(0)
    elif case == "nested_reset":
        inner = QuantumCircuit(1)
        inner.reset(0)
        circuit.append(inner.to_instruction(), [0])
    with pytest.raises(ValueError):
        _prepare(circuit, max_qubits=20)


def test_qubit_limits_and_bound_composite_unitary():
    with pytest.raises(ValueError, match="between 1 and 20"):
        _prepare(QuantumCircuit(21), max_qubits=20)
    with pytest.raises(ValueError, match="exactly 3"):
        _prepare(QuantumCircuit(2), max_qubits=3, exact_qubits=3)
    inner = QuantumCircuit(1)
    theta = Parameter("theta")
    inner.ry(theta, 0)
    circuit = QuantumCircuit(1)
    circuit.append(inner.assign_parameters({theta: 0}).to_instruction(), [0])
    with Runtime() as runtime:
        result = runtime.get(runtime.quantum_backend("simulator", max_qubits=1).submit(circuit))
    assert result.probabilities == {"0": 1}


@pytest.mark.parametrize("shots", [True, 0, -1, 1.5])
def test_invalid_shots_rejected_at_submit(shots):
    with Runtime() as runtime:
        with pytest.raises(ValueError, match="shots"):
            runtime.quantum_backend("simulator").submit(QuantumCircuit(1), shots=shots)


@pytest.mark.parametrize("config", [{"max_qubits": False}, {"max_qubits": 0}, {"device": "gpu"}])
def test_invalid_simulator_configuration(config):
    with Runtime() as runtime:
        with pytest.raises((ValueError, TypeError)):
            runtime.quantum_backend("simulator", **config)


@pytest.fixture
def offline_device(monkeypatch):
    requests = []
    state = {"failure": None, "reported_shots": 128}
    real_client = httpx.Client

    def handler(request):
        requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "backend": "circuit"})
        assert request.method == "POST" and request.url.path == "/v1/jobs"
        if state["failure"] == "lost_response":
            raise httpx.ReadError("offline test response lost", request=request)
        probabilities = [0, 0, 0, 0, 0.75, 0, 0, 0.25]  # device order q0,q1,q2
        return httpx.Response(200, json={
            "job_id": "offline-job", "status": "succeeded", "backend": "circuit",
            "parameters": {"reps": state["reported_shots"], "measure_base": "Z"},
            "files": [{"index": 0, "name": "circuit-000000.qasm"}],
            "result": {
                "columns": ["circuit"] + [f"expr_prob_P{i:03b}" for i in range(8)],
                "data": [[0] + probabilities],
            },
        })

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    return requests, state


def test_lab_qpu_converts_device_order_and_never_fabricates_counts(offline_device):
    requests, _ = offline_device
    circuit = QuantumCircuit(3)
    circuit.x(0)
    with Runtime() as runtime:
        backend = runtime.quantum_backend("lab-qpu", server_url="http://offline.test")
        assert not requests  # Creating a backend never opens a device connection.
        result = runtime.get(backend.submit(circuit, shots=128))
    assert result.probabilities == {"001": 0.75, "111": 0.25}
    assert result.counts is None and result.shots == 128
    assert result.backend == "lab-qpu" and not result.is_simulated
    assert result.metadata["source"] == "device_expr_prob"
    assert len(requests) == 2
    payload = requests[-1].content.decode()
    assert "OPENQASM 3.0" in payload and "rx(" in payload
    assert "measure " not in payload


def test_lab_partial_measurements_and_configuration_are_frozen(offline_device, monkeypatch, tmp_path):
    requests, _ = offline_device
    monkeypatch.setenv("QPU_DEVICE_URL", "http://original.test")
    monkeypatch.setenv("QPU_DEVICE_API_KEY", "original-key")
    circuit = QuantumCircuit(3, 2)
    circuit.measure(0, 1)
    with Runtime() as runtime:
        backend = runtime.quantum_backend("lab-qpu")
        monkeypatch.setenv("QPU_DEVICE_URL", "http://changed.test")
        monkeypatch.setenv("QPU_DEVICE_API_KEY", "changed-key")
        monkeypatch.setenv("QPU_PROBABILITY_SOURCE", "ideal_prob")
        monkeypatch.setenv("QPU_RESULT_ARCHIVE_DIR", str(tmp_path / "worker-archive"))
        result = runtime.get(backend.submit(circuit, shots=128))
    assert result.probabilities == {"10": 1.0}
    assert result.bit_order == "c[n-1]...c0"
    assert all(request.url.host == "original.test" for request in requests)
    assert requests[-1].headers["Authorization"] == "Bearer original-key"
    assert not (tmp_path / "worker-archive").exists()


def test_device_file_configuration_snapshot_preserves_binding(monkeypatch, tmp_path):
    path = tmp_path / "devices.json"
    path.write_text(json.dumps({"lab": {
        "url": "http://offline.test", "api_key": "private", "timeout_seconds": 120,
        "custom_resources": {"qpu_device_lab": 1},
    }}))
    monkeypatch.setenv("QPU_DEVICE_CONFIG_FILE", str(path))
    monkeypatch.setenv("QPU_DEVICE_ID", "lab")
    config = _LabSettings.resolve({})
    path.unlink()
    assert config.server_url == "http://offline.test" and config.timeout_seconds == 120
    assert config.custom_resources == (("qpu_device_lab", 1.0),)
    assert "private" not in repr(config)
    assert pickle.loads(pickle.dumps(config)) == config


@pytest.mark.parametrize("failure", ["lost_response", "wrong_shots"])
def test_unknown_execution_has_no_automatic_retry_or_simulator_fallback(offline_device, failure):
    requests, state = offline_device
    if failure == "wrong_shots":
        state["reported_shots"] = 10
    else:
        state["failure"] = failure
    downstream_calls = []

    def update(value):
        downstream_calls.append(value)
        return value

    with Runtime() as runtime:
        backend = runtime.quantum_backend("lab-qpu", server_url="http://offline.test")
        ref = backend.submit(QuantumCircuit(3), shots=128)
        updated = runtime.submit(update, ref)
        final = runtime.submit(update, updated)
        with pytest.raises(ResultUnknownError) as error:
            runtime.get(final)
        assert error.value.retry_advice is RetryAdvice.RECONCILE_FIRST
        assert error.value.framework_job_id.startswith("sdk-")
        assert error.value.framework_job_id in str(error.value)
        if failure == "wrong_shots":
            assert "offline-job" in str(error.value)
        with pytest.raises(ResultUnknownError) as original:
            runtime.get(ref)
        assert original.value.to_record(include_message=True) == error.value.to_record(include_message=True)
        runtime.release(final, updated, ref)
    assert not downstream_calls
    assert sum(request.method == "POST" for request in requests) == 1


def test_ray_dependency_failure_keeps_unknown_execution_identity_across_hops():
    from pivotq._internal.errors import ExecutionError
    from pivotq._internal.executors.ray import _dependency_failure
    from pivotq._internal.framework import InvocationResult, InvocationSpec, InvocationStatus

    error = ResultUnknownError(
        "response lost; reconcile QPU job", framework_job_id="original-request",
        backend_job_id="device-job", device_id="lab",
    )
    original = InvocationResult(
        "quantum", "backend", InvocationStatus.FAILED, error=error,
    )
    intermediate = _dependency_failure(InvocationSpec("updated", "cpu", "run"), (original,))
    # Ray transports the intermediate failure, then skips the next consumer.
    final = _dependency_failure(
        InvocationSpec("final", "cpu", "run"), (pickle.loads(pickle.dumps(intermediate)),),
    )
    assert final.invocation_id == "final"
    assert isinstance(final.error, ResultUnknownError)
    assert final.error.to_record(include_message=True) == error.to_record(include_message=True)
    ordinary = InvocationResult("plain", "cpu", InvocationStatus.FAILED, error=ExecutionError("ordinary"))
    ordinary_final = _dependency_failure(InvocationSpec("final", "cpu", "run"), (ordinary,))
    assert type(ordinary_final.error) is ExecutionError
    assert "dependency" in str(ordinary_final.error)
    assert ordinary_final.error.framework_job_id == "final"


def test_bad_lab_circuit_never_touches_device_and_seed_is_rejected(offline_device):
    requests, _ = offline_device
    with Runtime() as runtime:
        backend = runtime.quantum_backend("lab-qpu", server_url="http://offline.test")
        with pytest.raises(ValueError, match="seed"):
            backend.submit(QuantumCircuit(3), seed=1)
        ref = backend.submit(QuantumCircuit(2))
        with pytest.raises(Exception, match="exactly 3"):
            runtime.get(ref)
    assert not requests


def test_lab_compilation_error_is_known_not_submitted(offline_device):
    from qiskit.circuit import Gate
    from pivotq.errors import ValidationError

    requests, _ = offline_device
    circuit = QuantumCircuit(3)
    circuit.append(Gate("unknown_vendor_gate", 1, []), [0])
    with Runtime() as runtime:
        ref = runtime.quantum_backend("lab-qpu", server_url="http://offline.test").submit(circuit)
        with pytest.raises(ValidationError, match="export failed"):
            runtime.get(ref)
    assert not requests


def test_legacy_adapter_still_reads_environment_and_explicit_snapshot_does_not(monkeypatch, tmp_path):
    archive = tmp_path / "legacy-archive"
    monkeypatch.setenv("QPU_RESULT_ARCHIVE_DIR", str(archive))
    monkeypatch.setenv("QPU_PROBABILITY_SOURCE", "ideal_prob")
    legacy = QPUDeviceAdapter()
    assert legacy._archive_dir == archive and legacy._probability_source == "ideal_prob"
    frozen = QPUDeviceAdapter(use_environment=False)
    assert frozen._archive_dir is None and frozen._probability_source == "expr_prob"
