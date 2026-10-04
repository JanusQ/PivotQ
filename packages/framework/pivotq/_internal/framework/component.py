"""Structural contracts and registration-time component validation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, TypeVar, runtime_checkable

from .models import ComponentSpec, InvocationSpec


_ComponentT = TypeVar("_ComponentT")


@runtime_checkable
class ComponentFactory(Protocol):
    """A configured, zero-argument factory for one external component."""

    def __call__(self) -> object:
        """Create a component instance."""

        ...


@runtime_checkable
class ComponentAdapter(Protocol):
    """Minimum shared surface of screenshot-style external components.

    Business methods such as ``predict`` or ``extract_features`` are checked
    dynamically from ``ComponentSpec.allowed_methods`` because the framework
    does not own their request or response types.
    """

    def describe(self) -> Mapping[str, Any]:
        """Return external component capabilities and current state."""

        ...


def validate_component_factory(
    factory: _ComponentT,
) -> _ComponentT:
    """Reject values that cannot construct an external component.

    The factory is not called here because registration validation must not
    initialize hardware, models, or other external state.
    """

    if not callable(factory):
        raise TypeError("component factory must be callable")
    return factory


def validate_component_instance(
    spec: ComponentSpec,
    instance: _ComponentT,
) -> _ComponentT:
    """Validate the minimal component surface without invoking any method."""

    if not isinstance(spec, ComponentSpec):
        raise TypeError("spec must be a ComponentSpec")
    if instance is None:
        raise TypeError("component instance must not be None")
    if not isinstance(instance, ComponentAdapter):
        raise TypeError("component instance must provide a callable describe()")

    for method_name in spec.allowed_methods:
        candidate = getattr(instance, method_name, None)
        if not callable(candidate):
            raise TypeError(
                f"component {spec.component_id!r} must provide callable "
                f"method {method_name!r}"
            )
    return instance


def validate_invocation(
    spec: ComponentSpec,
    invocation: InvocationSpec,
) -> InvocationSpec:
    """Check that an invocation is permitted by a registered component."""

    if not isinstance(spec, ComponentSpec):
        raise TypeError("spec must be a ComponentSpec")
    if not isinstance(invocation, InvocationSpec):
        raise TypeError("invocation must be an InvocationSpec")
    if invocation.component_id != spec.component_id:
        raise ValueError(
            "invocation component_id does not match the registered component"
        )
    if invocation.method not in spec.allowed_methods:
        raise ValueError(
            f"method {invocation.method!r} is not allowed for component "
            f"{spec.component_id!r}"
        )
    return invocation


__all__ = [
    "ComponentAdapter",
    "ComponentFactory",
    "validate_component_factory",
    "validate_component_instance",
    "validate_invocation",
]
