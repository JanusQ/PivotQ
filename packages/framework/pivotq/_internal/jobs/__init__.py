"""Ray Jobs application-submission contracts and client boundary.

Importing this package does not import Ray.  ``RayJobClient`` loads the pinned
``JobSubmissionClient`` only when an actual client instance is constructed.
"""

from __future__ import annotations

from typing import Any

from .client import JobSubmissionClientProtocol, RayJobClient
from .errors import RayJobServiceError, RayJobStateError, RayJobSubmissionError
from .models import (
    RayJobDriverResources,
    RayJobHandle,
    RayJobRuntimeEnvironment,
    RayJobSpec,
    RayJobStatus,
)

__all__ = [
    "JobSubmissionClientProtocol",
    "RayJobClient",
    "RayJobDriverResources",
    "RayJobDriverConfig",
    "RayJobDriverContext",
    "RayJobDriverManifest",
    "RayJobDriverStatus",
    "RayJobHandle",
    "RayJobRuntimeEnvironment",
    "RayJobServiceError",
    "RayJobSpec",
    "RayJobStateError",
    "RayJobStatus",
    "RayJobSubmissionError",
    "run_driver",
]


def __getattr__(name: str) -> Any:
    """Load Driver contracts lazily so ``python -m ...driver`` stays clean."""

    if name in {
        "RayJobDriverConfig",
        "RayJobDriverContext",
        "RayJobDriverManifest",
        "RayJobDriverStatus",
        "run_driver",
    }:
        from . import driver

        return getattr(driver, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
