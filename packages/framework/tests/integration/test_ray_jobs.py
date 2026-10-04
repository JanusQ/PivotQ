"""Opt-in P7.1 smoke tests against an actual Ray Jobs service."""

from __future__ import annotations

import os
import sys
import time
import unittest
import uuid

from pivotq._internal.jobs import (
    RayJobClient,
    RayJobDriverResources,
    RayJobSpec,
    RayJobStatus,
)


_ENABLED = os.environ.get("RAY_QUANTUM_JOB_TEST") == "1"
_ADDRESS = os.environ.get("RAY_QUANTUM_JOBS_ADDRESS", "http://127.0.0.1:8265")
_WAIT_SECONDS = 30.0
_PYTHON = sys.executable


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


@unittest.skipUnless(_ENABLED, "set RAY_QUANTUM_JOB_TEST=1 for Ray Jobs smoke")
class RayJobsSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = RayJobClient(_ADDRESS)
        self.created_ids: list[str] = []

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

    def test_submit_status_logs_and_terminal_delete(self) -> None:
        submission_id = self._new_submission_id("success")
        handle = self.client.submit(
            RayJobSpec(
                submission_id,
                f'{_shell_quote(_PYTHON)} -c "print(\'p7-job-smoke\', flush=True)"',
                driver_resources=RayJobDriverResources(num_cpus=0.1),
            )
        )
        self.created_ids.append(handle.submission_id)

        status = self._wait_for_status(
            handle.submission_id,
            {RayJobStatus.SUCCEEDED, RayJobStatus.FAILED},
        )

        self.assertEqual(status, RayJobStatus.SUCCEEDED)
        self.assertIn("p7-job-smoke", self.client.logs(handle))
        self.assertTrue(self.client.delete(handle))
        self.created_ids.remove(handle.submission_id)

    def test_stop_running_job_and_delete_terminal_metadata(self) -> None:
        submission_id = self._new_submission_id("stop")
        handle = self.client.submit(
            RayJobSpec(
                submission_id,
                (
                    f'{_shell_quote(_PYTHON)} -c "import time; '
                    "print('p7-job-running', flush=True); time.sleep(60)\""
                ),
                driver_resources=RayJobDriverResources(num_cpus=0.1),
            )
        )
        self.created_ids.append(handle.submission_id)
        self._wait_for_status(handle.submission_id, {RayJobStatus.RUNNING})

        self.assertTrue(self.client.stop(handle))
        status = self._wait_for_status(
            handle.submission_id,
            {RayJobStatus.STOPPED, RayJobStatus.FAILED},
        )

        self.assertEqual(status, RayJobStatus.STOPPED)
        self.assertTrue(self.client.delete(handle))
        self.created_ids.remove(handle.submission_id)

    def _new_submission_id(self, suffix: str) -> str:
        return f"p7-{suffix}-{uuid.uuid4().hex[:12]}"

    def _wait_for_status(
        self,
        submission_id: str,
        accepted: set[RayJobStatus],
    ) -> RayJobStatus:
        deadline = time.monotonic() + _WAIT_SECONDS
        last_status = self.client.status(submission_id)
        while last_status not in accepted and time.monotonic() < deadline:
            time.sleep(0.1)
            last_status = self.client.status(submission_id)
        if last_status not in accepted:
            self.fail(
                f"job {submission_id!r} did not reach "
                f"{sorted(status.value for status in accepted)!r}; "
                f"last status was {last_status.value!r}"
            )
        return last_status


if __name__ == "__main__":
    unittest.main()
