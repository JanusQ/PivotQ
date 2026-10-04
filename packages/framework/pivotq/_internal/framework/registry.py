"""Thread-safe registrations for externally implemented components."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from pivotq._internal.errors import UnavailableError, ValidationError

from .component import ComponentFactory, validate_component_factory
from .models import ComponentSpec


@dataclass(frozen=True, slots=True)
class ComponentRegistration:
    """A validated component specification and its configured factory."""

    spec: ComponentSpec
    factory: ComponentFactory

    def __post_init__(self) -> None:
        if not isinstance(self.spec, ComponentSpec):
            raise TypeError("spec must be a ComponentSpec")
        validate_component_factory(self.factory)


class ComponentRegistry:
    """In-memory registry shared by local and future Ray executors.

    Registration never calls a factory.  Component construction belongs to an
    executor because a future Ray implementation must construct Actors/Tasks in
    the correct worker process rather than on the Driver.
    """

    def __init__(self) -> None:
        self._registrations: dict[str, ComponentRegistration] = {}
        self._closed = False
        self._lock = RLock()

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def register(
        self,
        spec: ComponentSpec,
        factory: ComponentFactory,
    ) -> ComponentRegistration:
        """Register a unique component without constructing it."""

        registration = ComponentRegistration(spec=spec, factory=factory)
        with self._lock:
            self._ensure_open()
            if spec.component_id in self._registrations:
                raise ValidationError(
                    f"component {spec.component_id!r} is already registered"
                )
            self._registrations[spec.component_id] = registration
        return registration

    def get(self, component_id: str) -> ComponentRegistration:
        """Return one registration or raise a structured validation error."""

        component_id = _require_component_id(component_id)
        with self._lock:
            self._ensure_open()
            registration = self._registrations.get(component_id)
            if registration is None:
                raise ValidationError(
                    f"component {component_id!r} is not registered"
                )
            return registration

    def replace_registration(
        self, expected: ComponentRegistration, replacement: ComponentRegistration,
    ) -> None:
        """Atomically resolve an unused registration to its selected implementation.

        The façade calls this before the first submission. Direct registry users
        must likewise ensure no executor has constructed the component yet.
        """
        if expected.spec.component_id != replacement.spec.component_id:
            raise ValueError("replacement must preserve component_id")
        with self._lock:
            self._ensure_open()
            if self._registrations.get(expected.spec.component_id) is not expected:
                raise ValidationError("component registration changed during execution selection")
            self._registrations[expected.spec.component_id] = replacement

    def unregister(self, component_id: str) -> ComponentRegistration:
        """Remove and return a registration.

        Active executors must be closed before dynamically unregistering a
        component that may already have a long-lived instance.
        """

        component_id = _require_component_id(component_id)
        with self._lock:
            self._ensure_open()
            registration = self._registrations.pop(component_id, None)
            if registration is None:
                raise ValidationError(
                    f"component {component_id!r} is not registered"
                )
            return registration

    def registrations(self) -> tuple[ComponentRegistration, ...]:
        """Return an immutable component-ID-sorted snapshot."""

        with self._lock:
            self._ensure_open()
            return tuple(
                self._registrations[component_id]
                for component_id in sorted(self._registrations)
            )

    def close(self) -> None:
        """Clear registrations and permanently reject new operations."""

        with self._lock:
            if self._closed:
                return
            self._registrations.clear()
            self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise UnavailableError("component registry is closed")


def _require_component_id(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("component_id must be a string")
    if not value:
        raise ValueError("component_id must not be empty")
    if value != value.strip():
        raise ValueError("component_id must not have surrounding whitespace")
    return value


__all__ = [
    "ComponentRegistration",
    "ComponentRegistry",
]
