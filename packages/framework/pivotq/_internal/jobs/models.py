"""Pure contracts for submitting complete applications through Ray Jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import re
from typing import Iterable, Mapping
from urllib.parse import urlsplit


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_ENVIRONMENT_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")
_REMOTE_WORKING_DIR_SCHEMES = frozenset(
    {"abfss", "azure", "gs", "http", "https", "s3"}
)
_TERMINAL_JOB_STATUSES = frozenset({"stopped", "succeeded", "failed"})


class RayJobStatus(str, Enum):
    """Ray Jobs application lifecycle, separate from invocation lifecycle."""

    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self.value in _TERMINAL_JOB_STATUSES


@dataclass(frozen=True, slots=True, repr=False)
class RayJobRuntimeEnvironment:
    """Small, versioned subset of Ray's runtime environment for P7.1.

    The contract intentionally supports only the fields needed to package a
    framework application without importing Ray.  Environment variable values
    are never included in ``repr`` because they may contain credentials.
    """

    working_dir: str | None = None
    pip_packages: Iterable[str] = ()
    env_vars: Mapping[str, str] | Iterable[tuple[str, str]] = field(
        default=(),
        repr=False,
    )
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "working_dir", _freeze_working_dir(self.working_dir))
        object.__setattr__(self, "pip_packages", _freeze_pip_packages(self.pip_packages))
        object.__setattr__(self, "env_vars", _freeze_env_vars(self.env_vars))
        _require_schema_version(self.schema_version)

    def as_ray_dict(self) -> dict[str, object]:
        """Return a fresh dictionary accepted by Ray 2.31.0 RuntimeEnv."""

        runtime_env: dict[str, object] = {}
        if self.working_dir is not None:
            runtime_env["working_dir"] = self.working_dir
        if self.pip_packages:
            runtime_env["pip"] = list(self.pip_packages)
        if self.env_vars:
            runtime_env["env_vars"] = dict(self.env_vars)
        return runtime_env

    def __repr__(self) -> str:
        return (
            "RayJobRuntimeEnvironment("
            f"working_dir={self.working_dir!r}, "
            f"pip_package_count={len(self.pip_packages)}, "
            f"env_var_names={tuple(name for name, _ in self.env_vars)!r}, "
            f"schema_version={self.schema_version})"
        )


@dataclass(frozen=True, slots=True)
class RayJobDriverResources:
    """Resources reserved only for the Ray Job entrypoint process."""

    num_cpus: float | None = None
    num_gpus: float | None = None
    memory_bytes: int | None = None
    custom_resources: (
        Mapping[str, int | float] | Iterable[tuple[str, int | float]]
    ) = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "num_cpus",
            _require_optional_non_negative_number("num_cpus", self.num_cpus),
        )
        object.__setattr__(
            self,
            "num_gpus",
            _require_optional_non_negative_number("num_gpus", self.num_gpus),
        )
        object.__setattr__(
            self,
            "memory_bytes",
            _require_optional_non_negative_integer("memory_bytes", self.memory_bytes),
        )
        object.__setattr__(
            self,
            "custom_resources",
            _freeze_custom_resources(self.custom_resources),
        )
        _require_schema_version(self.schema_version)

    def as_submit_arguments(self) -> dict[str, object]:
        """Return fresh kwargs matching Ray 2.31.0 ``submit_job``."""

        return {
            "entrypoint_num_cpus": self.num_cpus,
            "entrypoint_num_gpus": self.num_gpus,
            "entrypoint_memory": self.memory_bytes,
            "entrypoint_resources": (
                dict(self.custom_resources) if self.custom_resources else None
            ),
        }


@dataclass(frozen=True, slots=True, repr=False)
class RayJobSpec:
    """One complete application submission, not one framework invocation."""

    submission_id: str
    entrypoint: str = field(repr=False)
    runtime_environment: RayJobRuntimeEnvironment = field(
        default_factory=RayJobRuntimeEnvironment,
        repr=False,
    )
    metadata: Mapping[str, str] | Iterable[tuple[str, str]] = field(
        default=(),
        repr=False,
    )
    driver_resources: RayJobDriverResources = field(
        default_factory=RayJobDriverResources,
    )
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "submission_id",
            _require_stable_identifier("submission_id", self.submission_id),
        )
        object.__setattr__(self, "entrypoint", _require_entrypoint(self.entrypoint))
        if not isinstance(self.runtime_environment, RayJobRuntimeEnvironment):
            raise TypeError(
                "runtime_environment must be a RayJobRuntimeEnvironment"
            )
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))
        if not isinstance(self.driver_resources, RayJobDriverResources):
            raise TypeError("driver_resources must be RayJobDriverResources")
        _require_schema_version(self.schema_version)

    def metadata_dict(self) -> dict[str, str]:
        return dict(self.metadata)

    def __repr__(self) -> str:
        return (
            "RayJobSpec("
            f"submission_id={self.submission_id!r}, "
            "entrypoint=<redacted>, "
            f"runtime_environment={self.runtime_environment!r}, "
            f"metadata_keys={tuple(name for name, _ in self.metadata)!r}, "
            f"driver_resources={self.driver_resources!r}, "
            f"schema_version={self.schema_version})"
        )


@dataclass(frozen=True, slots=True)
class RayJobHandle:
    """Stable Ray Job identity returned by application submission."""

    submission_id: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "submission_id",
            _require_stable_identifier("submission_id", self.submission_id),
        )
        _require_schema_version(self.schema_version)


def _require_stable_identifier(name: str, value: object) -> str:
    value = _require_text(name, value, maximum_length=128)
    if _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{name} must start with an alphanumeric character and contain "
            "only alphanumerics, '_', '-' or '.' (maximum 128 characters)"
        )
    return value


def _require_entrypoint(value: object) -> str:
    value = _require_text("entrypoint", value, maximum_length=8192)
    if "\x00" in value or "\r" in value or "\n" in value:
        raise ValueError("entrypoint must be a single command without NUL or newlines")
    return value


def _freeze_working_dir(value: object) -> str | None:
    if value is None:
        return None
    value = _require_text("working_dir", value, maximum_length=4096)
    if "\x00" in value or "\r" in value or "\n" in value:
        raise ValueError("working_dir must not contain NUL or newlines")

    if not _WINDOWS_DRIVE_PATTERN.match(value):
        parsed = urlsplit(value)
        if parsed.scheme:
            if parsed.scheme.lower() not in _REMOTE_WORKING_DIR_SCHEMES:
                raise ValueError(
                    "remote working_dir must use a Ray 2.31.0 supported "
                    "HTTP or cloud-storage scheme"
                )
            if not parsed.netloc:
                raise ValueError("remote working_dir must include a host or bucket")
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("working_dir URI must not contain credentials")
            if parsed.query or parsed.fragment:
                raise ValueError("working_dir URI must not contain query or fragment")
    return value


def _freeze_pip_packages(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("pip_packages must be an iterable of package requirements")
    try:
        frozen = tuple(
            _require_text("pip package", value, maximum_length=1024)
            for value in values
        )
    except TypeError as error:
        raise TypeError(
            "pip_packages must be an iterable of package requirements"
        ) from error
    for requirement in frozen:
        if "\x00" in requirement or "\r" in requirement or "\n" in requirement:
            raise ValueError("pip package requirements must not contain NUL or newlines")
    return frozen


def _freeze_env_vars(
    values: Mapping[str, str] | Iterable[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []
    seen_names: set[str] = set()
    for name, value in _iter_pairs("env_vars", values):
        name = _require_text("environment variable name", name, maximum_length=256)
        if _ENVIRONMENT_NAME_PATTERN.fullmatch(name) is None:
            raise ValueError(f"invalid environment variable name: {name!r}")
        if name in seen_names:
            raise ValueError(f"duplicate environment variable: {name!r}")
        seen_names.add(name)
        value = _require_string("environment variable value", value)
        if "\x00" in value:
            raise ValueError("environment variable values must not contain NUL")
        normalized.append((name, value))
    return tuple(sorted(normalized))


def _freeze_metadata(
    values: Mapping[str, str] | Iterable[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []
    seen_names: set[str] = set()
    for name, value in _iter_pairs("metadata", values):
        name = _require_text("metadata key", name, maximum_length=256)
        value = _require_text("metadata value", value, maximum_length=4096)
        if name in seen_names:
            raise ValueError(f"duplicate metadata key: {name!r}")
        seen_names.add(name)
        normalized.append((name, value))
    return tuple(sorted(normalized))


def _freeze_custom_resources(
    values: Mapping[str, int | float] | Iterable[tuple[str, int | float]],
) -> tuple[tuple[str, float], ...]:
    normalized: list[tuple[str, float]] = []
    seen_names: set[str] = set()
    for name, quantity in _iter_pairs("custom_resources", values):
        name = _require_text("custom resource name", name, maximum_length=256)
        if name in {"CPU", "GPU", "memory"}:
            raise ValueError(f"{name} must use its dedicated driver resource field")
        if name in seen_names:
            raise ValueError(f"duplicate custom resource: {name!r}")
        seen_names.add(name)
        normalized.append(
            (name, _require_positive_number(f"custom resource {name!r}", quantity))
        )
    return tuple(sorted(normalized))


def _iter_pairs(name: str, values: object) -> tuple[tuple[object, object], ...]:
    if isinstance(values, Mapping):
        return tuple(values.items())
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be a mapping or iterable of pairs")
    try:
        items = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be a mapping or iterable of pairs") from error
    normalized: list[tuple[object, object]] = []
    for item in items:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise TypeError(f"{name} entries must be two-item pairs")
        normalized.append((item[0], item[1]))
    return tuple(normalized)


def _require_text(name: str, value: object, *, maximum_length: int) -> str:
    value = _require_string(name, value)
    if not value:
        raise ValueError(f"{name} must not be empty")
    if value != value.strip():
        raise ValueError(f"{name} must not have surrounding whitespace")
    if len(value) > maximum_length:
        raise ValueError(f"{name} must not exceed {maximum_length} characters")
    return value


def _require_string(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _require_optional_non_negative_number(
    name: str,
    value: object,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number or None")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return normalized


def _require_positive_number(name: str, value: object) -> float:
    normalized = _require_optional_non_negative_number(name, value)
    if normalized is None or normalized <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return normalized


def _require_optional_non_negative_integer(
    name: str,
    value: object,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer or None")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _require_schema_version(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("schema_version must be an integer")
    if value != 1:
        raise ValueError("only schema_version 1 is supported")


__all__ = [
    "RayJobDriverResources",
    "RayJobHandle",
    "RayJobRuntimeEnvironment",
    "RayJobSpec",
    "RayJobStatus",
]
