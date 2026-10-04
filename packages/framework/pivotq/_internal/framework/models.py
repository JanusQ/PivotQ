"""Serializable contracts owned by the fusion programming framework.

External component arguments and return values remain opaque to this module.
The only payload-level requirement is compatibility with Python's standard
``pickle`` transport boundary.
"""

from __future__ import annotations

import keyword
import math
import pickle
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pivotq._internal.errors import RayQuantumError
from pivotq._internal.models import StringMetadata


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_TERMINAL_INVOCATION_STATUSES = frozenset(
    {
        "succeeded",
        "failed",
        "cancelled",
        "timed_out",
    }
)


class ExecutionMode(str, Enum):
    """How an executor should host an external component."""

    TASK = "task"
    ACTOR = "actor"


class InvocationStatus(str, Enum):
    """Framework-level lifecycle states independent of Ray internals."""

    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def is_terminal(self) -> bool:
        """Whether no more framework state transitions are expected."""

        return self.value in _TERMINAL_INVOCATION_STATUSES


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    """Stable placement resources for one external component.

    CPU and GPU quantities may be fractional because Ray supports fractional
    logical resources.  Physical QPU capacity tokens are exclusive units, so
    ``QPU`` and ``qpu_device_<id>`` values must be positive whole numbers.
    """

    num_cpus: float = 1.0
    num_gpus: float = 0.0
    custom_resources: (
        Mapping[str, int | float] | Iterable[tuple[str, int | float]]
    ) = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "num_cpus",
            _require_non_negative_number("num_cpus", self.num_cpus),
        )
        object.__setattr__(
            self,
            "num_gpus",
            _require_non_negative_number("num_gpus", self.num_gpus),
        )
        object.__setattr__(
            self,
            "custom_resources",
            _freeze_custom_resources(self.custom_resources),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_positive_int("schema_version", self.schema_version),
        )

    def custom_resources_dict(self) -> dict[str, float]:
        """Return a mutable copy suitable for an executor API."""

        return dict(self.custom_resources)


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    """Registration-time behavior and resource requirements for a component."""

    component_id: str
    execution: ExecutionMode
    resources: ResourceRequest
    allowed_methods: Iterable[str]
    stateful: bool = False
    max_concurrency: int = 1
    timeout_seconds: float | None = None
    metadata: StringMetadata = field(default_factory=StringMetadata)
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "component_id",
            _require_stable_identifier("component_id", self.component_id),
        )
        _require_enum("execution", self.execution, ExecutionMode)
        if not isinstance(self.resources, ResourceRequest):
            raise TypeError("resources must be a ResourceRequest")
        object.__setattr__(
            self,
            "allowed_methods",
            _freeze_method_names(self.allowed_methods),
        )
        if not isinstance(self.stateful, bool):
            raise TypeError("stateful must be a bool")
        if self.stateful and self.execution is not ExecutionMode.ACTOR:
            raise ValueError("stateful components must use actor execution")
        object.__setattr__(
            self,
            "max_concurrency",
            _require_positive_int("max_concurrency", self.max_concurrency),
        )
        if self.timeout_seconds is not None:
            object.__setattr__(
                self,
                "timeout_seconds",
                _require_positive_number(
                    "timeout_seconds",
                    self.timeout_seconds,
                ),
            )
        if not isinstance(self.metadata, StringMetadata):
            raise TypeError("metadata must be StringMetadata")
        object.__setattr__(
            self,
            "schema_version",
            _require_positive_int("schema_version", self.schema_version),
        )


@dataclass(frozen=True, slots=True)
class InvocationSpec:
    """One method call whose arguments and result are framework-opaque."""

    invocation_id: str
    component_id: str
    method: str
    args: Iterable[Any] = ()
    kwargs: Mapping[str, Any] | Iterable[tuple[str, Any]] = ()
    dependencies: Iterable[str] = ()
    deadline: datetime | None = None
    trace_context: StringMetadata = field(default_factory=StringMetadata)
    schema_version: int = 1

    def __post_init__(self) -> None:
        invocation_id = _require_stable_identifier(
            "invocation_id",
            self.invocation_id,
        )
        object.__setattr__(self, "invocation_id", invocation_id)
        object.__setattr__(
            self,
            "component_id",
            _require_stable_identifier("component_id", self.component_id),
        )
        object.__setattr__(self, "method", _require_method_name(self.method))

        args = _freeze_args(self.args)
        kwargs = _freeze_keyword_arguments(self.kwargs)
        dependencies = _freeze_dependencies(
            self.dependencies,
            invocation_id=invocation_id,
        )
        _require_pickle_serializable("invocation arguments", (args, kwargs))
        object.__setattr__(self, "args", args)
        object.__setattr__(self, "kwargs", kwargs)
        object.__setattr__(self, "dependencies", dependencies)

        if self.deadline is not None:
            object.__setattr__(
                self,
                "deadline",
                _require_aware_datetime("deadline", self.deadline),
            )
        if not isinstance(self.trace_context, StringMetadata):
            raise TypeError("trace_context must be StringMetadata")
        object.__setattr__(
            self,
            "schema_version",
            _require_positive_int("schema_version", self.schema_version),
        )

    def kwargs_dict(self) -> dict[str, Any]:
        """Return a mutable copy for calling ``method(*args, **kwargs)``."""

        return dict(self.kwargs)

    def is_expired(self, at: datetime | None = None) -> bool:
        """Return whether the invocation deadline has passed."""

        if self.deadline is None:
            return False
        checked_at = (
            datetime.now(timezone.utc)
            if at is None
            else _require_aware_datetime("at", at)
        )
        return checked_at >= self.deadline


@dataclass(frozen=True, slots=True)
class InvocationHandle:
    """Logical invocation identity plus an executor-owned opaque reference.

    ``reference`` may later be a Ray ``ObjectRef`` or a local executor token.
    Keeping it opaque avoids importing Ray into the framework contract layer.
    """

    invocation_id: str
    component_id: str
    reference: Any
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "invocation_id",
            _require_stable_identifier("invocation_id", self.invocation_id),
        )
        object.__setattr__(
            self,
            "component_id",
            _require_stable_identifier("component_id", self.component_id),
        )
        if self.reference is None:
            raise ValueError("reference must not be None")
        _require_pickle_serializable("reference", self.reference)
        object.__setattr__(
            self,
            "schema_version",
            _require_positive_int("schema_version", self.schema_version),
        )


@dataclass(frozen=True, slots=True)
class InvocationResult:
    """Terminal result or structured framework error for one invocation."""

    invocation_id: str
    component_id: str
    status: InvocationStatus
    value: Any = None
    error: RayQuantumError | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "invocation_id",
            _require_stable_identifier("invocation_id", self.invocation_id),
        )
        object.__setattr__(
            self,
            "component_id",
            _require_stable_identifier("component_id", self.component_id),
        )
        _require_enum("status", self.status, InvocationStatus)
        if not self.status.is_terminal:
            raise ValueError("InvocationResult status must be terminal")

        if self.status is InvocationStatus.SUCCEEDED:
            if self.error is not None:
                raise ValueError("successful results must not contain an error")
            _require_pickle_serializable("result value", self.value)
        else:
            if self.value is not None:
                raise ValueError("unsuccessful results must not contain a value")
            if not isinstance(self.error, RayQuantumError):
                raise TypeError(
                    "unsuccessful results must contain a RayQuantumError"
                )
            _require_pickle_serializable("result error", self.error)

        object.__setattr__(
            self,
            "schema_version",
            _require_positive_int("schema_version", self.schema_version),
        )

    @property
    def succeeded(self) -> bool:
        return self.status is InvocationStatus.SUCCEEDED


def _require_stable_identifier(name: str, value: object) -> str:
    value = _require_text(name, value)
    if _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{name} must start with an alphanumeric character and contain "
            "only alphanumerics, '_', '-' or '.' (maximum 128 characters)"
        )
    return value


def _require_method_name(value: object) -> str:
    value = _require_text("method", value)
    if (
        not value.isidentifier()
        or keyword.iskeyword(value)
        or value.startswith("_")
    ):
        raise ValueError("method must be a public Python identifier")
    return value


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} must not be empty")
    if value != value.strip():
        raise ValueError(f"{name} must not have surrounding whitespace")
    if "\x00" in value:
        raise ValueError(f"{name} must not contain NUL")
    return value


def _require_positive_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _require_non_negative_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    if normalized < 0:
        raise ValueError(f"{name} must not be negative")
    return normalized


def _require_positive_number(name: str, value: object) -> float:
    normalized = _require_non_negative_number(name, value)
    if normalized <= 0:
        raise ValueError(f"{name} must be greater than zero")
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


def _iter_pairs(
    name: str,
    values: Mapping[str, Any] | Iterable[tuple[str, Any]],
) -> tuple[tuple[str, Any], ...]:
    if isinstance(values, Mapping):
        return tuple(values.items())
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be a mapping or iterable of pairs")
    try:
        items = tuple(values)
    except TypeError as error:
        raise TypeError(
            f"{name} must be a mapping or iterable of pairs"
        ) from error

    normalized: list[tuple[str, Any]] = []
    for item in items:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise TypeError(f"{name} entries must be two-item pairs")
        normalized.append((item[0], item[1]))
    return tuple(normalized)


def _freeze_custom_resources(
    values: Mapping[str, int | float] | Iterable[tuple[str, int | float]],
) -> tuple[tuple[str, float], ...]:
    normalized: list[tuple[str, float]] = []
    seen_names: set[str] = set()
    for name, quantity in _iter_pairs("custom_resources", values):
        resource_name = _require_text("custom resource name", name)
        if resource_name in {"CPU", "GPU"}:
            raise ValueError(
                f"{resource_name} must use its dedicated resource field"
            )
        if resource_name in seen_names:
            raise ValueError(f"duplicate custom resource: {resource_name!r}")
        seen_names.add(resource_name)

        normalized_quantity = _require_positive_number(
            f"custom resource {resource_name!r}",
            quantity,
        )
        if _is_physical_qpu_resource(resource_name):
            if not float(normalized_quantity).is_integer():
                raise ValueError(
                    f"physical QPU resource {resource_name!r} "
                    "must use a whole-number quantity"
                )
        normalized.append((resource_name, normalized_quantity))
    return tuple(sorted(normalized))


def _is_physical_qpu_resource(name: str) -> bool:
    return name == "QPU" or name.startswith("qpu_device_")


def _freeze_method_names(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("allowed_methods must be an iterable of method names")
    try:
        frozen = tuple(_require_method_name(value) for value in values)
    except TypeError as error:
        raise TypeError(
            "allowed_methods must be an iterable of method names"
        ) from error
    if not frozen:
        raise ValueError("allowed_methods must not be empty")
    if len(set(frozen)) != len(frozen):
        raise ValueError("allowed_methods must not contain duplicates")
    return frozen


def _freeze_args(values: Iterable[Any]) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise TypeError("args must be an iterable of positional arguments")
    try:
        return tuple(values)
    except TypeError as error:
        raise TypeError(
            "args must be an iterable of positional arguments"
        ) from error


def _freeze_keyword_arguments(
    values: Mapping[str, Any] | Iterable[tuple[str, Any]],
) -> tuple[tuple[str, Any], ...]:
    normalized: list[tuple[str, Any]] = []
    seen_names: set[str] = set()
    for name, value in _iter_pairs("kwargs", values):
        name = _require_text("keyword argument name", name)
        if name in seen_names:
            raise ValueError(f"duplicate keyword argument: {name!r}")
        seen_names.add(name)
        normalized.append((name, value))
    return tuple(normalized)


def _freeze_dependencies(
    values: Iterable[str],
    *,
    invocation_id: str,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("dependencies must be an iterable of invocation IDs")
    try:
        frozen = tuple(
            _require_stable_identifier("dependency ID", value)
            for value in values
        )
    except TypeError as error:
        raise TypeError(
            "dependencies must be an iterable of invocation IDs"
        ) from error
    if len(set(frozen)) != len(frozen):
        raise ValueError("dependencies must not contain duplicates")
    if invocation_id in frozen:
        raise ValueError("an invocation cannot depend on itself")
    return frozen


def _require_pickle_serializable(name: str, value: object) -> None:
    try:
        pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        raise ValueError(f"{name} must be pickle-serializable") from None


__all__ = [
    "ComponentSpec",
    "ExecutionMode",
    "InvocationHandle",
    "InvocationResult",
    "InvocationSpec",
    "InvocationStatus",
    "ResourceRequest",
]
