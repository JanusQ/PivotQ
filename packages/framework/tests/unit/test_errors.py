"""Unit tests for structured error and retry semantics."""

from __future__ import annotations

import pickle
import unittest

from pivotq._internal.errors import (
    CancellationError,
    ErrorCategory,
    ExecutionError,
    RayQuantumError,
    ResultUnknownError,
    RetryAdvice,
    SubmissionDisposition,
    SubmissionError,
    TimeoutError,
    UnavailableError,
    ValidationError,
)


class ErrorRecordTest(unittest.TestCase):
    def test_record_omits_free_form_message_by_default(self) -> None:
        error = ValidationError(
            "program contains a secret-like value",
            framework_job_id="job-01",
            backend_code="INVALID_IR",
        )

        self.assertEqual(
            error.to_record(),
            {
                "code": "invalid_request",
                "category": "validation",
                "retry_advice": "never",
                "framework_job_id": "job-01",
                "backend_code": "INVALID_IR",
            },
        )
        self.assertEqual(error.to_record(include_message=True)["message"], error.message)
        self.assertEqual(str(error), error.message)

    def test_errors_share_a_catchable_base_type(self) -> None:
        with self.assertRaises(RayQuantumError):
            raise ResultUnknownError("backend result cannot be confirmed")

    def test_structured_fields_survive_process_serialization(self) -> None:
        errors = [
            ValidationError("invalid", device_id="qpu-01", backend_code="INVALID_IR"),
            SubmissionError(
                "response lost",
                disposition=SubmissionDisposition.UNKNOWN,
                framework_job_id="job-01",
            ),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                restored = pickle.loads(pickle.dumps(error))
                self.assertIs(type(restored), type(error))
                self.assertEqual(restored.to_record(include_message=True), error.to_record(include_message=True))

    def test_invalid_error_fields_are_rejected(self) -> None:
        invalid_calls = [
            lambda: ValidationError(""),
            lambda: ValidationError(" padded "),
            lambda: ValidationError("invalid", device_id=" qpu-01"),
            lambda: ValidationError("invalid", retry_advice="safe"),
        ]
        for call in invalid_calls:
            with self.subTest(call=call), self.assertRaises((TypeError, ValueError)):
                call()

        error = ExecutionError("failed")
        with self.assertRaises(AttributeError):
            error.retry_advice = RetryAdvice.SAFE  # type: ignore[misc]


class RetrySemanticsTest(unittest.TestCase):
    def test_fixed_error_retry_advice_is_conservative(self) -> None:
        cases = [
            (ValidationError("invalid"), ErrorCategory.VALIDATION, RetryAdvice.NEVER),
            (UnavailableError("offline"), ErrorCategory.UNAVAILABLE, RetryAdvice.SAFE),
            (ExecutionError("failed"), ErrorCategory.EXECUTION, RetryAdvice.RECONCILE_FIRST),
            (TimeoutError("timed out"), ErrorCategory.TIMEOUT, RetryAdvice.RECONCILE_FIRST),
            (CancellationError("too late"), ErrorCategory.CANCELLATION, RetryAdvice.NEVER),
            (ResultUnknownError("unknown"), ErrorCategory.RESULT_UNKNOWN, RetryAdvice.RECONCILE_FIRST),
        ]
        for error, category, advice in cases:
            with self.subTest(error=type(error).__name__):
                self.assertEqual(error.category, category)
                self.assertEqual(error.retry_advice, advice)

    def test_submission_disposition_controls_retry_safety(self) -> None:
        expected = {
            SubmissionDisposition.NOT_SUBMITTED: RetryAdvice.SAFE,
            SubmissionDisposition.ACCEPTED: RetryAdvice.RECONCILE_FIRST,
            SubmissionDisposition.UNKNOWN: RetryAdvice.RECONCILE_FIRST,
        }
        for disposition, advice in expected.items():
            with self.subTest(disposition=disposition):
                error = SubmissionError(
                    "submission failed",
                    disposition=disposition,
                    framework_job_id="job-01",
                )
                self.assertEqual(error.retry_advice, advice)
                self.assertEqual(error.to_record()["submission_disposition"], disposition.value)

    def test_submission_disposition_is_required_and_typed(self) -> None:
        with self.assertRaises(TypeError):
            SubmissionError("submission failed", disposition="unknown")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
