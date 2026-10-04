"""Versioned invocation traces without business-payload capture."""

from __future__ import annotations

import pickle
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from pivotq._internal.framework.models import (
    ComponentSpec,
    ExecutionMode,
    InvocationResult,
    InvocationSpec,
    InvocationStatus,
    ResourceRequest,
)
from pivotq._internal.models import StringMetadata


TRACE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class TraceRecord:
    """One terminal framework invocation trace.

    Payload values are never retained.  Only serialized byte counts and
    caller-provided string trace metadata cross this boundary.
    """

    trace_id: str
    invocation_id: str
    component_id: str
    method: str
    dependencies: tuple[str, ...]
    execution_mode: ExecutionMode
    resources: ResourceRequest
    status: InvocationStatus
    backend: str
    submitted_at: datetime
    scheduled_at: datetime | None
    started_at: datetime | None
    finished_at: datetime
    result_observed_at: datetime | None
    queue_seconds: float | None
    execution_seconds: float | None
    transfer_seconds: float | None
    task_id: str | None
    actor_id: str | None
    node_id: str | None
    input_size_bytes: int
    output_size_bytes: int
    trace_context: StringMetadata = field(default_factory=StringMetadata)
    error_code: str | None = None
    schema_version: int = TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "trace_id",
            "invocation_id",
            "component_id",
            "method",
            "backend",
        ):
            _require_text(name, getattr(self, name))
        if not isinstance(self.dependencies, tuple) or not all(
            isinstance(item, str) and item for item in self.dependencies
        ):
            raise TypeError("dependencies must be a tuple of non-empty strings")
        if not isinstance(self.execution_mode, ExecutionMode):
            raise TypeError("execution_mode must be an ExecutionMode")
        if not isinstance(self.resources, ResourceRequest):
            raise TypeError("resources must be a ResourceRequest")
        if (
            not isinstance(self.status, InvocationStatus)
            or not self.status.is_terminal
        ):
            raise ValueError("status must be a terminal InvocationStatus")
        for name in (
            "submitted_at",
            "scheduled_at",
            "started_at",
            "finished_at",
            "result_observed_at",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _require_utc_datetime(name, value))
        for name in (
            "queue_seconds",
            "execution_seconds",
            "transfer_seconds",
        ):
            _require_optional_non_negative_number(name, getattr(self, name))
        for name in ("task_id", "actor_id", "node_id", "error_code"):
            value = getattr(self, name)
            if value is not None:
                _require_text(name, value)
        for name in ("input_size_bytes", "output_size_bytes"):
            _require_non_negative_int(name, getattr(self, name))
        if not isinstance(self.trace_context, StringMetadata):
            raise TypeError("trace_context must be a StringMetadata")
        if self.schema_version != TRACE_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {TRACE_SCHEMA_VERSION}"
            )

    def as_dict(self) -> dict[str, Any]:
        """Return a stable JSON-ready representation."""

        return {
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
            "invocation_id": self.invocation_id,
            "component_id": self.component_id,
            "method": self.method,
            "dependencies": list(self.dependencies),
            "execution_mode": self.execution_mode.value,
            "resources": {
                "num_cpus": self.resources.num_cpus,
                "num_gpus": self.resources.num_gpus,
                "custom_resources": self.resources.custom_resources_dict(),
            },
            "status": self.status.value,
            "backend": self.backend,
            "timestamps": {
                "submitted_at": _format_datetime(self.submitted_at),
                "scheduled_at": _format_datetime(self.scheduled_at),
                "started_at": _format_datetime(self.started_at),
                "finished_at": _format_datetime(self.finished_at),
                "result_observed_at": _format_datetime(
                    self.result_observed_at
                ),
            },
            "durations_seconds": {
                "queue": self.queue_seconds,
                "execution": self.execution_seconds,
                "transfer": self.transfer_seconds,
            },
            "execution_ids": {
                "task_id": self.task_id,
                "actor_id": self.actor_id,
                "node_id": self.node_id,
            },
            "sizes_bytes": {
                "input": self.input_size_bytes,
                "output": self.output_size_bytes,
            },
            "trace_context": self.trace_context.as_dict(),
            "error_code": self.error_code,
        }

    def observed(self, at: datetime | None = None) -> TraceRecord:
        """Return a copy carrying Driver observation latency."""

        observed_at = utc_now() if at is None else _require_utc_datetime("at", at)
        return replace(
            self,
            result_observed_at=observed_at,
            transfer_seconds=_elapsed(self.finished_at, observed_at),
        )


class TraceCollector:
    """Thread-safe bounded in-memory collection of terminal trace records."""

    def __init__(self, *, max_records: int = 10_000) -> None:
        self._max_records = _require_positive_int(
            "max_records",
            max_records,
        )
        self._records: OrderedDict[tuple[str, str], TraceRecord] = (
            OrderedDict()
        )
        self._dropped_records = 0
        self._lock = RLock()

    @property
    def max_records(self) -> int:
        return self._max_records

    @property
    def dropped_records(self) -> int:
        with self._lock:
            return self._dropped_records

    def record(self, trace: TraceRecord) -> None:
        """Store or replace one invocation trace without retaining payloads."""

        if not isinstance(trace, TraceRecord):
            raise TypeError("trace must be a TraceRecord")
        key = (trace.trace_id, trace.invocation_id)
        with self._lock:
            if key in self._records:
                self._records[key] = trace
                return
            if len(self._records) >= self._max_records:
                self._records.popitem(last=False)
                self._dropped_records += 1
            self._records[key] = trace

    def snapshot(self) -> tuple[TraceRecord, ...]:
        """Return an immutable arrival-ordered snapshot."""

        with self._lock:
            return tuple(self._records.values())

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._dropped_records = 0


def build_trace_record(
    invocation: InvocationSpec,
    component: ComponentSpec,
    result: InvocationResult,
    *,
    backend: str,
    submitted_at: datetime,
    scheduled_at: datetime | None,
    started_at: datetime | None,
    finished_at: datetime,
    result_observed_at: datetime | None = None,
    task_id: str | None = None,
    actor_id: str | None = None,
    node_id: str | None = None,
    input_size_bytes: int | None = None,
    output_size_bytes: int | None = None,
) -> TraceRecord:
    """Build a terminal record from framework-owned metadata only."""

    if not isinstance(invocation, InvocationSpec):
        raise TypeError("invocation must be an InvocationSpec")
    if not isinstance(component, ComponentSpec):
        raise TypeError("component must be a ComponentSpec")
    if not isinstance(result, InvocationResult):
        raise TypeError("result must be an InvocationResult")
    context = invocation.trace_context.as_dict()
    trace_id = context.get("trace_id", invocation.invocation_id)
    observed_at = (
        None
        if result_observed_at is None
        else _require_utc_datetime("result_observed_at", result_observed_at)
    )
    submitted_at = _require_utc_datetime("submitted_at", submitted_at)
    scheduled_at = (
        None
        if scheduled_at is None
        else _require_utc_datetime("scheduled_at", scheduled_at)
    )
    started_at = (
        None
        if started_at is None
        else _require_utc_datetime("started_at", started_at)
    )
    finished_at = _require_utc_datetime("finished_at", finished_at)
    return TraceRecord(
        trace_id=trace_id,
        invocation_id=invocation.invocation_id,
        component_id=invocation.component_id,
        method=invocation.method,
        dependencies=invocation.dependencies,
        execution_mode=component.execution,
        resources=component.resources,
        status=result.status,
        backend=backend,
        submitted_at=submitted_at,
        scheduled_at=scheduled_at,
        started_at=started_at,
        finished_at=finished_at,
        result_observed_at=observed_at,
        queue_seconds=_elapsed(submitted_at, scheduled_at),
        execution_seconds=_elapsed(started_at, finished_at),
        transfer_seconds=_elapsed(finished_at, observed_at),
        task_id=task_id,
        actor_id=actor_id,
        node_id=node_id,
        input_size_bytes=(
            serialized_size((invocation.args, invocation.kwargs))
            if input_size_bytes is None
            else input_size_bytes
        ),
        output_size_bytes=(
            serialized_size(result.value)
            if output_size_bytes is None
            else output_size_bytes
        ),
        trace_context=invocation.trace_context,
        error_code=None if result.error is None else result.error.code,
    )


def serialized_size(value: object) -> int:
    """Return standard-pickle byte size, or zero for an unavailable estimate."""

    try:
        return len(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
    except Exception:
        return 0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _elapsed(
    started_at: datetime | None,
    finished_at: datetime | None,
) -> float | None:
    if started_at is None or finished_at is None:
        return None
    return max(0.0, (finished_at - started_at).total_seconds())


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_utc_datetime(name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return value.astimezone(timezone.utc)


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or value != value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be non-empty normalized text")
    return value


def _require_positive_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _require_non_negative_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


def _require_optional_non_negative_number(
    name: str,
    value: object,
) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number or None")
    normalized = float(value)
    if normalized < 0 or normalized != normalized or normalized == float("inf"):
        raise ValueError(f"{name} must be finite and non-negative")


__all__ = [
    "TRACE_SCHEMA_VERSION",
    "TraceCollector",
    "TraceRecord",
    "build_trace_record",
    "serialized_size",
    "utc_now",
]
