"""Vendor-neutral domain models for quantum devices and jobs.

The models in this module intentionally depend only on the Python standard
library.  They define the stable boundary shared by future backends, the Ray
runtime, and user-facing adapters without choosing a quantum framework or
hardware vendor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Iterable, Mapping


class ConnectionMode(str, Enum):
    """How a runtime reaches a quantum device."""

    LOCAL = "local"
    REMOTE = "remote"
    MOCK = "mock"


class DeviceHealth(str, Enum):
    """Dynamic availability state reported by a backend."""

    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    CALIBRATING = "calibrating"
    MAINTENANCE = "maintenance"


class BackendJobStatus(str, Enum):
    """Backend-facing job states; transition rules are defined in P2.4."""

    CREATED = "created"
    QUEUED = "queued"
    SUBMITTED = "submitted"
    COMPILING = "compiling"
    RUNNING = "running"
    RECONCILING = "reconciling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    RESULT_UNKNOWN = "result_unknown"


class CancelOutcome(str, Enum):
    """Normalized outcome of a backend cancellation request."""

    CANCELLED = "cancelled"
    TOO_LATE = "too_late"
    NOT_SUPPORTED = "not_supported"
    NOT_FOUND = "not_found"
    ALREADY_TERMINAL = "already_terminal"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class StringMetadata:
    """Deterministic, immutable string metadata suitable for serialization."""

    items: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        frozen_items = tuple(self.items)
        normalized: list[tuple[str, str]] = []
        seen_keys: set[str] = set()
        for item in frozen_items:
            if not isinstance(item, tuple) or len(item) != 2:
                raise TypeError("metadata items must be (key, value) tuples")
            key, value = item
            key = _require_text("metadata key", key)
            if not isinstance(value, str):
                raise TypeError("metadata values must be strings")
            if key in seen_keys:
                raise ValueError(f"duplicate metadata key: {key!r}")
            seen_keys.add(key)
            normalized.append((key, value))
        object.__setattr__(self, "items", tuple(sorted(normalized)))

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> StringMetadata:
        if not isinstance(values, Mapping):
            raise TypeError("metadata must be a mapping")
        return cls(tuple(values.items()))

    def as_dict(self) -> dict[str, str]:
        """Return a mutable copy for JSON/log adapters."""

        return dict(self.items)


@dataclass(frozen=True, slots=True)
class OpaquePayload:
    """Versioned bytes whose interpretation belongs to an adapter.

    Examples of ``format`` values may eventually include ``openqasm3`` or a
    vendor-specific binary encoding.  Core scheduling code must not inspect
    ``data``.
    """

    format: str
    version: str
    data: bytes
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "format", _require_text("format", self.format))
        object.__setattr__(self, "version", _require_text("version", self.version))
        object.__setattr__(self, "schema_version", _require_positive_int("schema_version", self.schema_version))
        if not isinstance(self.data, (bytes, bytearray, memoryview)):
            raise TypeError("data must be bytes-like")
        frozen_data = bytes(self.data)
        if not frozen_data:
            raise ValueError("data must not be empty")
        object.__setattr__(self, "data", frozen_data)


@dataclass(frozen=True, slots=True)
class DeviceDescriptor:
    """Stable identity and connection information for one QPU endpoint."""

    device_id: str
    vendor: str
    model: str
    connection_mode: ConnectionMode
    hardware_group_id: str | None = None
    metadata: StringMetadata = field(default_factory=StringMetadata)
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_id", _require_text("device_id", self.device_id))
        object.__setattr__(self, "vendor", _require_text("vendor", self.vendor))
        object.__setattr__(self, "model", _require_text("model", self.model))
        _require_enum("connection_mode", self.connection_mode, ConnectionMode)
        object.__setattr__(
            self,
            "hardware_group_id",
            _require_optional_text("hardware_group_id", self.hardware_group_id),
        )
        _require_metadata(self.metadata)
        object.__setattr__(self, "schema_version", _require_positive_int("schema_version", self.schema_version))


@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    """Versioned, expiring device capabilities used for admission checks."""

    device_id: str
    observed_at: datetime
    ttl_seconds: float
    qubit_count: int
    native_gates: tuple[str, ...] = ()
    coupling_map: tuple[tuple[int, int], ...] = ()
    max_shots: int | None = None
    supports_cancel: bool = False
    metadata: StringMetadata = field(default_factory=StringMetadata)
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_id", _require_text("device_id", self.device_id))
        object.__setattr__(self, "observed_at", _require_aware_datetime("observed_at", self.observed_at))
        object.__setattr__(self, "ttl_seconds", _require_positive_number("ttl_seconds", self.ttl_seconds))
        qubit_count = _require_positive_int("qubit_count", self.qubit_count)
        object.__setattr__(self, "qubit_count", qubit_count)
        object.__setattr__(self, "native_gates", _freeze_unique_text("native_gates", self.native_gates))
        object.__setattr__(self, "coupling_map", _freeze_coupling_map(self.coupling_map, qubit_count))
        if self.max_shots is not None:
            object.__setattr__(self, "max_shots", _require_positive_int("max_shots", self.max_shots))
        if not isinstance(self.supports_cancel, bool):
            raise TypeError("supports_cancel must be a bool")
        _require_metadata(self.metadata)
        object.__setattr__(self, "schema_version", _require_positive_int("schema_version", self.schema_version))

    @property
    def expires_at(self) -> datetime:
        return self.observed_at + timedelta(seconds=self.ttl_seconds)

    def is_stale(self, at: datetime | None = None) -> bool:
        checked_at = datetime.now(timezone.utc) if at is None else _require_aware_datetime("at", at)
        return checked_at >= self.expires_at


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    """Versioned, expiring dynamic health data kept outside Ray resources."""

    device_id: str
    observed_at: datetime
    ttl_seconds: float
    status: DeviceHealth
    available_qubits: tuple[int, ...] = ()
    queue_depth: int = 0
    message: str | None = None
    metadata: StringMetadata = field(default_factory=StringMetadata)
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_id", _require_text("device_id", self.device_id))
        object.__setattr__(self, "observed_at", _require_aware_datetime("observed_at", self.observed_at))
        object.__setattr__(self, "ttl_seconds", _require_positive_number("ttl_seconds", self.ttl_seconds))
        _require_enum("status", self.status, DeviceHealth)
        object.__setattr__(self, "available_qubits", _freeze_non_negative_ints("available_qubits", self.available_qubits))
        object.__setattr__(self, "queue_depth", _require_non_negative_int("queue_depth", self.queue_depth))
        object.__setattr__(self, "message", _require_optional_text("message", self.message))
        _require_metadata(self.metadata)
        object.__setattr__(self, "schema_version", _require_positive_int("schema_version", self.schema_version))

    @property
    def expires_at(self) -> datetime:
        return self.observed_at + timedelta(seconds=self.ttl_seconds)

    def is_stale(self, at: datetime | None = None) -> bool:
        checked_at = datetime.now(timezone.utc) if at is None else _require_aware_datetime("at", at)
        return checked_at >= self.expires_at


@dataclass(frozen=True, slots=True)
class BackendSelector:
    """Stable capability constraints; an empty selector means any backend."""

    device_id: str | None = None
    vendor: str | None = None
    model: str | None = None
    min_qubits: int | None = None
    required_gates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_id", _require_optional_text("device_id", self.device_id))
        object.__setattr__(self, "vendor", _require_optional_text("vendor", self.vendor))
        object.__setattr__(self, "model", _require_optional_text("model", self.model))
        if self.min_qubits is not None:
            object.__setattr__(self, "min_qubits", _require_positive_int("min_qubits", self.min_qubits))
        object.__setattr__(self, "required_gates", _freeze_unique_text("required_gates", self.required_gates))


@dataclass(frozen=True, slots=True)
class QuantumJobRequest:
    """Validated request submitted to a future backend contract."""

    framework_job_id: str
    idempotency_key: str
    program: OpaquePayload
    shots: int
    selector: BackendSelector = field(default_factory=BackendSelector)
    deadline: datetime | None = None
    metadata: StringMetadata = field(default_factory=StringMetadata)
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "framework_job_id", _require_text("framework_job_id", self.framework_job_id))
        object.__setattr__(self, "idempotency_key", _require_text("idempotency_key", self.idempotency_key))
        if not isinstance(self.program, OpaquePayload):
            raise TypeError("program must be an OpaquePayload")
        object.__setattr__(self, "shots", _require_positive_int("shots", self.shots))
        if not isinstance(self.selector, BackendSelector):
            raise TypeError("selector must be a BackendSelector")
        if self.deadline is not None:
            object.__setattr__(self, "deadline", _require_aware_datetime("deadline", self.deadline))
        _require_metadata(self.metadata)
        object.__setattr__(self, "schema_version", _require_positive_int("schema_version", self.schema_version))


@dataclass(frozen=True, slots=True)
class BackendJobHandle:
    """Stable mapping between a framework request and a backend job."""

    framework_job_id: str
    idempotency_key: str
    backend_job_id: str
    device_id: str
    submitted_at: datetime
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "framework_job_id", _require_text("framework_job_id", self.framework_job_id))
        object.__setattr__(self, "idempotency_key", _require_text("idempotency_key", self.idempotency_key))
        object.__setattr__(self, "backend_job_id", _require_text("backend_job_id", self.backend_job_id))
        object.__setattr__(self, "device_id", _require_text("device_id", self.device_id))
        object.__setattr__(self, "submitted_at", _require_aware_datetime("submitted_at", self.submitted_at))
        object.__setattr__(self, "schema_version", _require_positive_int("schema_version", self.schema_version))


@dataclass(frozen=True, slots=True)
class QuantumResult:
    """Normalized terminal result with adapter-owned opaque bytes."""

    framework_job_id: str
    backend_job_id: str
    device_id: str
    completed_at: datetime
    payload: OpaquePayload
    shots: int
    metadata: StringMetadata = field(default_factory=StringMetadata)
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "framework_job_id", _require_text("framework_job_id", self.framework_job_id))
        object.__setattr__(self, "backend_job_id", _require_text("backend_job_id", self.backend_job_id))
        object.__setattr__(self, "device_id", _require_text("device_id", self.device_id))
        object.__setattr__(self, "completed_at", _require_aware_datetime("completed_at", self.completed_at))
        if not isinstance(self.payload, OpaquePayload):
            raise TypeError("payload must be an OpaquePayload")
        object.__setattr__(self, "shots", _require_positive_int("shots", self.shots))
        _require_metadata(self.metadata)
        object.__setattr__(self, "schema_version", _require_positive_int("schema_version", self.schema_version))


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


def _require_positive_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    normalized = float(value)
    if normalized <= 0:
        raise ValueError(f"{name} must be greater than zero")
    if normalized == float("inf") or normalized != normalized:
        raise ValueError(f"{name} must be finite")
    return normalized


def _require_aware_datetime(name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return value.astimezone(timezone.utc)


def _require_enum(name: str, value: object, enum_type: type[Enum]) -> None:
    if not isinstance(value, enum_type):
        raise TypeError(f"{name} must be a {enum_type.__name__}")


def _require_metadata(value: object) -> None:
    if not isinstance(value, StringMetadata):
        raise TypeError("metadata must be StringMetadata")


def _freeze_unique_text(name: str, values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of strings")
    frozen = tuple(_require_text(name, value) for value in values)
    if len(set(frozen)) != len(frozen):
        raise ValueError(f"{name} must not contain duplicates")
    return frozen


def _freeze_non_negative_ints(name: str, values: Iterable[int]) -> tuple[int, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of integers")
    frozen = tuple(_require_non_negative_int(name, value) for value in values)
    if len(set(frozen)) != len(frozen):
        raise ValueError(f"{name} must not contain duplicates")
    return frozen


def _freeze_coupling_map(
    values: Iterable[tuple[int, int]],
    qubit_count: int,
) -> tuple[tuple[int, int], ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("coupling_map must be an iterable of pairs")
    frozen: list[tuple[int, int]] = []
    for edge in values:
        if not isinstance(edge, (tuple, list)) or len(edge) != 2:
            raise TypeError("coupling_map entries must be two-item pairs")
        source = _require_non_negative_int("coupling_map source", edge[0])
        target = _require_non_negative_int("coupling_map target", edge[1])
        if source == target:
            raise ValueError("coupling_map entries must connect different qubits")
        if source >= qubit_count or target >= qubit_count:
            raise ValueError("coupling_map references a qubit outside qubit_count")
        frozen.append((source, target))
    if len(set(frozen)) != len(frozen):
        raise ValueError("coupling_map must not contain duplicate edges")
    return tuple(frozen)


__all__ = [
    "BackendJobHandle",
    "BackendJobStatus",
    "BackendSelector",
    "CancelOutcome",
    "CapabilitySnapshot",
    "ConnectionMode",
    "DeviceDescriptor",
    "DeviceHealth",
    "HealthSnapshot",
    "OpaquePayload",
    "QuantumJobRequest",
    "QuantumResult",
    "StringMetadata",
]
