"""Offline signal delivery through real Driver/Executor/Trace cleanup.

Only the signal table and Ray transport are faked. No OS signal, Ray service,
subprocess, network connection or remote task is created by these tests.
"""

from hashlib import sha256
import json
import signal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import ray

from pivotq._internal.framework import ComponentRegistry
from pivotq._internal.framework.models import ComponentSpec, ExecutionMode, InvocationSpec, ResourceRequest
from pivotq._internal.executors import ray as executor_module
from pivotq._internal.executors.ray import RayExecutor, _RayInvocationEntry
from pivotq._internal.jobs import driver
from pivotq._internal.observability.events import (
    TraceEventJournal, TraceEventKind, TraceEventSource,
)
from pivotq._internal.framework.models import InvocationStatus


class _Component:
    def run(self):
        return None


class _OfflineDriver:
    def __init__(self, monkeypatch, tmp_path, *, phase=None, signum=signal.SIGTERM,
                 initial_stop=True, fault=None):
        self.phase, self.signum = phase, signum
        self.initial_stop, self.fault = initial_stop, fault
        self.events = []
        self.delivered = []
        self.config = driver.RayJobDriverConfig(
            "offline-cleanup", "fixture:register", "fixture:run", "offline-ns",
            tmp_path.resolve(), trace_max_records=10, trace_event_max_records=10,
            actor_close_timeout_seconds=2,
        )
        # The prior SIGTERM callback matches installed Ray 2.31 worker.init:
        # sigterm_handler(signum, frame): sys.exit(signum).
        def prior_term(signum, frame):
            raise SystemExit(signum)
        def prior_int(signum, frame):
            raise KeyboardInterrupt()
        self.previous = {signal.SIGTERM: prior_term, signal.SIGINT: prior_int}
        self.handlers = dict(self.previous)
        monkeypatch.setattr(driver.signal, "getsignal", self.handlers.__getitem__)
        monkeypatch.setattr(driver.signal, "signal", self.handlers.__setitem__)
        monkeypatch.setattr(ray, "init", Mock(side_effect=AssertionError("real Ray init forbidden")))
        monkeypatch.setattr(ray, "shutdown", Mock(side_effect=AssertionError("real Ray shutdown forbidden")))
        monkeypatch.setattr(ray, "is_initialized", lambda: True)
        monkeypatch.setattr(ray, "wait", lambda *args, **kwargs: ([], []))
        monkeypatch.setattr(ray, "cancel", lambda *args, **kwargs: self.at("cancel"))
        monkeypatch.setattr(ray, "get", lambda value, **kwargs: value)
        monkeypatch.setattr(ray, "kill", lambda *args, **kwargs: self.events.append("kill"))
        fake_ray = SimpleNamespace(
            is_initialized=lambda: False, init=lambda **kwargs: None,
            shutdown=lambda: self.at("shutdown"),
        )
        monkeypatch.setattr(driver, "_load_ray_module", lambda: fake_ray)
        monkeypatch.setattr(driver, "_load_callable", Mock(side_effect=[self.register, self.runner]))
        monkeypatch.setattr(driver, "_load_ray_executor", lambda: self.make_executor)
        monkeypatch.setattr(executor_module, "_create_trace_event_sink", self.make_sink)
        for name, phase_name in [("_drain_ready_traces", "drain"),
                                 ("_record_driver_terminal", "terminal"),
                                 ("_record_driver_finished_event", "finished")]:
            original = getattr(RayExecutor, name)
            def wrapped(executor, *args, _original=original, _phase=phase_name, **kwargs):
                self.at(_phase)
                return _original(executor, *args, **kwargs)
            monkeypatch.setattr(RayExecutor, name, wrapped)
        original_registry_close = ComponentRegistry.close
        def close_registry(registry):
            self.at("registry")
            return original_registry_close(registry)
        monkeypatch.setattr(ComponentRegistry, "close", close_registry)
        original_replace = driver._replace_manifest
        def replace_manifest(path, manifest):
            self.at("manifest")
            if self.fault == "manifest":
                raise OSError("private manifest payload")
            return original_replace(path, manifest)
        monkeypatch.setattr(driver, "_replace_manifest", replace_manifest)

    def emit(self):
        self.delivered.append(self.signum)
        self.handlers[self.signum](self.signum, None)

    def at(self, phase):
        self.events.append(phase)
        if self.phase == phase:
            self.emit()
            self.emit()
        if self.fault == phase and phase != "manifest":
            raise RuntimeError("private cleanup payload")

    def make_sink(self, config):
        self.journal = TraceEventJournal(config)
        def finalize():
            self.at("trace_finalize")
            return self.journal.finalize()
        return SimpleNamespace(
            record=SimpleNamespace(remote=self.journal.record),
            finalize=SimpleNamespace(remote=finalize),
        )

    def make_executor(self, registry, **kwargs):
        self.executor = RayExecutor(registry, **kwargs)
        return self.executor

    def register(self, framework):
        framework.register(ComponentSpec("component", ExecutionMode.TASK, ResourceRequest(num_cpus=1), ("run",)), _Component)

    def runner(self, framework, context):
        self.context = context
        invocation = InvocationSpec("invocation", "component", "run")
        registration = framework.registry.get("component")
        entry = _RayInvocationEntry(invocation, registration, object())
        self.executor._entries[invocation.invocation_id] = entry
        for event, source, status in [
            (TraceEventKind.SUBMITTED, TraceEventSource.DRIVER, InvocationStatus.QUEUED),
            (TraceEventKind.STARTED, TraceEventSource.WORKER, InvocationStatus.RUNNING),
        ]:
            executor_module._send_trace_event(
                self.executor._trace_event_sink, invocation, registration.spec,
                event=event, source=source, status=status, run_id=context.run_id,
            )
        if self.initial_stop:
            self.emit()

    def run(self):
        try:
            return driver.run_driver(self.config)
        finally:
            assert self.handlers == self.previous, "Signal handlers leaked after run_driver"

    def assert_trace_finalized(self):
        trace = json.loads(self.config.trace_event_manifest_path.read_text())
        stream = self.config.trace_event_path.read_bytes()
        assert trace["complete"] is True
        assert trace["stream"]["sha256"] == sha256(stream).hexdigest()
        assert trace["stream"]["size_bytes"] == len(stream)
        assert json.loads(stream.splitlines()[-1])["event"] == "finished"


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT], ids=["sigterm", "sigint"])
@pytest.mark.parametrize("phase", ["drain", "terminal", "finished", "cancel", "trace_finalize", "registry", "shutdown", "manifest"])
def test_repeated_signal_during_cleanup_finishes_report_and_trace(monkeypatch, tmp_path, signum, phase):
    fixture = _OfflineDriver(monkeypatch, tmp_path, phase=phase, signum=signum)
    manifest = fixture.run()
    assert manifest.status is driver.RayJobDriverStatus.STOP_REQUESTED
    assert manifest.exit_code == 143
    assert manifest.cleanup_succeeded, manifest.as_dict()
    assert manifest.actor_cleanup.records_complete
    assert manifest.framework_closed and manifest.registry_closed and manifest.ray_disconnected
    assert len(fixture.delivered) == 3
    fixture.assert_trace_finalized()


def test_single_stop_control_completes_cleanup(monkeypatch, tmp_path, capsys):
    fixture = _OfflineDriver(monkeypatch, tmp_path)
    manifest = fixture.run()
    assert manifest.cleanup_succeeded
    assert len(fixture.delivered) == 1
    fixture.assert_trace_finalized()
    assert 'RAY_QUANTUM_DRIVER_STOP_SIGNALS={"received":1,"during_cleanup":0}' in capsys.readouterr().err


@pytest.mark.parametrize("phase", ["drain", "cancel", "trace_finalize", "registry", "shutdown"])
def test_first_stop_during_cleanup_is_recorded_without_interrupting_it(monkeypatch, tmp_path, phase):
    fixture = _OfflineDriver(monkeypatch, tmp_path, phase=phase, initial_stop=False)
    manifest = fixture.run()
    assert manifest.status is driver.RayJobDriverStatus.STOP_REQUESTED
    assert manifest.exit_code == 143 and manifest.cleanup_succeeded
    assert fixture.context.stop_requested
    fixture.assert_trace_finalized()


def test_success_without_stop_preserves_success(monkeypatch, tmp_path):
    fixture = _OfflineDriver(monkeypatch, tmp_path, initial_stop=False)
    manifest = fixture.run()
    assert manifest.status is driver.RayJobDriverStatus.SUCCEEDED
    assert manifest.exit_code == 0 and manifest.cleanup_succeeded
    assert not fixture.context.stop_requested


def test_runner_failure_is_preserved_if_first_signal_arrives_during_cleanup(monkeypatch, tmp_path):
    fixture = _OfflineDriver(monkeypatch, tmp_path, phase="cancel", initial_stop=False)
    def runner(framework, context):
        fixture.runner(framework, context)
        raise ValueError("private runner payload")
    monkeypatch.setattr(driver, "_load_callable", Mock(side_effect=[fixture.register, runner]))
    manifest = fixture.run()
    assert manifest.status is driver.RayJobDriverStatus.FAILED
    assert manifest.exit_code == 1 and manifest.failure_type == "ValueError"
    assert manifest.cleanup_succeeded
    assert "private" not in fixture.config.manifest_path.read_text()


@pytest.mark.parametrize("fault,expected_phase", [("drain", "framework_close"), ("registry", "registry_close"), ("shutdown", "ray_shutdown")])
def test_unrelated_cleanup_failure_is_redacted_and_remains_failed(monkeypatch, tmp_path, capsys, fault, expected_phase):
    fixture = _OfflineDriver(monkeypatch, tmp_path, fault=fault)
    manifest = fixture.run()
    assert manifest.status is driver.RayJobDriverStatus.STOP_REQUESTED
    assert manifest.exit_code == 143
    assert manifest.cleanup_outcome == "failed" and not manifest.cleanup_succeeded
    output = capsys.readouterr().err
    assert '"phase":"' + expected_phase + '"' in output
    assert '"error_type":"RuntimeError"' in output
    assert "private" not in output + fixture.config.manifest_path.read_text()


def test_manifest_write_failure_restores_handlers_and_propagates(monkeypatch, tmp_path):
    fixture = _OfflineDriver(monkeypatch, tmp_path, fault="manifest")
    with pytest.raises(OSError, match="private manifest payload"):
        fixture.run()


def test_ray_disconnected_before_close_is_not_marked_clean(monkeypatch, tmp_path, capsys):
    fixture = _OfflineDriver(monkeypatch, tmp_path)
    original_runner = fixture.runner
    def runner(framework, context):
        try:
            original_runner(framework, context)
        finally:
            monkeypatch.setattr(ray, "is_initialized", lambda: False)
    monkeypatch.setattr(driver, "_load_callable", Mock(side_effect=[fixture.register, runner]))
    manifest = fixture.run()
    assert manifest.cleanup_outcome == "failed"
    assert manifest.actor_cleanup.records_complete is False
    assert '"error_type":"IncompleteCleanupReport"' in capsys.readouterr().err


def test_reentrant_signal_during_stop_event_set_does_not_reenter_event(monkeypatch, tmp_path):
    fixture = _OfflineDriver(monkeypatch, tmp_path)
    original = driver.RayJobDriverContext._request_stop
    calls = []
    def request_stop(context):
        calls.append(True)
        assert len(calls) == 1, "Signal reentered Event.set"
        fixture.emit()
        original(context)
    monkeypatch.setattr(driver.RayJobDriverContext, "_request_stop", request_stop)
    manifest = fixture.run()
    assert manifest.status is driver.RayJobDriverStatus.STOP_REQUESTED
    assert manifest.cleanup_succeeded
    assert len(calls) == 1


def test_partial_signal_installation_is_restored(monkeypatch, tmp_path):
    fixture = _OfflineDriver(monkeypatch, tmp_path)
    failed_once = False
    def install(signum, handler):
        nonlocal failed_once
        if signum == signal.SIGINT and not failed_once:
            failed_once = True
            raise RuntimeError("private signal installation error")
        fixture.handlers[signum] = handler
    monkeypatch.setattr(driver.signal, "signal", install)
    manifest = fixture.run()
    assert failed_once
    assert manifest.status is driver.RayJobDriverStatus.FAILED
    assert manifest.failure_type == "RuntimeError"


def test_signal_at_installation_return_still_restores_handlers(monkeypatch, tmp_path):
    fixture = _OfflineDriver(monkeypatch, tmp_path)
    original = driver._install_stop_signal_handlers
    def install(*args):
        begin_cleanup = original(*args)
        fixture.emit()
        return begin_cleanup
    monkeypatch.setattr(driver, "_install_stop_signal_handlers", install)
    manifest = fixture.run()
    assert manifest.status is driver.RayJobDriverStatus.STOP_REQUESTED
    assert manifest.exit_code == 143 and manifest.ray_disconnected


def test_repeated_signal_counters_are_logged_after_cleanup(monkeypatch, tmp_path, capsys):
    fixture = _OfflineDriver(monkeypatch, tmp_path, phase="drain")
    manifest = fixture.run()
    assert manifest.cleanup_succeeded
    output = capsys.readouterr().err
    assert 'RAY_QUANTUM_DRIVER_STOP_SIGNALS={"received":3,"during_cleanup":2}' in output
    assert "CLEANUP_ERROR" not in output


def test_non_main_thread_does_not_install_process_signal_handlers(monkeypatch, tmp_path):
    fixture = _OfflineDriver(monkeypatch, tmp_path, initial_stop=False)
    monkeypatch.setattr(driver, "current_thread", lambda: object())
    manifest = fixture.run()
    assert manifest.status is driver.RayJobDriverStatus.SUCCEEDED
    assert manifest.cleanup_succeeded


def test_closed_diagnostic_stream_does_not_abort_remaining_cleanup(monkeypatch, tmp_path):
    fixture = _OfflineDriver(monkeypatch, tmp_path, fault="drain")
    monkeypatch.setattr(driver.sys, "stderr", SimpleNamespace(write=Mock(side_effect=OSError("closed"))))
    manifest = fixture.run()
    assert not manifest.cleanup_succeeded
    assert manifest.registry_closed and manifest.ray_disconnected
