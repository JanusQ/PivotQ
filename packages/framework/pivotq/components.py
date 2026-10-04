"""CPU components and Runtime-owned, stateful actors."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import inspect
import keyword
import math
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .runtime import Runtime
    from .refs import ResultRef


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    """A CPU component; Task instances are per-call and Actor instances persist.

    ``max_concurrency`` is an Actor option. Serial Actor calls are mutually
    exclusive; dependent state updates should pass references between calls.
    ``timeout_seconds`` uses executor deadlines, not wait timeouts. Local timing
    starts after dependencies resolve; Ray timing includes dependency waiting.
    Metadata contains explicit string labels, never business payloads or secrets.
    """

    name: str
    methods: tuple[str, ...]
    execution: str = "task"
    num_cpus: float = 1
    max_concurrency: int | None = None
    timeout_seconds: float | None = None
    metadata: Mapping[str, str] | tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("component name must be nonempty")
        if isinstance(self.methods, str):
            raise TypeError("methods must be a sequence of method names")
        methods = tuple(self.methods)
        if not methods or len(set(methods)) != len(methods):
            raise ValueError("methods must be nonempty and unique")
        if any(not isinstance(name, str) or not name.isidentifier() or name.startswith("_")
               or keyword.iskeyword(name) or name in ("close", "describe") for name in methods):
            raise ValueError("methods must be public business methods (not close/describe)")
        object.__setattr__(self, "methods", methods)
        if self.execution not in ("task", "actor"):
            raise ValueError("execution must be 'task' or 'actor'")
        if isinstance(self.num_cpus, bool) or not isinstance(self.num_cpus, (int, float)) or not math.isfinite(self.num_cpus) or self.num_cpus <= 0:
            raise ValueError("num_cpus must be a finite positive number")
        if self.max_concurrency is not None:
            if self.execution != "actor":
                raise ValueError("max_concurrency is only supported for actors")
            if isinstance(self.max_concurrency, bool) or not isinstance(self.max_concurrency, int) or self.max_concurrency < 1:
                raise ValueError("max_concurrency must be a positive integer")
        if self.timeout_seconds is not None and (
                isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float))
                or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0):
            raise ValueError("timeout_seconds must be a finite positive number or None")
        items = tuple(self.metadata.items()) if isinstance(self.metadata, Mapping) else tuple(self.metadata)
        if any(not isinstance(item, tuple) or len(item) != 2
               or not isinstance(item[0], str) or not item[0]
               or not isinstance(item[1], str) for item in items):
            raise TypeError("metadata must contain nonempty string keys and string values")
        if len({key for key, _ in items}) != len(items):
            raise ValueError("metadata keys must be unique")
        object.__setattr__(self, "metadata", tuple(sorted(items)))

    def metadata_dict(self) -> dict[str, str]:
        """Return a detached metadata copy. Never put payloads or secrets here."""
        return dict(self.metadata)


class ComponentHandle:
    """A Runtime-owned component. Every method submission returns a ResultRef."""

    def __init__(self, runtime: Runtime, spec: ComponentSpec, component_id: str) -> None:
        self._runtime = runtime
        self._spec = spec
        self._component_id = component_id

    @property
    def spec(self) -> ComponentSpec:
        return self._spec

    def submit(self, method: str, /, *args: Any,
               kwargs: Mapping[str, Any] | None = None) -> ResultRef[Any]:
        return self._runtime._submit_component(self._component_id, method, *args, kwargs=kwargs)

    def describe(self) -> ComponentSpec:
        return self._spec

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("ComponentHandle belongs to its creating Runtime")


@dataclass(frozen=True)
class _ComponentFactory:
    factory: Callable[[], object]
    spec: ComponentSpec

    def __call__(self) -> _ComponentAdapter:
        instance = self.factory()
        try:
            for name in self.spec.methods:
                method = getattr(instance, name, None)
                if (not callable(method) or inspect.iscoroutinefunction(method)
                        or inspect.isgeneratorfunction(method) or inspect.isasyncgenfunction(method)):
                    raise TypeError(f"component method {name!r} must be synchronous")
        except BaseException:
            close = getattr(instance, "close", None)
            if callable(close):
                close()
            raise
        return _ComponentAdapter(instance, self.spec)


class _ComponentAdapter:
    def __init__(self, instance: object, spec: ComponentSpec) -> None:
        self._instance, self._spec = instance, spec
        self._closed = False

    def describe(self) -> dict[str, Any]:
        return {"name": self._spec.name, "methods": self._spec.methods,
                "execution": self._spec.execution}

    def __getattr__(self, name: str) -> Any:
        if name in self._spec.methods:
            return getattr(self._instance, name)
        raise AttributeError(name)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        close = getattr(self._instance, "close", None)
        if callable(close):
            close()


@dataclass(frozen=True)
class _ActorFactory:
    constructor: Callable[..., object]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]

    def __call__(self) -> object:
        return self.constructor(*self.args, **self.kwargs)


__all__ = ["ComponentSpec", "ComponentHandle"]
