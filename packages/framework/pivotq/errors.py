"""Public structured execution errors shared by PivotQ backends."""

from ._internal.errors import (
    CancellationError,
    ErrorCategory,
    ExecutionError,
    RayQuantumError as PivotQError,
    ResultUnknownError,
    RetryAdvice,
    SubmissionDisposition,
    SubmissionError,
    TimeoutError,
    UnavailableError,
    ValidationError,
)

__all__ = [
    "PivotQError", "ValidationError", "UnavailableError", "ExecutionError",
    "SubmissionError", "TimeoutError", "CancellationError", "ResultUnknownError",
    "ErrorCategory", "RetryAdvice", "SubmissionDisposition",
]
