"""Executor contract shared by local and future Ray implementations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
import math

from pivotq._internal.framework.models import (
    InvocationHandle,
    InvocationResult,
    InvocationSpec,
)
from pivotq._internal.framework.registry import ComponentRegistry


@runtime_checkable
class Executor(Protocol):
    """Submit, resolve, invoke, release, and close component calls."""

    @property
    def closed(self) -> bool:
        """Whether this executor permanently rejects new submissions."""

        ...

    @property
    def registry(self) -> ComponentRegistry:
        """Registry used for validation and component construction."""

        ...

    def submit(self, invocation: InvocationSpec) -> InvocationHandle:
        """Submit one invocation and return an executor-neutral handle."""

        ...

    def result(self, handle: InvocationHandle) -> InvocationResult:
        """Wait for and return one terminal invocation result."""

        ...

    def poll(self, handle: InvocationHandle) -> InvocationResult | None:
        """Return a ready terminal result, or None without waiting."""
        ...

    def wait(self, handles: tuple[InvocationHandle, ...], *, num_returns: int = 1,
             timeout: float | None = None) -> tuple[tuple[InvocationHandle, ...], tuple[InvocationHandle, ...]]:
        """Wait for terminal handles without raising their business errors."""
        ...

    def invoke(self, invocation: InvocationSpec) -> InvocationResult:
        """Submit and synchronously resolve one invocation."""

        ...

    def release(self, handle: InvocationHandle) -> None:
        """Release a completed result retained by this executor."""

        ...

    def close(self) -> None:
        """Stop accepting work and release executor-owned resources."""

        ...


__all__ = ["Executor"]


def validate_wait(handles: tuple[InvocationHandle, ...], num_returns: int,
                  timeout: float | None) -> None:
    if not isinstance(handles, tuple) or not all(isinstance(item, InvocationHandle) for item in handles):
        raise TypeError("handles must be a tuple of InvocationHandle")
    if len({item.invocation_id for item in handles}) != len(handles):
        raise ValueError("wait does not accept duplicate references")
    if isinstance(num_returns, bool) or not isinstance(num_returns, int) or num_returns < 1:
        raise ValueError("num_returns must be a positive integer")
    if handles and num_returns > len(handles):
        raise ValueError("num_returns cannot exceed the number of references")
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                                or not math.isfinite(timeout) or timeout < 0):
        raise ValueError("timeout must be a finite nonnegative number or None")
