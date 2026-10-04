"""Driver manifest v2 contract: no Ray initialization or cluster operations."""

from dataclasses import replace
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from pivotq._internal.executors.cleanup import ActorCleanupRecord, ExecutorCleanupError, ExecutorCleanupReport
from pivotq._internal.jobs.driver import RayJobDriverConfig, RayJobDriverStatus, run_driver, _manifest, _write_initial_manifest, _replace_manifest


def record(name="component", state="timed_out"):
    return ActorCleanupRecord(
        name, f"ray-quantum-{'a' * 32}-{name}", state,
        "GetTimeoutError" if state == "timed_out" else None, 2,
        "requested", "fallback_after_timeout" if state == "timed_out" else "normal_after_close", None,
    )


def test_initial_v2_manifest_and_cli_config_version_are_independent(tmp_path):
    config = RayJobDriverConfig("run", "a:b", "a:c", "run-ns", tmp_path)
    assert config.schema_version == 1
    observed = []
    def registration(framework):
        observed.append(json.loads(config.manifest_path.read_text()))
    executor = SimpleNamespace(closed=False, cleanup_report=ExecutorCleanupReport())
    def close():
        executor.closed = True
        executor.cleanup_report = ExecutorCleanupReport.completed([], total=0)
    executor.close = close
    fake_ray = Mock()
    fake_ray.is_initialized.return_value = False
    with patch("pivotq._internal.jobs.driver._load_callable", side_effect=[registration, lambda framework, context: None]), patch("pivotq._internal.jobs.driver._load_ray_module", return_value=fake_ray), patch("pivotq._internal.jobs.driver._load_ray_executor", return_value=lambda *args, **kwargs: executor), patch("pivotq._internal.jobs.driver.FusionFramework", side_effect=lambda e: e):
        manifest = run_driver(config)
    initial = observed[0]
    assert initial["schema_version"] == 2
    assert initial["cleanup"]["outcome"] == "pending"
    assert initial["finished_at"] is initial["exit_code"] is None
    assert initial["cleanup"]["actor_cleanup"]["records_complete"] is False
    assert manifest.cleanup_succeeded
    assert manifest.cleanup_outcome == "clean"
    assert manifest.ray_connection_owned


@pytest.mark.parametrize("failure", [None, "registry", "trace", "shutdown", "borrowed"])
def test_stop_timeout_report_retains_legacy_false_and_owned_connection(tmp_path, failure):
    config = RayJobDriverConfig("run", "a:b", "a:c", "run-ns", tmp_path)
    report = ExecutorCleanupReport.completed([record()], total=1)
    executor = SimpleNamespace(closed=False, cleanup_report=ExecutorCleanupReport())
    def close():
        executor.closed = True
        executor.cleanup_report = report
        if failure == "trace":
            raise RuntimeError("secret trace finalize failure")
        raise ExecutorCleanupError(report)
    executor.close = close
    def stop(framework, context):
        context._request_stop()
        context.raise_if_stop_requested()
    fake_ray = Mock()
    fake_ray.is_initialized.return_value = failure == "borrowed"
    fake_ray.get_runtime_context.return_value = SimpleNamespace(namespace=config.namespace)
    if failure == "shutdown":
        fake_ray.shutdown.side_effect = RuntimeError("secret shutdown failure")
    with patch("pivotq._internal.jobs.driver._load_callable", side_effect=[lambda framework: None, stop]), patch("pivotq._internal.jobs.driver._load_ray_module", return_value=fake_ray), patch("pivotq._internal.jobs.driver._load_ray_executor", return_value=lambda *args, **kwargs: executor), patch("pivotq._internal.jobs.driver.FusionFramework", side_effect=lambda e: e), patch("pivotq._internal.jobs.driver.ComponentRegistry") as registry:
        registry.return_value.closed = True
        if failure == "registry":
            registry.return_value.close.side_effect = RuntimeError("secret")
        manifest = run_driver(config)
    assert manifest.status == RayJobDriverStatus.STOP_REQUESTED
    assert manifest.exit_code == 143
    assert manifest.cleanup_succeeded is False
    assert manifest.cleanup_outcome == ("failed" if failure else "fallback_pending_verification")
    disk = json.loads(config.manifest_path.read_text())
    assert disk == manifest.as_dict()
    assert disk["cleanup"]["ray_connection_owned"] == (failure != "borrowed")
    assert "secret" not in config.manifest_path.read_text()


def test_manifest_overflow_produces_a_small_incomplete_failure(tmp_path):
    records = [replace(record(f"{index}" + "量" * 120), actor_name=f"{index}" + "量" * 500) for index in range(32)]
    report = ExecutorCleanupReport.completed(records, total=32)
    assert report.records_complete
    config = RayJobDriverConfig("run", "a:b", "a:c", "run-ns", tmp_path)
    manifest = _manifest(config, status=RayJobDriverStatus.STOP_REQUESTED, exit_code=143, started_at="2026-09-07T00:00:00Z", finished_at="2026-09-07T00:00:01Z", actor_cleanup=report, cleanup_outcome=report.outcome, cleanup_succeeded=False)
    assert manifest.cleanup_outcome == "failed"
    assert not manifest.actor_cleanup.records_complete
    assert len(json.dumps(manifest.as_dict()).encode()) < 64 * 1024


@pytest.mark.parametrize("initial", [False, True])
def test_manifest_writer_never_deletes_another_writer_temporary_file(tmp_path, initial):
    config = RayJobDriverConfig("run", "a:b", "a:c", "run-ns", tmp_path)
    manifest = _manifest(config, status=RayJobDriverStatus.STARTING, exit_code=None, started_at="2026-09-07T00:00:00Z", finished_at=None)
    path = config.manifest_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"existing manifest")
    suffix = "initial.tmp" if initial else "tmp"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{suffix}")
    temporary.write_bytes(b"another writer")
    with pytest.raises((ValueError, FileExistsError)):
        (_write_initial_manifest if initial else _replace_manifest)(path, manifest)
    assert temporary.read_bytes() == b"another writer"
    assert path.read_bytes() == b"existing manifest"
