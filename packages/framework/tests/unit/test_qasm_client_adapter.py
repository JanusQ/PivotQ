"""Offline provider-boundary tests. No installed SDK or network is used."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from pivotq._internal.qpu_integration.device_adapter import (
    DeviceClientError,
    DeviceExecutionUnknownError,
    DeviceJobResponse,
    DeviceProtocolNotConfiguredError,
    QPUDeviceAdapter,
)
from pivotq._internal.qpu_integration.qasm3_export import QASM3Circuit


@pytest.fixture
def provider(monkeypatch):
    state = SimpleNamespace(
        events=[], paths=[], contents=[], parameters=None, connection=None,
        fail_at=None, job={"job_id": "test-job-17"},
        result={"status": "succeeded", "unknown_native_data": "do-not-log-result"},
        suppress=False,
    )
    monkeypatch.setenv("QPU_DEVICE_URL", "http://qpu.invalid:9000")
    monkeypatch.setenv("QPU_DEVICE_API_KEY", "do-not-log-key")

    class ExperimentClient:
        def __init__(self, url, *, api_key):
            state.connection = (url, api_key)
            state.events.append("construct")

        def __enter__(self):
            state.events.append("enter")
            if state.fail_at == "enter":
                raise RuntimeError("do-not-log-key")
            return self

        def submit(self, paths, *, parameters):
            state.events.append("submit")
            state.paths = [Path(path) for path in paths]
            state.contents = [path.read_text(encoding="utf-8") for path in state.paths]
            state.parameters = parameters
            if state.fail_at == "submit":
                raise TimeoutError("do-not-log-key do-not-log-program")
            return state.job

        def wait(self, job_id):
            state.events.append("wait")
            assert job_id == state.job["job_id"]
            assert all(path.is_file() for path in state.paths)
            if state.fail_at == "wait":
                raise TimeoutError("do-not-log-result do-not-log-key")
            return state.result

        def __exit__(self, *args):
            state.events.append("exit")
            assert all(path.is_file() for path in state.paths)
            if state.fail_at == "exit":
                raise RuntimeError("do-not-log-result do-not-log-key")
            return state.suppress

    monkeypatch.setitem(sys.modules, "qasm_client", SimpleNamespace(ExperimentClient=ExperimentClient))
    return state


@pytest.fixture
def circuits():
    return (
        QASM3Circuit("z-1", "Z", "circuit-000000.qasm", "OPENQASM 3.0;\n// 中文 UTF-8\n"),
        QASM3Circuit("x-2", "X", "circuit-000001.qasm", "OPENQASM 3.0;\nqubit[3] q;\n"),
    )


def exchange(adapter, circuits):
    return adapter._exchange(circuits, shots=3000, request_id="run.qpu.000001")


def assert_cleaned(provider):
    assert all(not path.exists() and not path.parent.exists() for path in provider.paths)


def test_upload_wait_preserves_files_and_native_context(provider, circuits, caplog):
    with caplog.at_level("INFO"):
        response = exchange(QPUDeviceAdapter(), circuits)
    assert provider.events == ["construct", "enter", "submit", "wait", "exit"]
    assert provider.connection == ("http://qpu.invalid:9000", "do-not-log-key")
    assert provider.parameters == {"reps": 3000}  # All optional experiment params omitted.
    assert [path.name for path in provider.paths] == [c.filename for c in circuits]
    assert provider.contents == [c.content for c in circuits]
    assert isinstance(response, DeviceJobResponse)
    assert response.job_id == "test-job-17"
    assert response.request_id == "run.qpu.000001"
    assert response.requested_shots == 3000
    assert response.circuits == circuits
    assert response.result is provider.result
    assert "test-job-17" in caplog.text
    for text in (caplog.text, repr(response)):
        assert "do-not-log" not in text
        assert "OPENQASM" not in text
    assert_cleaned(provider)


def test_result_decoder_is_explicitly_pending_after_one_exchange(provider, circuits):
    adapter = QPUDeviceAdapter()
    with pytest.raises(DeviceProtocolNotConfiguredError, match="_decode.*test-job-17"):
        adapter.execute_batch(circuits, shots=3000, request_id="run.qpu.000001")
    assert provider.events.count("submit") == provider.events.count("wait") == 1
    adapter.close()
    assert provider.events.count("exit") == 1
    assert_cleaned(provider)


def test_explicit_config_takes_precedence_over_environment(provider, circuits):
    exchange(QPUDeviceAdapter(server_url="http://other.invalid", api_key="explicit"), circuits)
    assert provider.connection == ("http://other.invalid", "explicit")


@pytest.mark.parametrize("variable", ["QPU_DEVICE_URL", "QPU_DEVICE_API_KEY"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_config_never_constructs_client(provider, circuits, monkeypatch, variable, value):
    if value is None:
        monkeypatch.delenv(variable)
    else:
        monkeypatch.setenv(variable, value)
    with pytest.raises(DeviceProtocolNotConfiguredError, match="device_adapter.py"):
        exchange(QPUDeviceAdapter(), circuits)
    assert provider.events == []


def test_missing_sdk_reports_provider_dependency(provider, circuits, monkeypatch):
    monkeypatch.setitem(sys.modules, "qasm_client", None)
    with pytest.raises(DeviceProtocolNotConfiguredError, match="provider's qasm_client"):
        exchange(QPUDeviceAdapter(), circuits)
    assert provider.events == []


@pytest.mark.parametrize("phase", ["enter", "submit", "wait", "exit"])
def test_sdk_failures_cleanup_without_retry_or_payload_leak(provider, circuits, phase):
    provider.fail_at = phase
    expected = DeviceExecutionUnknownError if phase in {"submit", "wait"} else DeviceClientError
    with pytest.raises(expected) as caught:
        exchange(QPUDeviceAdapter(), circuits)
    assert "do-not-log" not in str(caught.value)
    assert caught.value.__suppress_context__
    if phase in {"wait", "exit"}:
        assert "test-job-17" in str(caught.value)
    assert provider.events.count("submit") <= 1
    assert provider.events.count("wait") <= 1
    assert provider.events.count("exit") == (0 if phase == "enter" else 1)
    assert_cleaned(provider)


@pytest.mark.parametrize("job", [None, {}, {"job_id": ""}, {"job_id": True}, {"job_id": []}])
def test_missing_task_id_is_uncertain_and_never_resubmitted(provider, circuits, job):
    provider.job = job
    with pytest.raises(DeviceExecutionUnknownError, match="no usable job_id"):
        exchange(QPUDeviceAdapter(), circuits)
    assert provider.events == ["construct", "enter", "submit", "exit"]
    assert_cleaned(provider)


@pytest.mark.parametrize("result", [None, {}, {"status": "failed"}, {"status": "running"}])
def test_unconfirmed_success_never_reaches_decoder(provider, circuits, result):
    provider.result = result
    with pytest.raises(DeviceExecutionUnknownError, match="test-job-17"):
        QPUDeviceAdapter().execute_batch(circuits, shots=3000, request_id="test")
    assert provider.events == ["construct", "enter", "submit", "wait", "exit"]
    assert_cleaned(provider)


def test_suppressed_sdk_exception_still_cannot_become_success(provider, circuits):
    provider.fail_at = "wait"
    provider.suppress = True
    with pytest.raises(DeviceExecutionUnknownError, match="no confirmed response"):
        exchange(QPUDeviceAdapter(), circuits)
    assert_cleaned(provider)


@pytest.mark.parametrize("name", ["../escape.qasm", "..\\escape.qasm", "D:escape.qasm", ""])
def test_upload_names_cannot_escape_directory(provider, name):
    circuits = [QASM3Circuit("id", "Z", name, "OPENQASM 3.0;")]
    with pytest.raises(DeviceClientError, match="basename"):
        exchange(QPUDeviceAdapter(), circuits)
    assert provider.events == []


def test_duplicate_upload_names_fail_before_client(provider, circuits):
    with pytest.raises(DeviceClientError, match="unique"):
        exchange(QPUDeviceAdapter(), [circuits[0], circuits[0]])
    assert provider.events == []
