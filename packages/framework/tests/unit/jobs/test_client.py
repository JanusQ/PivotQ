"""Unit tests for the narrow Ray Jobs SDK wrapper."""

from __future__ import annotations

from enum import Enum
import unittest

from pivotq._internal.jobs import (
    RayJobClient,
    RayJobDriverResources,
    RayJobRuntimeEnvironment,
    RayJobServiceError,
    RayJobSpec,
    RayJobStateError,
    RayJobStatus,
    RayJobSubmissionError,
)
from pivotq._internal.errors import RetryAdvice, SubmissionDisposition


class _SdkStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"


class _FakeJobsClient:
    def __init__(self) -> None:
        self.submit_arguments: dict[str, object] | None = None
        self.status_value: object = "RUNNING"
        self.logs_value: object = "driver output\n"
        self.stop_value: object = True
        self.delete_value: object = True
        self.submit_error: Exception | None = None
        self.operation_error: Exception | None = None
        self.deleted_ids: list[str] = []

    def submit_job(self, **kwargs: object) -> str:
        if self.submit_error is not None:
            raise self.submit_error
        self.submit_arguments = dict(kwargs)
        return str(kwargs["submission_id"])

    def get_job_status(self, job_id: str) -> object:
        if self.operation_error is not None:
            raise self.operation_error
        return self.status_value

    def get_job_logs(self, job_id: str) -> object:
        if self.operation_error is not None:
            raise self.operation_error
        return self.logs_value

    def stop_job(self, job_id: str) -> object:
        if self.operation_error is not None:
            raise self.operation_error
        return self.stop_value

    def delete_job(self, job_id: str) -> object:
        if self.operation_error is not None:
            raise self.operation_error
        self.deleted_ids.append(job_id)
        return self.delete_value


class RayJobClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = _FakeJobsClient()
        self.factory_arguments: dict[str, object] = {}

        def factory(address: str, **kwargs: object) -> _FakeJobsClient:
            self.factory_arguments = {"address": address, **kwargs}
            return self.fake

        self.client = RayJobClient(
            "http://127.0.0.1:8265",
            headers={"Authorization": "Bearer secret-token"},
            client_factory=factory,
        )

    def test_submit_maps_exact_ray_290_arguments(self) -> None:
        spec = RayJobSpec(
            "run-001",
            "python run.py",
            runtime_environment=RayJobRuntimeEnvironment(
                working_dir=".",
                env_vars={"MODE": "test"},
            ),
            metadata={"owner": "framework"},
            driver_resources=RayJobDriverResources(
                num_cpus=1,
                num_gpus=0,
                memory_bytes=2048,
                custom_resources={"driver_slot": 1},
            ),
        )

        handle = self.client.submit(spec)

        self.assertEqual(handle.submission_id, "run-001")
        self.assertEqual(
            self.fake.submit_arguments,
            {
                "entrypoint": "python run.py",
                "submission_id": "run-001",
                "runtime_env": {
                    "working_dir": ".",
                    "env_vars": {"MODE": "test"},
                },
                "metadata": {"owner": "framework"},
                "entrypoint_num_cpus": 1.0,
                "entrypoint_num_gpus": 0.0,
                "entrypoint_memory": 2048,
                "entrypoint_resources": {"driver_slot": 1.0},
            },
        )
        self.assertEqual(self.factory_arguments["address"], "http://127.0.0.1:8265")
        self.assertNotIn("secret-token", repr(self.client))

    def test_status_logs_stop_and_terminal_delete(self) -> None:
        self.fake.status_value = _SdkStatus.SUCCEEDED

        self.assertEqual(self.client.status("run-001"), RayJobStatus.SUCCEEDED)
        self.assertEqual(self.client.logs("run-001"), "driver output\n")
        self.assertTrue(self.client.stop("run-001"))
        self.assertTrue(self.client.delete("run-001"))
        self.assertEqual(self.fake.deleted_ids, ["run-001"])

    def test_delete_rejects_nonterminal_job_without_calling_sdk_delete(self) -> None:
        self.fake.status_value = "RUNNING"

        with self.assertRaises(RayJobStateError) as captured:
            self.client.delete("run-001")

        self.assertEqual(captured.exception.code, "invalid_ray_job_state")
        self.assertEqual(self.fake.deleted_ids, [])

    def test_duplicate_or_uncertain_submission_is_structured_and_redacted(self) -> None:
        self.fake.submit_error = RuntimeError(
            "duplicate submission run-001 secret-token"
        )

        with self.assertRaises(RayJobSubmissionError) as captured:
            self.client.submit(RayJobSpec("run-001", "python run.py secret-token"))

        error = captured.exception
        self.assertEqual(error.disposition, SubmissionDisposition.UNKNOWN)
        self.assertEqual(error.retry_advice, RetryAdvice.RECONCILE_FIRST)
        self.assertNotIn("secret-token", str(error))
        self.assertNotIn("secret-token", str(error.to_record(include_message=True)))

    def test_service_failures_and_invalid_responses_are_structured(self) -> None:
        self.fake.operation_error = RuntimeError("connection refused secret-token")
        for operation in (
            lambda: self.client.status("run-001"),
            lambda: self.client.logs("run-001"),
            lambda: self.client.stop("run-001"),
        ):
            with self.subTest(operation=operation), self.assertRaises(
                RayJobServiceError
            ) as captured:
                operation()
            self.assertNotIn("secret-token", str(captured.exception))

        self.fake.operation_error = None
        invalid_responses = [
            ("status_value", "UNRECOGNIZED", lambda: self.client.status("run-001")),
            ("logs_value", b"logs", lambda: self.client.logs("run-001")),
            ("stop_value", 1, lambda: self.client.stop("run-001")),
        ]
        for attribute, value, operation in invalid_responses:
            with self.subTest(attribute=attribute):
                setattr(self.fake, attribute, value)
                with self.assertRaises(RayJobServiceError):
                    operation()
                setattr(
                    self.fake,
                    attribute,
                    {"status_value": "RUNNING", "logs_value": "logs", "stop_value": True}[attribute],
                )

    def test_address_and_tls_boundaries_are_enforced(self) -> None:
        def factory(address: str, **kwargs: object) -> _FakeJobsClient:
            return self.fake

        accepted = [
            "http://localhost:8265",
            "http://10.0.1.7:8265",
            "https://jobs.example.test:8265",
        ]
        for address in accepted:
            with self.subTest(address=address):
                RayJobClient(address, client_factory=factory)

        rejected = [
            "ray://10.0.1.7:10001",
            "http://public.example.test:8265",
            "https://user:secret@jobs.example.test:8265",
            "https://jobs.example.test:8265/api/jobs",
            "https://jobs.example.test:8265?",
            "https://jobs.example.test:0",
            "http://127.0.0.1:8265\nignored",
        ]
        for address in rejected:
            with self.subTest(address=address), self.assertRaises(ValueError):
                RayJobClient(address, client_factory=factory)

        with self.assertRaises(ValueError):
            RayJobClient(
                "https://jobs.example.test:8265",
                verify=False,
                client_factory=factory,
            )
        with self.assertRaises(ValueError):
            RayJobClient(
                "https://jobs.example.test:8265",
                headers={"Authorization": "Bearer value\r\nInjected: true"},
                client_factory=factory,
            )
        with self.assertRaises(ValueError):
            RayJobClient(
                "https://jobs.example.test:8265",
                cookies={"bad cookie": "value"},
                client_factory=factory,
            )


if __name__ == "__main__":
    unittest.main()
