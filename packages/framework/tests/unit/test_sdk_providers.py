"""User providers run through the same circuit, result, and lifetime contracts."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest
from qiskit import QuantumCircuit

from pivotq import Runtime
from pivotq.errors import ExecutionError, ResultUnknownError, ValidationError
from pivotq.providers import BackendCapabilities, ProviderResult


SIMULATOR = BackendCapabilities(8, True, supports_seed=True)
DEVICE = BackendCapabilities(8, False)


def test_registration_and_backend_creation_never_construct_provider():
    calls = []

    class Provider:
        def __init__(self, *, settings):
            calls.append(("init", settings["state"]))
            self.state = settings["state"]
            settings["state"] = "111"

        def run(self, request):
            assert not request.circuit.num_clbits
            assert all(item.operation.name != "measure" for item in request.circuit.data)
            return ProviderResult(request.shots, "fixture", counts={self.state: request.shots})

        def close(self):
            calls.append(("close", self.state))

    runtime = Runtime()
    runtime.register_quantum_backend("custom", Provider, capabilities=SIMULATOR)
    assert runtime._framework is None
    settings = {"state": "001"}
    backend = runtime.quantum_backend("custom", settings=settings)
    assert backend.describe() == SIMULATOR
    assert not calls
    settings["state"] = "010"
    with runtime:
        for _ in range(2):
            result = runtime.get(backend.submit(QuantumCircuit(3), shots=3))
            assert result.counts == {"001": 3}
    # Each TASK gets its own configuration copy and is closed after execution.
    assert calls == [("init", "001"), ("close", "001"), ("init", "001"), ("close", "001")]


def test_full_logical_distribution_is_mapped_to_partial_permuted_measurements():
    original = QuantumCircuit(3, 3)
    original.x(0)
    original.measure(0, 2)
    original.measure(2, 0)
    saved = original.copy()

    class Provider:
        def run(self, request):
            assert request.circuit.num_qubits == 3 and request.circuit.num_clbits == 0
            request.circuit.measure_all()  # Providers may adapt their private circuit.
            return ProviderResult(request.shots, "fixture", counts={"001": 30, "011": 70})

        def close(self):
            pass

    with Runtime() as runtime:
        runtime.register_quantum_backend("partial", Provider, capabilities=SIMULATOR)
        result = runtime.get(runtime.quantum_backend("partial").submit(original, shots=100))
    assert result.counts == {"100": 100}
    assert result.probabilities == {"100": 1.0}
    assert result.bit_order == "c[n-1]...c0"
    assert result.backend == "partial" and result.is_simulated
    assert original == saved


def test_probability_only_results_never_create_counts():
    class Provider:
        def run(self, request):
            return ProviderResult(request.shots, "calibrated_probabilities", probabilities={"000": 0.25, "100": 0.75})

        def close(self):
            pass

    with Runtime() as runtime:
        runtime.register_quantum_backend("probabilities", Provider, capabilities=DEVICE)
        result = runtime.get(runtime.quantum_backend("probabilities").submit(QuantumCircuit(3)))
    assert result.counts is None
    assert result.probabilities == {"000": 0.25, "100": 0.75}
    assert not result.is_simulated


def test_actor_provider_is_reused_serially_and_closed_once():
    events = []
    active = 0
    max_active = 0
    lock = threading.Lock()

    class Provider:
        def __init__(self):
            events.append("init")

        def run(self, request):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(active, max_active)
            try:
                time.sleep(0.01)
                events.append("run")
                return ProviderResult(request.shots, "fixture", counts={"000": request.shots})
            finally:
                with lock:
                    active -= 1

        def close(self):
            events.append("close")

    runtime = Runtime(max_workers=4)
    with runtime:
        runtime.register_quantum_backend("serial", Provider, capabilities=DEVICE)
        backend = runtime.quantum_backend("serial")
        refs = [backend.submit(QuantumCircuit(3)) for _ in range(6)]
        assert all(runtime.get(ref).counts == {"000": 1024} for ref in refs)
    runtime.close()
    assert max_active == 1
    assert events == ["init"] + ["run"] * 6 + ["close"]


@pytest.mark.parametrize("change", [
    {"shots": 99}, {"shots": True}, {"source": ""}, {"counts": {}},
    {"counts": {"00": 100}}, {"counts": {"00x": 100}}, {"counts": {"000": 99}},
    {"counts": {"000": -1, "001": 101}}, {"counts": {"000": 100.0}}, {"counts": {"000": True}},
    {"counts": None}, {"counts": None, "probabilities": {"000": 0.5}},
    {"counts": None, "probabilities": {"000": float("nan")}},
    {"counts": None, "probabilities": {"000": 1.1, "001": -0.1}},
    {"counts": None, "probabilities": {"000": True}},
    {"probabilities": {"001": 1.0}}, {"metadata": {"source": "forged"}},
    {"metadata": {"is_simulated": False}}, {"metadata": {1: "bad-key"}},
])
@pytest.mark.parametrize("simulated", [True, False])
def test_invalid_provider_results_fail_with_correct_execution_uncertainty(change, simulated):
    calls = []

    class Provider:
        def run(self, request):
            calls.append(request.request_id)
            result = ProviderResult(100, "fixture", counts={"000": 100}, metadata={"backend_job_id": "job-1"})
            return replace(result, **change)

        def close(self):
            pass

    with Runtime() as runtime:
        runtime.register_quantum_backend("invalid", Provider, capabilities=SIMULATOR if simulated else DEVICE)
        backend = runtime.quantum_backend("invalid")
        ref = backend.submit(QuantumCircuit(3), shots=100)
        with pytest.raises(ExecutionError if simulated else ResultUnknownError) as caught:
            runtime.get(ref)
        assert caught.value.framework_job_id == calls[0]
        if "metadata" not in change:
            assert caught.value.backend_job_id == "job-1"
    assert len(calls) == 1


def test_invalid_result_metadata_fails_before_leaving_executor():
    class Provider:
        def run(self, request):
            return ProviderResult(request.shots, "fixture", counts={"000": request.shots}, metadata={"lock": threading.Lock()})

        def close(self):
            pass

    with Runtime() as runtime:
        runtime.register_quantum_backend("unserializable", Provider, capabilities=DEVICE)
        result = runtime.quantum_backend("unserializable").submit(QuantumCircuit(3))
        with pytest.raises(ResultUnknownError, match="standard-pickle"):
            runtime.get(result)


@pytest.mark.parametrize("structured", [True, False])
def test_physical_failure_retains_request_identity_through_downstream(structured):
    calls = []

    class Provider:
        def run(self, request):
            calls.append(request.request_id)
            if structured:
                raise ResultUnknownError("response lost", backend_job_id="job-7", device_id="lab")
            raise OSError("vendor message may include secrets")

        def close(self):
            pass

    with Runtime() as runtime:
        runtime.register_quantum_backend("uncertain", Provider, capabilities=DEVICE)
        first = runtime.quantum_backend("uncertain").submit(QuantumCircuit(3))
        final = runtime.submit(lambda value: value.counts, first)
        with pytest.raises(ResultUnknownError) as caught:
            runtime.get(final)
        assert caught.value.framework_job_id == calls[0]
        if structured:
            assert caught.value.backend_job_id == "job-7" and caught.value.device_id == "lab"
        else:
            assert "secrets" not in str(caught.value)
    assert len(calls) == 1


def test_provider_known_validation_failure_is_not_reported_as_execution_unknown():
    class Provider:
        def run(self, request):
            raise ValidationError("gate compilation unsupported")

        def close(self):
            pass

    with Runtime() as runtime:
        runtime.register_quantum_backend("compiler", Provider, capabilities=DEVICE)
        with pytest.raises(ValidationError, match="compilation") as caught:
            runtime.get(runtime.quantum_backend("compiler").submit(QuantumCircuit(3)))
        assert caught.value.framework_job_id.startswith("sdk-")


def test_duplicate_reserved_names_configuration_and_runtime_ownership():
    class Provider:
        def __init__(self, *, endpoint):
            pass

    with Runtime() as left, Runtime() as right:
        left.register_quantum_backend("custom", Provider, capabilities=DEVICE)
        with pytest.raises((ValueError, ValidationError)):
            left.register_quantum_backend("custom", Provider, capabilities=DEVICE)
        with pytest.raises((ValueError, ValidationError)):
            left.register_quantum_backend("simulator", Provider, capabilities=DEVICE)
        with pytest.raises(ValueError, match="not registered"):
            right.quantum_backend("custom", endpoint="offline")
        with pytest.raises(TypeError, match="configuration"):
            left.quantum_backend("custom", typo="offline")
        with pytest.raises(TypeError, match="serializable"):
            left.quantum_backend("custom", endpoint=threading.Lock())


@pytest.mark.parametrize("capabilities,options", [
    (DEVICE, {"execution": "task"}), (DEVICE, {"num_cpus": 1}),
    (SIMULATOR, {"num_cpus": 0}), (SIMULATOR, {"num_cpus": float("nan")}),
    (SIMULATOR, {"execution": "gpu"}), (SIMULATOR, {"num_cpus": True}),
])
def test_invalid_provider_execution_options(capabilities, options):
    with Runtime() as runtime:
        with pytest.raises((ValueError, TypeError)):
            runtime.register_quantum_backend("custom", lambda: None, capabilities=capabilities, **options)


def test_custom_provider_example_is_executed_from_same_source(tmp_path):
    framework_root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [str(framework_root), environment.get("PYTHONPATH")]))
    completed = subprocess.run(
        [sys.executable, str(framework_root / "examples/custom_backend.py")],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["backend"] == "custom-simulator" and result["is_simulated"]
    assert set(result["counts"]) == {"10", "11"}
    assert sum(result["counts"].values()) == result["shots"] == 1024
    assert result["bit_order"] == "c[n-1]...c0"

