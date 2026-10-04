"""Incremental, payload-free invocation lifecycle events (Trace schema v2)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any

from pivotq._internal.framework.models import (
    ComponentSpec,
    ExecutionMode,
    InvocationSpec,
    InvocationStatus,
    ResourceRequest,
)
from pivotq._internal.models import StringMetadata

from .trace import utc_now


TRACE_EVENT_SCHEMA_VERSION = 2
TRACE_EVENT_RECORD_TYPE = "invocation_lifecycle_event"
TRACE_EVENT_MANIFEST_TYPE = "invocation_event_stream_manifest"
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_EVENT_DOCUMENT_FIELDS = frozenset(
    {
        "schema_version",
        "record_type",
        "cursor",
        "run_id",
        "trace_id",
        "invocation_id",
        "component_id",
        "method",
        "event",
        "source",
        "occurred_at",
        "execution_mode",
        "requested_resources",
        "status",
        "backend",
        "dependencies",
        "phase",
        "aimd_step",
        "invocation_index",
        "execution_ids",
        "error_code",
        "duration_seconds",
        "trace_context",
    }
)


class TraceEventKind(str, Enum):
    """Lifecycle facts supported by the v2 event contract."""

    SUBMITTED = "submitted"
    SCHEDULED = "scheduled"
    STARTED = "started"
    FINISHED = "finished"
    RESULT_OBSERVED = "result_observed"
    PHASE_STARTED = "phase_started"
    PHASE_FINISHED = "phase_finished"


class TraceEventSource(str, Enum):
    """The framework boundary that directly observed an event."""

    DRIVER = "framework_driver"
    WORKER = "framework_worker"
    APPLICATION = "application"


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One immutable v2 event without business payload or free-form errors."""

    run_id: str
    trace_id: str
    invocation_id: str
    component_id: str
    method: str
    event: TraceEventKind
    source: TraceEventSource
    occurred_at: datetime
    execution_mode: ExecutionMode
    resources: ResourceRequest
    status: InvocationStatus
    backend: str
    dependencies: tuple[str, ...] = ()
    phase: str | None = None
    aimd_step: int | None = None
    invocation_index: int | None = None
    task_id: str | None = None
    actor_id: str | None = None
    node_id: str | None = None
    error_code: str | None = None
    duration_seconds: float | None = None
    trace_context: StringMetadata = field(default_factory=StringMetadata)
    schema_version: int = TRACE_EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "trace_id",
            "invocation_id",
            "component_id",
            "method",
            "backend",
        ):
            _require_text(name, getattr(self, name))
        if _IDENTIFIER_PATTERN.fullmatch(self.run_id) is None:
            raise ValueError("run_id must be a stable identifier of at most 128 characters")
        if not isinstance(self.event, TraceEventKind):
            raise TypeError("event must be a TraceEventKind")
        if not isinstance(self.source, TraceEventSource):
            raise TypeError("source must be a TraceEventSource")
        object.__setattr__(
            self,
            "occurred_at",
            _require_utc_datetime("occurred_at", self.occurred_at),
        )
        if not isinstance(self.execution_mode, ExecutionMode):
            raise TypeError("execution_mode must be an ExecutionMode")
        if not isinstance(self.resources, ResourceRequest):
            raise TypeError("resources must be a ResourceRequest")
        if not isinstance(self.status, InvocationStatus):
            raise TypeError("status must be an InvocationStatus")
        if not isinstance(self.dependencies, tuple) or not all(
            isinstance(item, str) and item for item in self.dependencies
        ):
            raise TypeError("dependencies must be a tuple of non-empty strings")
        for name in ("phase", "task_id", "actor_id", "node_id", "error_code"):
            value = getattr(self, name)
            if value is not None:
                _require_text(name, value)
        for name in ("aimd_step", "invocation_index"):
            value = getattr(self, name)
            if value is not None:
                _require_non_negative_int(name, value)
        if self.duration_seconds is not None:
            _require_non_negative_number(
                "duration_seconds",
                self.duration_seconds,
            )
        if not isinstance(self.trace_context, StringMetadata):
            raise TypeError("trace_context must be a StringMetadata")
        _validate_event_status(self.event, self.status, self.error_code)
        if self.event in {
            TraceEventKind.PHASE_STARTED,
            TraceEventKind.PHASE_FINISHED,
        } and self.phase is None:
            raise ValueError("phase events require phase")
        if self.schema_version != TRACE_EVENT_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {TRACE_EVENT_SCHEMA_VERSION}"
            )

    @property
    def deduplication_key(self) -> tuple[object, ...]:
        """Return the stable identity used by append/recovery paths."""

        return (
            self.run_id,
            self.trace_id,
            self.invocation_id,
            self.event.value,
            self.phase,
            self.aimd_step,
            self.invocation_index,
        )

    def as_dict(self, *, cursor: int) -> dict[str, Any]:
        """Return one cursor-bearing JSON-ready event record."""

        _require_positive_int("cursor", cursor)
        return {
            "schema_version": self.schema_version,
            "record_type": TRACE_EVENT_RECORD_TYPE,
            "cursor": cursor,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "invocation_id": self.invocation_id,
            "component_id": self.component_id,
            "method": self.method,
            "event": self.event.value,
            "source": self.source.value,
            "occurred_at": _format_datetime(self.occurred_at),
            "execution_mode": self.execution_mode.value,
            "requested_resources": {
                "num_cpus": self.resources.num_cpus,
                "num_gpus": self.resources.num_gpus,
                "custom_resources": self.resources.custom_resources_dict(),
            },
            "status": self.status.value,
            "backend": self.backend,
            "dependencies": list(self.dependencies),
            "phase": self.phase,
            "aimd_step": self.aimd_step,
            "invocation_index": self.invocation_index,
            "execution_ids": {
                "task_id": self.task_id,
                "actor_id": self.actor_id,
                "node_id": self.node_id,
            },
            "error_code": self.error_code,
            "duration_seconds": self.duration_seconds,
            "trace_context": self.trace_context.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class TraceEventJournalConfig:
    """Serializable configuration for one Head-local append-only event stream."""

    run_id: str
    event_path: str | os.PathLike[str]
    manifest_path: str | os.PathLike[str]
    max_records: int = 100_000
    schema_version: int = TRACE_EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        run_id = _require_text("run_id", self.run_id)
        if _IDENTIFIER_PATTERN.fullmatch(run_id) is None:
            raise ValueError("run_id must be a stable identifier of at most 128 characters")
        event_path = _require_absolute_path("event_path", self.event_path)
        manifest_path = _require_absolute_path("manifest_path", self.manifest_path)
        if event_path == manifest_path:
            raise ValueError("event_path and manifest_path must be different")
        if event_path.parent != manifest_path.parent:
            raise ValueError("event_path and manifest_path must share one directory")
        object.__setattr__(self, "event_path", str(event_path))
        object.__setattr__(self, "manifest_path", str(manifest_path))
        object.__setattr__(
            self,
            "max_records",
            _require_positive_int("max_records", self.max_records),
        )
        if self.schema_version != TRACE_EVENT_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {TRACE_EVENT_SCHEMA_VERSION}"
            )


class TraceEventJournal:
    """Crash-visible JSONL journal with cursor, truncation, and digest evidence."""

    def __init__(self, config: TraceEventJournalConfig) -> None:
        if not isinstance(config, TraceEventJournalConfig):
            raise TypeError("config must be a TraceEventJournalConfig")
        self._config = config
        self._event_path = Path(config.event_path)
        self._manifest_path = Path(config.manifest_path)
        if not self._event_path.parent.is_dir():
            raise FileNotFoundError(
                f"trace event directory does not exist: {self._event_path.parent}"
            )
        self._lock = RLock()
        self._records: list[dict[str, Any]] = []
        self._cursors_by_key: dict[tuple[object, ...], int] = {}
        self._dropped_records = 0
        self._complete = False
        self._created_at = _format_datetime(utc_now())
        self._digest = hashlib.sha256()
        self._size_bytes = 0
        self._recovered = False
        self._open_or_recover()
        self._write_manifest()

    @property
    def config(self) -> TraceEventJournalConfig:
        return self._config

    @property
    def record_count(self) -> int:
        with self._lock:
            return len(self._records)

    @property
    def dropped_records(self) -> int:
        with self._lock:
            return self._dropped_records

    @property
    def complete(self) -> bool:
        with self._lock:
            return self._complete

    def record(self, event: TraceEvent) -> int | None:
        """Append one event, returning its cursor or ``None`` after truncation."""

        if not isinstance(event, TraceEvent):
            raise TypeError("event must be a TraceEvent")
        if event.run_id != self._config.run_id:
            raise ValueError("event run_id must match the journal run_id")
        with self._lock:
            if self._complete:
                raise RuntimeError("trace event journal is already complete")
            existing = self._cursors_by_key.get(event.deduplication_key)
            if existing is not None:
                self._write_manifest()
                return existing
            if len(self._records) >= self._config.max_records:
                self._dropped_records += 1
                self._write_manifest()
                return None
            cursor = len(self._records) + 1
            document = event.as_dict(cursor=cursor)
            encoded = (
                json.dumps(
                    document,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            )
            with self._event_path.open("ab", buffering=0) as stream:
                written = stream.write(encoded)
            if written != len(encoded):
                raise OSError("trace event journal append was incomplete")
            self._digest.update(encoded)
            self._size_bytes += len(encoded)
            self._records.append(document)
            self._cursors_by_key[event.deduplication_key] = cursor
            self._write_manifest()
            return cursor

    def snapshot(
        self,
        *,
        after_cursor: int = 0,
        limit: int = 1_000,
    ) -> tuple[dict[str, Any], ...]:
        """Return bounded copied records after one exclusive cursor."""

        _require_non_negative_int("after_cursor", after_cursor)
        _require_positive_int("limit", limit)
        with self._lock:
            selected = self._records[after_cursor : after_cursor + limit]
            return tuple(deepcopy(record) for record in selected)

    def manifest(self) -> dict[str, Any]:
        """Return the current stream manifest as a detached dictionary."""

        with self._lock:
            return deepcopy(self._manifest_document())

    def finalize(self) -> dict[str, Any]:
        """Mark normal producer completion and fsync the append-only stream."""

        with self._lock:
            if not self._complete:
                with self._event_path.open("ab", buffering=0) as stream:
                    os.fsync(stream.fileno())
                self._complete = True
                self._write_manifest()
            return deepcopy(self._manifest_document())

    def _open_or_recover(self) -> None:
        if not self._event_path.exists():
            with self._event_path.open("xb"):
                pass
            return
        data = self._event_path.read_bytes()
        if data and not data.endswith(b"\n"):
            raise ValueError("trace event journal has an incomplete trailing record")
        self._recovered = bool(data)
        self._digest.update(data)
        self._size_bytes = len(data)
        for expected_cursor, raw_line in enumerate(data.splitlines(), start=1):
            try:
                document = json.loads(raw_line)
            except (TypeError, ValueError):
                raise ValueError("trace event journal contains invalid JSON") from None
            _validate_recovered_document(
                document,
                run_id=self._config.run_id,
                expected_cursor=expected_cursor,
            )
            key = _document_key(document)
            if key in self._cursors_by_key:
                raise ValueError("trace event journal contains a duplicate event")
            self._records.append(document)
            self._cursors_by_key[key] = expected_cursor
        if len(self._records) > self._config.max_records:
            raise ValueError("trace event journal exceeds configured max_records")
        if self._manifest_path.exists():
            try:
                manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError):
                raise ValueError("trace event manifest is invalid") from None
            if manifest.get("schema_version") != TRACE_EVENT_SCHEMA_VERSION:
                raise ValueError("trace event manifest schema_version is invalid")
            if manifest.get("run_id") != self._config.run_id:
                raise ValueError("trace event manifest run_id is invalid")
            if manifest.get("record_type") != TRACE_EVENT_MANIFEST_TYPE:
                raise ValueError("trace event manifest record_type is invalid")
            if manifest.get("record_count") != len(self._records):
                raise ValueError("trace event manifest record_count is invalid")
            if manifest.get("last_cursor") != len(self._records):
                raise ValueError("trace event manifest last_cursor is invalid")
            if manifest.get("max_records") != self._config.max_records:
                raise ValueError("trace event manifest max_records is invalid")
            stream = manifest.get("stream")
            if not isinstance(stream, dict):
                raise ValueError("trace event manifest stream is invalid")
            if stream.get("file_name") != self._event_path.name:
                raise ValueError("trace event manifest file_name is invalid")
            if stream.get("size_bytes") != self._size_bytes:
                raise ValueError("trace event manifest size_bytes is invalid")
            if stream.get("sha256") != self._digest.hexdigest():
                raise ValueError("trace event manifest sha256 is invalid")
            dropped = manifest.get("dropped_count", 0)
            self._dropped_records = _require_non_negative_int(
                "manifest dropped_count",
                dropped,
            )
            complete = manifest.get("complete")
            if not isinstance(complete, bool):
                raise ValueError("trace event manifest complete is invalid")
            truncated = manifest.get("truncated")
            if not isinstance(truncated, bool):
                raise ValueError("trace event manifest truncated is invalid")
            if truncated != (self._dropped_records > 0):
                raise ValueError("trace event manifest truncated is inconsistent")
            self._complete = complete
            created_at = manifest.get("created_at")
            if isinstance(created_at, str) and created_at:
                self._created_at = created_at

    def _manifest_document(self) -> dict[str, Any]:
        record_count = len(self._records)
        return {
            "schema_version": TRACE_EVENT_SCHEMA_VERSION,
            "record_type": TRACE_EVENT_MANIFEST_TYPE,
            "run_id": self._config.run_id,
            "created_at": self._created_at,
            "generated_at": _format_datetime(utc_now()),
            "record_count": record_count,
            "last_cursor": record_count,
            "max_records": self._config.max_records,
            "dropped_count": self._dropped_records,
            "truncated": self._dropped_records > 0,
            "complete": self._complete,
            "recovered": self._recovered,
            "stream": {
                "file_name": self._event_path.name,
                "size_bytes": self._size_bytes,
                "sha256": self._digest.hexdigest(),
            },
        }

    def _write_manifest(self) -> None:
        document = self._manifest_document()
        temporary = self._manifest_path.with_name(
            f".{self._manifest_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(
                    document,
                    stream,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._manifest_path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def build_trace_event(
    invocation: InvocationSpec,
    component: ComponentSpec,
    *,
    event: TraceEventKind,
    source: TraceEventSource,
    status: InvocationStatus,
    backend: str,
    occurred_at: datetime | None = None,
    task_id: str | None = None,
    actor_id: str | None = None,
    node_id: str | None = None,
    error_code: str | None = None,
    duration_seconds: float | None = None,
    run_id: str | None = None,
) -> TraceEvent:
    """Build a v2 event without inferring application-specific semantics."""

    if not isinstance(invocation, InvocationSpec):
        raise TypeError("invocation must be an InvocationSpec")
    if not isinstance(component, ComponentSpec):
        raise TypeError("component must be a ComponentSpec")
    context = invocation.trace_context.as_dict()
    trace_id = context.get("trace_id", invocation.invocation_id)
    resolved_run_id = context.get("run_id", trace_id) if run_id is None else run_id
    phase = context.get("phase")
    return TraceEvent(
        run_id=resolved_run_id,
        trace_id=trace_id,
        invocation_id=invocation.invocation_id,
        component_id=invocation.component_id,
        method=invocation.method,
        event=event,
        source=source,
        occurred_at=utc_now() if occurred_at is None else occurred_at,
        execution_mode=component.execution,
        resources=component.resources,
        status=status,
        backend=backend,
        dependencies=invocation.dependencies,
        phase=phase,
        aimd_step=_context_non_negative_int(context, "aimd_step"),
        invocation_index=_context_non_negative_int(context, "invocation_index"),
        task_id=task_id,
        actor_id=actor_id,
        node_id=node_id,
        error_code=error_code,
        duration_seconds=duration_seconds,
        trace_context=invocation.trace_context,
    )


def _context_non_negative_int(
    context: dict[str, str],
    name: str,
) -> int | None:
    value = context.get(name)
    if value is None:
        return None
    if not value.isdecimal():
        raise ValueError(f"trace_context {name} must be a non-negative integer")
    return _require_non_negative_int(name, int(value))


def _validate_event_status(
    event: TraceEventKind,
    status: InvocationStatus,
    error_code: str | None,
) -> None:
    if event in {TraceEventKind.SUBMITTED, TraceEventKind.SCHEDULED}:
        expected = InvocationStatus.QUEUED
        if status is not expected:
            raise ValueError(f"{event.value} events require queued status")
    elif event in {
        TraceEventKind.STARTED,
        TraceEventKind.PHASE_STARTED,
        TraceEventKind.PHASE_FINISHED,
    }:
        if status is not InvocationStatus.RUNNING:
            raise ValueError(f"{event.value} events require running status")
    elif not status.is_terminal:
        raise ValueError(f"{event.value} events require a terminal status")
    if status is InvocationStatus.SUCCEEDED and error_code is not None:
        raise ValueError("successful events must not contain error_code")
    if status in {
        InvocationStatus.FAILED,
        InvocationStatus.CANCELLED,
        InvocationStatus.TIMED_OUT,
    } and error_code is None:
        raise ValueError("unsuccessful terminal events require error_code")
    if not status.is_terminal and error_code is not None:
        raise ValueError("non-terminal events must not contain error_code")


def _validate_recovered_document(
    document: object,
    *,
    run_id: str,
    expected_cursor: int,
) -> None:
    if not isinstance(document, dict):
        raise ValueError("trace event journal records must be JSON objects")
    if document.get("schema_version") != TRACE_EVENT_SCHEMA_VERSION:
        raise ValueError("trace event journal schema_version is invalid")
    if document.get("record_type") != TRACE_EVENT_RECORD_TYPE:
        raise ValueError("trace event journal record_type is invalid")
    if document.get("run_id") != run_id:
        raise ValueError("trace event journal run_id is invalid")
    if document.get("cursor") != expected_cursor:
        raise ValueError("trace event journal cursor sequence is invalid")
    if set(document) != _EVENT_DOCUMENT_FIELDS:
        raise ValueError("trace event journal record fields are invalid")
    try:
        requested_resources = document["requested_resources"]
        execution_ids = document["execution_ids"]
        trace_context = document["trace_context"]
        dependencies = document["dependencies"]
        if not isinstance(requested_resources, dict) or set(requested_resources) != {
            "num_cpus",
            "num_gpus",
            "custom_resources",
        }:
            raise ValueError
        if not isinstance(execution_ids, dict) or set(execution_ids) != {
            "task_id",
            "actor_id",
            "node_id",
        }:
            raise ValueError
        if not isinstance(trace_context, dict):
            raise ValueError
        if not isinstance(dependencies, list):
            raise ValueError
        recovered = TraceEvent(
            run_id=document["run_id"],
            trace_id=document["trace_id"],
            invocation_id=document["invocation_id"],
            component_id=document["component_id"],
            method=document["method"],
            event=TraceEventKind(document["event"]),
            source=TraceEventSource(document["source"]),
            occurred_at=_parse_utc_text(
                "trace event journal occurred_at",
                document["occurred_at"],
            ),
            execution_mode=ExecutionMode(document["execution_mode"]),
            resources=ResourceRequest(
                num_cpus=requested_resources["num_cpus"],
                num_gpus=requested_resources["num_gpus"],
                custom_resources=requested_resources["custom_resources"],
            ),
            status=InvocationStatus(document["status"]),
            backend=document["backend"],
            dependencies=tuple(dependencies),
            phase=document["phase"],
            aimd_step=document["aimd_step"],
            invocation_index=document["invocation_index"],
            task_id=execution_ids["task_id"],
            actor_id=execution_ids["actor_id"],
            node_id=execution_ids["node_id"],
            error_code=document["error_code"],
            duration_seconds=document["duration_seconds"],
            trace_context=StringMetadata.from_mapping(trace_context),
        )
    except (KeyError, TypeError, ValueError):
        raise ValueError("trace event journal record is invalid") from None
    if recovered.deduplication_key != _document_key(document):
        raise ValueError("trace event journal identity is invalid")


def _document_key(document: dict[str, Any]) -> tuple[object, ...]:
    return (
        document.get("run_id"),
        document.get("trace_id"),
        document.get("invocation_id"),
        document.get("event"),
        document.get("phase"),
        document.get("aimd_step"),
        document.get("invocation_index"),
    )


def _require_absolute_path(name: str, value: object) -> Path:
    try:
        path = Path(value)  # type: ignore[arg-type]
    except TypeError:
        raise TypeError(f"{name} must be a path") from None
    if "\x00" in str(path):
        raise ValueError(f"{name} must not contain NUL")
    if not path.is_absolute():
        raise ValueError(f"{name} must be absolute")
    return path.resolve(strict=False)


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


def _require_non_negative_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    normalized = float(value)
    if normalized < 0 or normalized == float("inf") or normalized != normalized:
        raise ValueError(f"{name} must be finite and non-negative")
    return normalized


def _require_utc_datetime(name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return value.astimezone(timezone.utc)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc_text(name: str, value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{name} must be an RFC 3339 UTC string")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        raise ValueError(f"{name} must be an RFC 3339 UTC string") from None
    return _require_utc_datetime(name, parsed)


__all__ = [
    "TRACE_EVENT_MANIFEST_TYPE",
    "TRACE_EVENT_RECORD_TYPE",
    "TRACE_EVENT_SCHEMA_VERSION",
    "TraceEvent",
    "TraceEventJournal",
    "TraceEventJournalConfig",
    "TraceEventKind",
    "TraceEventSource",
    "build_trace_event",
]
