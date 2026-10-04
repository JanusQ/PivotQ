"""Public QPU service and Job configuration without Ray startup or hardware."""

import shlex
from types import SimpleNamespace
from unittest.mock import patch
import time

import pytest
from qiskit import QuantumCircuit

from pivotq._internal.errors import ExecutionError, ValidationError
from pivotq._internal.executors.local import LocalExecutor
from pivotq._internal.framework import ComponentRegistry, FusionFramework
from pivotq._internal.qpu_integration import QuantumCircuitRequest, QPUCircuitService
from pivotq._internal.qpu_integration.component import DEFAULT_QPU_COMPONENT_ID, register_qpu_client
from pivotq._internal.qpu_integration.device_adapter import DeviceExecutionUnknownError
from pivotq._internal.qpu_integration.registration import register_components
from pivotq._internal.qpu_integration import submit_job
from pivotq._internal.qpu_integration.submit_job import build_job_spec
from tests.fixtures.qpu_device_fake import RecordingDeviceAdapter


@pytest.fixture
def setup_service():
    registry = ComponentRegistry()
    framework = FusionFramework(LocalExecutor(registry, max_workers=2))
    adapter = RecordingDeviceAdapter()
    register_qpu_client(framework, adapter_factory=lambda: adapter)
    context = SimpleNamespace(run_id="client-test", raise_if_stop_requested=lambda: None)
    service = QPUCircuitService(framework, context)
    yield service, adapter, framework
    framework.close()
    registry.close()


def requests():
    return [QuantumCircuitRequest(f"id-{basis}", QuantumCircuit(3), basis) for basis in "XYZ"]


def test_service_preserves_api_ids_shots_and_all_eight_probabilities_xyz(setup_service):
    service, adapter, framework = setup_service
    for step, shots in [(0, 3000), (1, 64)]:
        results = service.run_quantum_circuits(step=step, circuits=requests(), shots=shots)
        assert [item["measurement_basis"] for item in results] == list("XYZ")
        expected = {"000": 0.0, "001": 0.0, "010": 0.0, "011": 0.0,
                    "100": 1.0, "101": 0.0, "110": 0.0, "111": 0.0}
        assert all(item["probabilities"] == expected for item in results)
        programs, sent_shots, request_id = adapter.exchanges[-1]
        assert sent_shots == shots
        assert request_id == f"client-test.qpu.{step:06d}"
        assert all(program.content.startswith("OPENQASM 3.0;") for program in programs)
    assert len(adapter.exchanges) == 2
    assert not framework._executor._entries


def test_service_failure_and_no_automatic_retry(setup_service):
    service, adapter, _ = setup_service
    adapter.failure = DeviceExecutionUnknownError("fixture response lost")
    with pytest.raises(ExecutionError):
        service.run_quantum_circuits(step=0, circuits=requests())
    assert len(adapter.exchanges) == 1


def test_service_wait_reminder_is_payload_free(setup_service, caplog):
    service, adapter, _ = setup_service
    original = adapter._exchange
    def slow(*args, **kwargs):
        time.sleep(0.06)
        return original(*args, **kwargs)
    adapter._exchange = slow
    with patch("pivotq._internal.qpu_integration.service.QPU_WAIT_WARNING_SECONDS", 0.01), \
         patch("pivotq._internal.qpu_integration.service.QPU_WAIT_WARNING_INTERVAL_SECONDS", 0.01):
        service.run_quantum_circuits(step=0, circuits=requests())
    assert "当前不会自动取消或重试" in caplog.text
    assert "OPENQASM" not in caplog.text


def test_service_stops_before_submission_and_validates_metadata(setup_service):
    service, adapter, framework = setup_service
    for step in (True, -1, 1_000_000):
        with pytest.raises((TypeError, ValueError)):
            service.run_quantum_circuits(step=step, circuits=requests())
    with pytest.raises(ValidationError):
        service.run_quantum_circuits(step=0, circuits=requests(), shots=0)
    with pytest.raises(ValueError):
        QPUCircuitService(framework, SimpleNamespace(run_id="bad/id"))
    def stop():
        raise RuntimeError("stop requested")
    stopped = QPUCircuitService(framework, SimpleNamespace(run_id="stop", raise_if_stop_requested=stop))
    with pytest.raises(RuntimeError, match="stop requested"):
        stopped.run_quantum_circuits(step=0, circuits=requests())
    assert not adapter.exchanges


def test_registration_is_lazy_and_requires_only_cpu():
    registry = ComponentRegistry()
    framework = FusionFramework(LocalExecutor(registry))
    try:
        register_components(framework)
        spec = framework.describe(DEFAULT_QPU_COMPONENT_ID)
        assert spec.resources.custom_resources_dict() == {}
        assert spec.resources.num_cpus == 1
        assert spec.resources.num_gpus == 0
        with pytest.raises(ValidationError, match="Set QPU_DEVICE_URL"):
            QPUCircuitService(framework, SimpleNamespace(
                run_id="not-configured", raise_if_stop_requested=lambda: None,
            )).run_quantum_circuits(step=0, circuits=requests())
    finally:
        framework.close()
        registry.close()


def test_job_spec_requires_only_cpu_and_keeps_trace_options():
    spec = build_job_spec(
        submission_id="client-001", working_dir=".", output_dir="/persistent/output",
        trace_event_max_records=512,
    )
    args = shlex.split(spec.entrypoint)
    assert args[args.index("--trace-event-max-records") + 1] == "512"
    assert dict(spec.runtime_environment.env_vars) == {"PYTHONPATH": "src:."}
    assert dict(spec.driver_resources.custom_resources) == {}
    assert spec.driver_resources.num_cpus == 0.2
    assert spec.metadata_dict()["qpu_contract"] == "qasm3-full-3q-v1"


@pytest.mark.parametrize("replacement", [
    {"submission_id": "x" * 116}, {"output_dir": "relative"},
    {"runner_target": "invalid"}, {"trace_max_records": 0},
    {"trace_event_max_records": 0}, {"trace_event_max_records": True},
])
def test_job_spec_invalid_metadata(replacement):
    args = {"submission_id": "client-001", "working_dir": ".", "output_dir": "/persistent/output"}
    with pytest.raises((TypeError, ValueError)):
        build_job_spec(**(args | replacement))


def test_removed_placement_option_fails_before_client_creation():
    with patch.object(submit_job, "RayJobClient", side_effect=AssertionError("must not connect")):
        with pytest.raises(SystemExit) as stopped:
            submit_job.main([
                "--submission-id", "client-001", "--output-dir", "/persistent/output",
                "--server-resource", "obsolete",
            ])
    assert stopped.value.code == 2
