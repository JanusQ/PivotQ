"""Structured, vendor-neutral errors and retry safety hints."""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCategory(str, Enum):
    """Stable error groups for API responses, metrics, and policies."""

    VALIDATION = "validation"
    UNAVAILABLE = "unavailable"
    SUBMISSION = "submission"
    EXECUTION = "execution"
    TIMEOUT = "timeout"
    CANCELLATION = "cancellation"
    RESULT_UNKNOWN = "result_unknown"
    INTERNAL = "internal"


class RetryAdvice(str, Enum):
    """Whether retrying can duplicate an external quantum job."""

    NEVER = "never"
    SAFE = "safe"
    RECONCILE_FIRST = "reconcile_first"


class SubmissionDisposition(str, Enum):
    """What is known about a failed submission attempt."""

    NOT_SUBMITTED = "not_submitted"
    ACCEPTED = "accepted"
    UNKNOWN = "unknown"


class RayQuantumError(Exception):
    """Base exception carrying stable machine-readable error information."""

    category = ErrorCategory.INTERNAL
    code = "internal_error"
    default_retry_advice = RetryAdvice.NEVER

    def __init__(
        self,
        message: str,
        *,
        device_id: str | None = None,
        framework_job_id: str | None = None,
        backend_job_id: str | None = None,
        backend_code: str | None = None,
    ) -> None:
        self.message = _require_text("message", message)
        self.device_id = _require_optional_text("device_id", device_id)
        self.framework_job_id = _require_optional_text("framework_job_id", framework_job_id)
        self.backend_job_id = _require_optional_text("backend_job_id", backend_job_id)
        self.backend_code = _require_optional_text("backend_code", backend_code)
        self._retry_advice = self.default_retry_advice
        super().__init__(self.message)

    @property
    def retry_advice(self) -> RetryAdvice:
        """Return the policy-owned retry hint; callers cannot override it."""

        return self._retry_advice

    def to_record(self, *, include_message: bool = False) -> dict[str, Any]:
        """Return a log/API record, omitting free-form text by default."""

        record: dict[str, Any] = {
            "code": self.code,
            "category": self.category.value,
            "retry_advice": self.retry_advice.value,
        }
        for key in (
            "device_id",
            "framework_job_id",
            "backend_job_id",
            "backend_code",
        ):
            value = getattr(self, key)
            if value is not None:
                record[key] = value
        if include_message:
            record["message"] = self.message
        return record

    def __reduce__(self) -> tuple[object, tuple[object, ...]]:
        """Preserve structured fields when an error crosses a process boundary."""

        return (_restore_error, (type(self), self.message, self._constructor_kwargs()))

    def _constructor_kwargs(self) -> dict[str, object]:
        return {
            key: value
            for key, value in {
                "device_id": self.device_id,
                "framework_job_id": self.framework_job_id,
                "backend_job_id": self.backend_job_id,
                "backend_code": self.backend_code,
            }.items()
            if value is not None
        }


class ValidationError(RayQuantumError):
    category = ErrorCategory.VALIDATION
    code = "invalid_request"
    default_retry_advice = RetryAdvice.NEVER


class UnavailableError(RayQuantumError):
    """Device/backend was unavailable before a job was accepted."""

    category = ErrorCategory.UNAVAILABLE
    code = "backend_unavailable"
    default_retry_advice = RetryAdvice.SAFE


class SubmissionError(RayQuantumError):
    category = ErrorCategory.SUBMISSION
    code = "submission_failed"

    def __init__(
        self,
        message: str,
        *,
        disposition: SubmissionDisposition,
        device_id: str | None = None,
        framework_job_id: str | None = None,
        backend_job_id: str | None = None,
        backend_code: str | None = None,
    ) -> None:
        if not isinstance(disposition, SubmissionDisposition):
            raise TypeError("disposition must be SubmissionDisposition")
        self.disposition = disposition
        retry_advice = (
            RetryAdvice.SAFE
            if disposition is SubmissionDisposition.NOT_SUBMITTED
            else RetryAdvice.RECONCILE_FIRST
        )
        super().__init__(
            message,
            device_id=device_id,
            framework_job_id=framework_job_id,
            backend_job_id=backend_job_id,
            backend_code=backend_code,
        )
        self._retry_advice = retry_advice

    def to_record(self, *, include_message: bool = False) -> dict[str, Any]:
        record = super().to_record(include_message=include_message)
        record["submission_disposition"] = self.disposition.value
        return record

    def _constructor_kwargs(self) -> dict[str, object]:
        return super()._constructor_kwargs() | {"disposition": self.disposition}


class ExecutionError(RayQuantumError):
    category = ErrorCategory.EXECUTION
    code = "execution_failed"
    default_retry_advice = RetryAdvice.RECONCILE_FIRST


class TimeoutError(RayQuantumError):
    """Conservative timeout: reconcile backend state before any retry."""

    category = ErrorCategory.TIMEOUT
    code = "operation_timed_out"
    default_retry_advice = RetryAdvice.RECONCILE_FIRST


class CancellationError(RayQuantumError):
    category = ErrorCategory.CANCELLATION
    code = "cancellation_failed"
    default_retry_advice = RetryAdvice.NEVER


class ResultUnknownError(RayQuantumError):
    category = ErrorCategory.RESULT_UNKNOWN
    code = "result_unknown"
    default_retry_advice = RetryAdvice.RECONCILE_FIRST


def _restore_error(
    error_type: type[RayQuantumError],
    message: str,
    keyword_arguments: dict[str, object],
) -> RayQuantumError:
    return error_type(message, **keyword_arguments)


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} must not be empty")
    if value != value.strip():
        raise ValueError(f"{name} must not have surrounding whitespace")
    return value


def _require_optional_text(name: str, value: object) -> str | None:
    if value is None:
        return None
    return _require_text(name, value)


__all__ = [
    "CancellationError",
    "ErrorCategory",
    "ExecutionError",
    "RayQuantumError",
    "ResultUnknownError",
    "RetryAdvice",
    "SubmissionDisposition",
    "SubmissionError",
    "TimeoutError",
    "UnavailableError",
    "ValidationError",
]
