"""Unit tests for cluster-side Driver bootstrap ownership and manifests."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from pivotq._internal.framework import ComponentRegistry
from pivotq._internal.executors.cleanup import ExecutorCleanupReport
from pivotq._internal.jobs.driver import (
    RayJobDriverConfig,
    RayJobDriverContext,
    RayJobDriverStatus,
    main,
    run_driver,
)
from pivotq._internal.observability import TraceEventJournalConfig


_APPLICATION_CLEANUP_AVAILABLE = hasattr(RayJobDriverContext, "record_cleanup")
_ARCHIVED_APPLICATION_CLEANUP_REASON = (
    "record_cleanup belongs to the archived IR/source Job contract (D-071/D-091)"
)


_EVENTS: list[str] = []
_EXECUTOR_OPTIONS: list[dict[str, object]] = []


class _FakeRuntimeContext:
    namespace = "p72-tests"


class _FakeRay:
    def __init__(self, *, initialized: bool = False) -> None:
        self.initialized = initialized
        self.init_arguments: dict[str, object] | None = None

    def is_initialized(self) -> bool:
        return self.initialized

    def init(self, **kwargs: object) -> object:
        _EVENTS.append("ray.init")
        self.init_arguments = dict(kwargs)
        self.initialized = True
        return object()

    def shutdown(self) -> None:
        _EVENTS.append("ray.shutdown")
        self.initialized = False

    def get_runtime_context(self) -> _FakeRuntimeContext:
        return _FakeRuntimeContext()


class _RecordingRegistry(ComponentRegistry):
    def close(self) -> None:
        _EVENTS.append("registry.close")
        super().close()


class _FakeRayExecutor:
    def __init__(self, registry: ComponentRegistry, **kwargs: object) -> None:
        _EVENTS.append("executor.init")
        self.registry = registry
        self.closed = False
        self.cleanup_report = ExecutorCleanupReport()
        self.options = dict(kwargs)
        _EXECUTOR_OPTIONS.append(self.options)

    def submit(self, invocation: object) -> object:
        raise AssertionError("unit runner must not submit component work")

    def result(self, handle: object) -> object:
        raise AssertionError("unit runner must not resolve component work")

    def release(self, handle: object) -> None:
        raise AssertionError("unit runner must not release component work")

    def close(self) -> None:
        _EVENTS.append("executor.close")
        self.closed = True
        self.cleanup_report = ExecutorCleanupReport.completed([], total=0)


def _registration(framework: object) -> None:
    _EVENTS.append("registration")


def _successful_runner(framework: object, context: object) -> None:
    _EVENTS.append("runner")


def _failing_runner(framework: object, context: object) -> None:
    _EVENTS.append("runner")
    raise RuntimeError("sensitive runner detail")


def _stop_requested_runner(framework: object, context: object) -> None:
    del framework
    context._request_stop()
    context.raise_if_stop_requested()


def _trace_runner(framework: object, context: object) -> None:
    del framework
    _EVENTS.append(f"trace.capacity={context.trace_collector.max_records}")


def _application_cleanup_runner(framework: object, context: object) -> None:
    del framework
    context.record_cleanup("runtime_closed", True)
    context.record_cleanup("cache_closed", True)
    context.record_cleanup("runtime_closed", True)


def _failed_application_cleanup_runner(framework: object, context: object) -> None:
    del framework
    context.record_cleanup("runtime_closed", False)


class RayJobDriverTest(unittest.TestCase):
    def setUp(self) -> None:
        _EVENTS.clear()
        _EXECUTOR_OPTIONS.clear()
        self.output_path = Path(f"tmp/p72-unit/{uuid.uuid4().hex}").resolve()
        self.output_path.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, self.output_path, True)
        self.output_dir = str(self.output_path)

    def _config(
        self,
        run_id: str = "p72-run",
        *,
        trace_max_records: int | None = None,
        trace_event_max_records: int | None = None,
    ) -> RayJobDriverConfig:
        return RayJobDriverConfig(
            run_id=run_id,
            registration_target="external.registration:register",
            runner_target="external.runner:run",
            namespace="p72-tests",
            output_dir=self.output_dir,
            actor_close_timeout_seconds=2,
            trace_max_records=trace_max_records,
            trace_event_max_records=trace_event_max_records,
        )

    def _run(
        self,
        runner: object,
        *,
        ray: _FakeRay | None = None,
        trace_max_records: int | None = None,
        trace_event_max_records: int | None = None,
    ):
        targets = [_registration, runner]
        with (
            patch("pivotq._internal.jobs.driver._load_callable", side_effect=targets),
            patch("pivotq._internal.jobs.driver._load_ray_module", return_value=ray or _FakeRay()),
            patch("pivotq._internal.jobs.driver._load_ray_executor", return_value=_FakeRayExecutor),
            patch("pivotq._internal.jobs.driver.ComponentRegistry", _RecordingRegistry),
        ):
            return run_driver(
                self._config(
                    trace_max_records=trace_max_records,
                    trace_event_max_records=trace_event_max_records,
                )
            )

    def test_success_owns_and_closes_resources_in_reverse_order(self) -> None:
        fake_ray = _FakeRay()

        manifest = self._run(_successful_runner, ray=fake_ray)

        self.assertEqual(manifest.status, RayJobDriverStatus.SUCCEEDED)
        self.assertEqual(manifest.exit_code, 0)
        self.assertTrue(manifest.cleanup_succeeded)
        self.assertEqual(
            _EVENTS,
            [
                "ray.init",
                "executor.init",
                "registration",
                "runner",
                "executor.close",
                "registry.close",
                "ray.shutdown",
            ],
        )
        self.assertEqual(
            fake_ray.init_arguments,
            {
                "address": "auto",
                "namespace": "p72-tests",
                "log_to_driver": False,
            },
        )
        on_disk = json.loads(self._config().manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["status"], "succeeded")
        self.assertTrue(on_disk["cleanup"]["succeeded"])

    def test_runner_failure_is_redacted_and_cleanup_still_runs(self) -> None:
        manifest = self._run(_failing_runner)

        self.assertEqual(manifest.status, RayJobDriverStatus.FAILED)
        self.assertEqual(manifest.exit_code, 1)
        self.assertEqual(manifest.failure_type, "RuntimeError")
        serialized = self._config().manifest_path.read_text(encoding="utf-8")
        self.assertNotIn("sensitive runner detail", serialized)
        self.assertEqual(_EVENTS[-3:], ["executor.close", "registry.close", "ray.shutdown"])

    def test_existing_runtime_is_borrowed_and_not_shutdown(self) -> None:
        fake_ray = _FakeRay(initialized=True)

        manifest = self._run(_successful_runner, ray=fake_ray)

        self.assertEqual(manifest.status, RayJobDriverStatus.SUCCEEDED)
        self.assertNotIn("ray.init", _EVENTS)
        self.assertNotIn("ray.shutdown", _EVENTS)
        self.assertFalse(manifest.ray_disconnected)

    def test_cooperative_stop_has_distinct_status_and_exit_code(self) -> None:
        manifest = self._run(_stop_requested_runner)

        self.assertEqual(manifest.status, RayJobDriverStatus.STOP_REQUESTED)
        self.assertEqual(manifest.exit_code, 143)
        self.assertIsNone(manifest.failure_type)
        self.assertTrue(manifest.cleanup_succeeded)

    def test_optional_trace_collector_is_owned_by_driver_context(self) -> None:
        manifest = self._run(_trace_runner, trace_max_records=8)

        self.assertEqual(manifest.status, RayJobDriverStatus.SUCCEEDED)
        self.assertIn("trace.capacity=8", _EVENTS)

    def test_trace_v2_is_default_off_and_passed_as_serializable_config(self) -> None:
        self._run(_successful_runner)

        self.assertNotIn("trace_event_journal", _EXECUTOR_OPTIONS[-1])

        second_output = Path(f"tmp/p72-unit/{uuid.uuid4().hex}").resolve()
        second_output.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, second_output, True)
        self.output_dir = str(second_output)
        self._run(_successful_runner, trace_event_max_records=321)

        journal = _EXECUTOR_OPTIONS[-1]["trace_event_journal"]
        self.assertIsInstance(journal, TraceEventJournalConfig)
        self.assertEqual(journal.run_id, "p72-run")
        self.assertEqual(journal.max_records, 321)
        self.assertEqual(
            Path(journal.event_path),
            second_output / "p72-run.trace-v2.jsonl",
        )
        self.assertEqual(
            Path(journal.manifest_path),
            second_output / "p72-run.trace-v2.manifest.json",
        )

    @unittest.skipUnless(
        _APPLICATION_CLEANUP_AVAILABLE,
        _ARCHIVED_APPLICATION_CLEANUP_REASON,
    )
    def test_application_cleanup_is_audited_without_payloads(self) -> None:
        manifest = self._run(_application_cleanup_runner)

        self.assertEqual(
            manifest.application_cleanup,
            (("cache_closed", True), ("runtime_closed", True)),
        )
        on_disk = json.loads(self._config().manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            on_disk["cleanup"]["application"],
            {"cache_closed": True, "runtime_closed": True},
        )
        self.assertTrue(on_disk["cleanup"]["succeeded"])

    @unittest.skipUnless(
        _APPLICATION_CLEANUP_AVAILABLE,
        _ARCHIVED_APPLICATION_CLEANUP_REASON,
    )
    def test_failed_application_cleanup_fails_an_otherwise_successful_job(self) -> None:
        manifest = self._run(_failed_application_cleanup_runner)

        self.assertEqual(manifest.status, RayJobDriverStatus.FAILED)
        self.assertEqual(manifest.failure_type, "DriverCleanupError")
        self.assertFalse(manifest.cleanup_succeeded)

    @unittest.skipUnless(
        _APPLICATION_CLEANUP_AVAILABLE,
        _ARCHIVED_APPLICATION_CLEANUP_REASON,
    )
    def test_application_cleanup_result_cannot_be_rewritten(self) -> None:
        def conflicting_runner(framework: object, context: object) -> None:
            del framework
            context.record_cleanup("runtime_closed", False)
            context.record_cleanup("runtime_closed", True)

        manifest = self._run(conflicting_runner)

        self.assertEqual(manifest.status, RayJobDriverStatus.FAILED)
        self.assertEqual(manifest.failure_type, "ValueError")
        self.assertFalse(manifest.cleanup_succeeded)

    def test_invalid_config_and_manifest_reuse_are_rejected(self) -> None:
        invalid = [
            lambda: RayJobDriverConfig(
                "bad id", "a:b", "c:d", "namespace", self.output_dir
            ),
            lambda: RayJobDriverConfig(
                "run", "invalid", "c:d", "namespace", self.output_dir
            ),
            lambda: RayJobDriverConfig(
                "run", "a:b", "c:d", "namespace", "relative-output"
            ),
            lambda: RayJobDriverConfig(
                "run", "a:b", "c:d", "namespace", self.output_dir, ray_address="ray://host:10001"
            ),
            lambda: RayJobDriverConfig(
                "run", "a:b", "c:d", "namespace", self.output_dir, trace_max_records=0
            ),
            lambda: RayJobDriverConfig(
                "run",
                "a:b",
                "c:d",
                "namespace",
                self.output_dir,
                trace_event_max_records=0,
            ),
        ]
        for call in invalid:
            with self.subTest(call=call), self.assertRaises((TypeError, ValueError)):
                call()

        self._run(_successful_runner)
        with self.assertRaises(ValueError):
            self._run(_successful_runner)

    def test_cli_rejects_invalid_configuration_without_echoing_targets(self) -> None:
        with patch("sys.stderr") as stderr:
            exit_code = main(
                [
                    "--run-id",
                    "bad id",
                    "--registration",
                    "secret.module:register",
                    "--runner",
                    "secret.module:run",
                    "--namespace",
                    "p72-tests",
                    "--output-dir",
                    self.output_dir,
                ]
            )

        self.assertEqual(exit_code, 2)
        rendered = "".join(call.args[0] for call in stderr.write.call_args_list if call.args)
        self.assertNotIn("secret.module", rendered)

    def test_cli_passes_explicit_trace_v2_capacity(self) -> None:
        completed = SimpleNamespace(
            status=RayJobDriverStatus.SUCCEEDED,
            exit_code=0,
        )
        with (
            patch("pivotq._internal.jobs.driver.run_driver", return_value=completed) as run,
            patch("sys.stdout"),
        ):
            exit_code = main(
                [
                    "--run-id",
                    "run-1",
                    "--registration",
                    "external.registration:register",
                    "--runner",
                    "external.runner:run",
                    "--namespace",
                    "p72-tests",
                    "--output-dir",
                    self.output_dir,
                    "--trace-event-max-records",
                    "77",
                ]
            )

        self.assertEqual(exit_code, 0)
        config = run.call_args.args[0]
        self.assertEqual(config.trace_event_max_records, 77)


if __name__ == "__main__":
    unittest.main()
