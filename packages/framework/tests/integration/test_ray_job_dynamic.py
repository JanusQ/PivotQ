"""Fast local and opt-in real-cluster tests for P7.3 dynamic coordination."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import time
import unittest
import uuid

from pivotq._internal.executors import LocalExecutor
from pivotq._internal.framework import ComponentRegistry, FusionFramework
from pivotq._internal.jobs import (
    RayJobClient,
    RayJobDriverContext,
    RayJobDriverResources,
    RayJobRuntimeEnvironment,
    RayJobSpec,
    RayJobStatus,
)
from pivotq._internal.observability import TraceCollector
try:
    from tests.fixtures.p7_dynamic_app import (
        register_dynamic_components,
        run_dynamic_workflow,
    )
except ModuleNotFoundError as error:
    if error.name == "tests.fixtures.p7_dynamic_app":
        raise unittest.SkipTest(
            "P7.3 dynamic fixture is maintained separately and is not part of this framework package"
        ) from error
    raise


_ENABLED = os.environ.get("RAY_QUANTUM_P73_TEST") == "1"
_ADDRESS = os.environ.get("RAY_QUANTUM_JOBS_ADDRESS", "http://127.0.0.1:8265")
_OUTPUT_ROOT = Path(
    os.environ.get("RAY_QUANTUM_DRIVER_OUTPUT_ROOT", "/tmp/ray-quantum-p73")
)
_PROJECT_ROOT = os.environ.get("RAY_QUANTUM_DRIVER_PROJECT_ROOT")
_WAIT_SECONDS = 900.0


class DynamicCoordinatorLocalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.output_path = Path(f"tmp/p73-local/{uuid.uuid4().hex}").resolve()
        self.output_path.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, self.output_path, True)
        self.collector = TraceCollector(max_records=32)
        self.registry = ComponentRegistry()
        self.framework = FusionFramework(
            LocalExecutor(
                self.registry,
                max_workers=2,
                max_pending=4,
                trace_collector=self.collector,
            )
        )
        self.context = RayJobDriverContext(
            "p73-local-run",
            self.output_path,
            trace_collector=self.collector,
        )
        register_dynamic_components(self.framework)

    def tearDown(self) -> None:
        self.framework.close()
        self.registry.close()

    def test_small_equivalent_run_has_exact_counts_reuse_and_trace(self) -> None:
        run_dynamic_workflow(
            self.framework,
            self.context,
            iterations=4,
            require_ray_ids=False,
        )

        audit = self._audit()
        self.assertEqual(audit["status"], "succeeded")
        self.assertEqual(audit["counts"]["task_released"], 4)
        self.assertEqual(audit["counts"]["actor_released"], 4)
        self.assertEqual(audit["instance_counts"], {"actor": 1, "task": 4})
        self.assertEqual(audit["trace"]["record_count"], 8)
        self.assertEqual(len(self._trace_lines()), 8)

    def test_failure_stops_later_work_and_audits_terminal_releases(self) -> None:
        with self.assertRaises(RuntimeError):
            run_dynamic_workflow(
                self.framework,
                self.context,
                iterations=6,
                fail_at=2,
                require_ray_ids=False,
            )

        audit = self._audit()
        self.assertEqual(audit["status"], "failed")
        self.assertEqual(audit["failure_type"], "RuntimeError")
        self.assertEqual(audit["counts"]["task_submitted"], 3)
        self.assertEqual(audit["counts"]["task_completed"], 2)
        self.assertEqual(audit["counts"]["task_released"], 3)
        self.assertEqual(audit["counts"]["actor_submitted"], 2)
        self.assertEqual(audit["counts"]["actor_released"], 2)
        self.assertEqual(audit["trace"]["record_count"], 5)

    def _audit(self) -> dict[str, object]:
        return json.loads(
            (self.output_path / "p73-local-run.p73.audit.json").read_text(
                encoding="utf-8"
            )
        )

    def _trace_lines(self) -> list[str]:
        return (
            self.output_path / "p73-local-run.p73.trace.jsonl"
        ).read_text(encoding="utf-8").splitlines()


@unittest.skipUnless(
    _ENABLED,
    "set RAY_QUANTUM_P73_TEST=1 for the P7.3 1004-iteration acceptance",
)
class DynamicCoordinatorRayJobTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = RayJobClient(_ADDRESS)
        self.created_ids: list[str] = []
        self.submit_calls = 0
        _OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        for submission_id in self.created_ids:
            try:
                status = self.client.status(submission_id)
                if not status.is_terminal:
                    self.client.stop(submission_id)
                    status = self._wait_for_terminal(submission_id)
                if status.is_terminal:
                    self.client.delete(submission_id)
            except Exception:
                pass

    def test_one_submission_runs_exactly_1004_tasks_and_actor_calls(self) -> None:
        submission_id = f"p73-1004-{uuid.uuid4().hex[:10]}"
        self._submit(submission_id, iterations=1004)

        status = self._wait_for_terminal(submission_id)

        self.assertEqual(status, RayJobStatus.SUCCEEDED)
        self.assertEqual(self.submit_calls, 1)
        manifest = self._manifest(submission_id)
        audit = self._audit(submission_id)
        trace_lines = self._trace_lines(submission_id)
        self.assertEqual(manifest["status"], "succeeded")
        self.assertTrue(manifest["cleanup"]["succeeded"])
        self.assertEqual(audit["job_submission_id"], submission_id)
        self.assertEqual(audit["run_id"], submission_id)
        self.assertFalse(audit["scientific_result"])
        self.assertEqual(audit["requested_iterations"], 1004)
        self.assertEqual(
            audit["counts"],
            {
                "actor_completed": 1004,
                "actor_released": 1004,
                "actor_submitted": 1004,
                "task_completed": 1004,
                "task_released": 1004,
                "task_submitted": 1004,
            },
        )
        self.assertEqual(audit["instance_counts"], {"actor": 1, "task": 1004})
        self.assertEqual(audit["trace"]["record_count"], 2008)
        self.assertEqual(audit["trace"]["task_id_count"], 1004)
        self.assertEqual(audit["trace"]["actor_id_count"], 1)
        self.assertEqual(audit["trace"]["dropped_records"], 0)
        self.assertEqual(len(trace_lines), 2008)
        parsed = tuple(json.loads(line) for line in trace_lines)
        self.assertTrue(
            all(item["trace_context"]["job_submission_id"] == submission_id for item in parsed)
        )
        self.assertTrue(
            all(item["execution_ids"]["node_id"] for item in parsed)
        )
        self.assertIn(
            "P73_DYNAMIC_COUNTS=task:1004,actor:1004",
            self.client.logs(submission_id),
        )
        self.assertTrue(self.client.delete(submission_id))
        self.created_ids.remove(submission_id)

    def test_failure_stops_future_work_and_cleans_driver(self) -> None:
        submission_id = f"p73-failure-{uuid.uuid4().hex[:10]}"
        self._submit(submission_id, iterations=6, fail_at=2)

        status = self._wait_for_terminal(submission_id)

        self.assertEqual(status, RayJobStatus.FAILED)
        self.assertEqual(self.submit_calls, 1)
        manifest = self._manifest(submission_id)
        audit = self._audit(submission_id)
        self.assertEqual(manifest["status"], "failed")
        self.assertTrue(manifest["cleanup"]["succeeded"])
        self.assertEqual(audit["status"], "failed")
        self.assertEqual(audit["counts"]["task_submitted"], 3)
        self.assertEqual(audit["counts"]["task_released"], 3)
        self.assertEqual(audit["counts"]["actor_submitted"], 2)
        self.assertEqual(audit["counts"]["actor_released"], 2)
        self.assertEqual(audit["trace"]["record_count"], 5)
        self.assertNotIn("intentional P7.3 fixture failure", self.client.logs(submission_id))
        self.assertTrue(self.client.delete(submission_id))
        self.created_ids.remove(submission_id)

    def _submit(
        self,
        submission_id: str,
        *,
        iterations: int,
        fail_at: int | None = None,
    ) -> None:
        env_vars = {
            "PYTHONPATH": "src",
            "RAY_QUANTUM_P73_ITERATIONS": str(iterations),
        }
        if fail_at is not None:
            env_vars["RAY_QUANTUM_P73_FAIL_AT"] = str(fail_at)
        entrypoint = " ".join(
            shlex.quote(part)
            for part in (
                "exec",
                sys.executable,
                "-m",
                "pivotq._internal.jobs.driver",
                "--run-id",
                submission_id,
                "--registration",
                "tests.fixtures.p7_dynamic_app:register_dynamic_components",
                "--runner",
                "tests.fixtures.p7_dynamic_app:run_from_environment",
                "--namespace",
                "ray-quantum-p73",
                "--output-dir",
                str(_OUTPUT_ROOT),
                "--trace-max-records",
                str(iterations * 2),
            )
        )
        spec = RayJobSpec(
            submission_id,
            entrypoint,
            runtime_environment=RayJobRuntimeEnvironment(
                working_dir=_PROJECT_ROOT,
                env_vars=env_vars,
            ),
            driver_resources=RayJobDriverResources(num_cpus=0.2),
        )
        self.submit_calls += 1
        handle = self.client.submit(spec)
        self.created_ids.append(handle.submission_id)

    def _wait_for_terminal(self, submission_id: str) -> RayJobStatus:
        deadline = time.monotonic() + _WAIT_SECONDS
        status = self.client.status(submission_id)
        while not status.is_terminal and time.monotonic() < deadline:
            time.sleep(0.2)
            status = self.client.status(submission_id)
        if not status.is_terminal:
            self.fail(f"P7.3 Job remained in {status.value!r}")
        return status

    def _manifest(self, submission_id: str) -> dict[str, object]:
        return json.loads(
            (_OUTPUT_ROOT / f"{submission_id}.manifest.json").read_text(
                encoding="utf-8"
            )
        )

    def _audit(self, submission_id: str) -> dict[str, object]:
        return json.loads(
            (_OUTPUT_ROOT / f"{submission_id}.p73.audit.json").read_text(
                encoding="utf-8"
            )
        )

    def _trace_lines(self, submission_id: str) -> list[str]:
        return (
            _OUTPUT_ROOT / f"{submission_id}.p73.trace.jsonl"
        ).read_text(encoding="utf-8").splitlines()


if __name__ == "__main__":
    unittest.main()
