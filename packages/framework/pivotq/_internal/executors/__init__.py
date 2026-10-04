"""Execution backends for framework component invocations."""

from __future__ import annotations

from typing import Any

from .base import Executor
from .local import LocalExecutor

__all__ = [
    "Executor",
    "LocalExecutor",
    "RayExecutor",
]


def __getattr__(name: str) -> Any:
    """Load the Ray-backed executor only when explicitly requested."""

    if name == "RayExecutor":
        from .ray import RayExecutor

        return RayExecutor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
