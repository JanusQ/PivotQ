"""Opt-in P7.2 end-to-end tests through the actual Ray Jobs service."""

from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import shlex
import sys
import time
import unittest
import uuid

from pivotq._internal.jobs import (
    RayJobClient,
    RayJobDriverResources,
    RayJobRuntimeEnvironment,
    RayJobSpec,
    RayJobStatus,
)


_ENABLED = os.environ.get("RAY_QUANTUM_JOB_DRIVER_TEST") == "1"
_ADDRESS = os.environ.get("RAY_QUANTUM_JOBS_ADDRESS", "http://127.0.0.1:8265")
_OUTPUT_ROOT = Path(os.environ.get("RAY_QUANTUM_DRIVER_OUTPUT_ROOT", "/tmp/ray-quantum-p72"))
_PROJECT_ROOT = os.environ.get("RAY_QUANTUM_DRIVER_PROJECT_ROOT")
_WAIT_SECONDS = 45.0


def _driver_spec(submission_id: str, runner_name: str) -> RayJobSpec:
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
            "tests.fixtures.p7_driver_app:register_components",
            "--runner",
            f"tests.fixtures.p7_driver_app:{runner_name}",
            "--namespace",
            "ray-quantum-p72",
            "--output-dir",
            str(_OUTPUT_ROOT),
        )
    )
    return RayJobSpec(
        submission_id,
        entrypoint,
        runtime_environment=RayJobRuntimeEnvironment(
            working_dir=_PROJECT_ROOT,
            env_vars={"PYTHONPATH": "src"},
        ),
        driver_resources=RayJobDriverResources(num_cpus=0.2),
    )


def _submit_from_short_lived_process(
    address: str,
    submission_id: str,
    runner_name: str,
) -> None:
    RayJobClient(address).submit(_driver_spec(submission_id, runner_name))


@unittest.skipUnless(
    _ENABLED,
    "set RAY_QUANTUM_JOB_DRIVER_TEST=1 for the P7.2 Driver smoke",
)
class RayJobDriverSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = RayJobClient(_ADDRESS)
        self.created_ids: list[str] = []
        _OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        for submission_id in self.created_ids:
            try:
                status = self.client.status(submission_id)
                if not status.is_terminal:
                    self.client.stop(submission_id)
                    status = self._wait_for_status(
                        submission_id,
                        {RayJobStatus.STOPPED, RayJobStatus.FAILED},
                    )
                if status.is_terminal:
                    self.client.delete(submission_id)
            except Exception:
                pass

    def test_success_and_failure_map_to_job_states_and_manifests(self) -> None:
        cases = (
            ("run_once", RayJobStatus.SUCCEEDED, "succeeded", 0),
            ("fail_after_setup", RayJobStatus.FAILED, "failed", 1),
        )
        for runner_name, expected_job, expected_driver, expected_code in cases:
            with self.subTest(runner=runner_name):
                submission_id = self._new_submission_id(runner_name)
                self._submit(submission_id, runner_name)
                status = self._wait_for_status(
                    submission_id,
                    {RayJobStatus.SUCCEEDED, RayJobStatus.FAILED},
                )
                self.assertEqual(status, expected_job)
                manifest = self._manifest(submission_id)
                self.assertEqual(manifest["status"], expected_driver)
                self.assertEqual(manifest["exit_code"], expected_code)
                self.assertTrue(manifest["cleanup"]["framework_closed"])
                self.assertTrue(manifest["cleanup"]["registry_closed"])
                self.assertTrue(manifest["cleanup"]["succeeded"])
                self.assertTrue(manifest["cleanup"]["ray_disconnected"])
                logs = self.client.logs(submission_id)
                self.assertNotIn("intentional P7.2 fixture failure", logs)
                self.assertTrue(self.client.delete(submission_id))
                self.created_ids.remove(submission_id)

    def test_service_stop_closes_executor_owned_actor_and_inflight_task(self) -> None:
        submission_id = self._new_submission_id("stop")
        self._submit(submission_id, "wait_for_service_stop")
        self._wait_for_log(submission_id, "P72_DRIVER_READY_FOR_STOP=1")

        self.assertTrue(self.client.stop(submission_id))
        status = self._wait_for_status(
            submission_id,
            {RayJobStatus.STOPPED, RayJobStatus.FAILED},
        )

        self.assertEqual(status, RayJobStatus.STOPPED)
        manifest = self._wait_for_manifest(submission_id)
        self.assertEqual(manifest["status"], "stop_requested")
        self.assertEqual(manifest["exit_code"], 143)
        self.assertTrue(manifest["cleanup"]["framework_closed"])
        self.assertTrue(manifest["cleanup"]["registry_closed"])
        self.assertTrue(manifest["cleanup"]["succeeded"])
        self.assertTrue(self.client.delete(submission_id))
        self.created_ids.remove(submission_id)

    def test_job_continues_after_short_lived_submitter_exits(self) -> None:
        submission_id = self._new_submission_id("detached-submitter")
        process = multiprocessing.get_context("spawn").Process(
            target=_submit_from_short_lived_process,
            args=(_ADDRESS, submission_id, "finish_after_submitter_exits"),
        )
        process.start()
        process.join(timeout=30)
        self.assertFalse(process.is_alive())
        self.assertEqual(process.exitcode, 0)
        self.created_ids.append(submission_id)

        self._wait_for_log(submission_id, "P72_SHORT_LIVED_SUBMITTER_JOB_STARTED=1")
        status = self._wait_for_status(submission_id, {RayJobStatus.SUCCEEDED})

        self.assertEqual(status, RayJobStatus.SUCCEEDED)
        self.assertIn(
            "P72_SHORT_LIVED_SUBMITTER_JOB_FINISHED=1",
            self.client.logs(submission_id),
        )
        self.assertEqual(self._manifest(submission_id)["status"], "succeeded")
        self.assertTrue(self.client.delete(submission_id))
        self.created_ids.remove(submission_id)

    def _submit(self, submission_id: str, runner_name: str) -> None:
        handle = RayJobClient(_ADDRESS).submit(_driver_spec(submission_id, runner_name))
        self.created_ids.append(handle.submission_id)

    def _new_submission_id(self, suffix: str) -> str:
        return f"p72-{suffix}-{uuid.uuid4().hex[:10]}"

    def _manifest(self, submission_id: str) -> dict[str, object]:
        return json.loads(
            (_OUTPUT_ROOT / f"{submission_id}.manifest.json").read_text(encoding="utf-8")
        )

    def _wait_for_manifest(self, submission_id: str) -> dict[str, object]:
        path = _OUTPUT_ROOT / f"{submission_id}.manifest.json"
        deadline = time.monotonic() + _WAIT_SECONDS
        while time.monotonic() < deadline:
            if path.exists():
                manifest = json.loads(path.read_text(encoding="utf-8"))
                if manifest.get("status") != "starting":
                    return manifest
            time.sleep(0.1)
        self.fail(f"Driver manifest {path!s} did not reach a terminal state")

    def _wait_for_log(self, submission_id: str, marker: str) -> None:
        deadline = time.monotonic() + _WAIT_SECONDS
        while time.monotonic() < deadline:
            if marker in self.client.logs(submission_id):
                return
            status = self.client.status(submission_id)
            if status.is_terminal:
                self.fail(f"Job ended as {status.value!r} before log marker {marker!r}")
            time.sleep(0.1)
        self.fail(f"Job did not emit log marker {marker!r}")

    def _wait_for_status(
        self,
        submission_id: str,
        accepted: set[RayJobStatus],
    ) -> RayJobStatus:
        deadline = time.monotonic() + _WAIT_SECONDS
        status = self.client.status(submission_id)
        while status not in accepted and time.monotonic() < deadline:
            time.sleep(0.1)
            status = self.client.status(submission_id)
        if status not in accepted:
            self.fail(f"Job {submission_id!r} remained in {status.value!r}")
        return status


if __name__ == "__main__":
    unittest.main()
