"""Structured failures at the Ray Jobs service boundary."""

from __future__ import annotations

from pivotq._internal.errors import (
    ErrorCategory,
    RayQuantumError,
    RetryAdvice,
    SubmissionError,
)


class RayJobSubmissionError(SubmissionError):
    """Submission may have reached the Jobs service; reconcile by ID first."""

    code = "ray_job_submission_failed"


class RayJobServiceError(RayQuantumError):
    """A read-only or management request to the Jobs service failed."""

    category = ErrorCategory.UNAVAILABLE
    code = "ray_jobs_service_unavailable"
    default_retry_advice = RetryAdvice.SAFE


class RayJobStateError(RayQuantumError):
    """The requested operation is invalid for the observed Job state."""

    category = ErrorCategory.VALIDATION
    code = "invalid_ray_job_state"
    default_retry_advice = RetryAdvice.NEVER


__all__ = [
    "RayJobServiceError",
    "RayJobStateError",
    "RayJobSubmissionError",
]
