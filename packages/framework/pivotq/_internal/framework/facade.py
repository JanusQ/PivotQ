"""Unified application façade for component registration and invocation DAGs."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime
from threading import RLock
from types import TracebackType
from typing import Any, Protocol

from pivotq._internal.errors import UnavailableError, ValidationError
from pivotq._internal.models import StringMetadata

from .component import ComponentFactory, validate_invocation
from .graph import (
    InvocationGraph,
    ResultRef,
    _normalize_handle_references,
    result_ref_ids,
)
from .models import (
    ComponentSpec,
    InvocationHandle,
    InvocationResult,
    InvocationSpec,
    ResourceRequest,
)
from .registry import (
    ComponentRegistration,
    ComponentRegistry,
)
from .simulation import ExecutionSelection, SimulationAdapter, has_device_capacity, requested_devices


class _ExecutorLike(Protocol):
    @property
    def closed(self) -> bool: ...

    @property
    def registry(self) -> ComponentRegistry: ...

    def submit(self, invocation: InvocationSpec) -> InvocationHandle: ...

    def result(self, handle: InvocationHandle) -> InvocationResult: ...

    def release(self, handle: InvocationHandle) -> None: ...

    def close(self) -> None: ...


class FusionFramework:
    """Application-facing registration, submission, and result boundary.

    The façade owns the executor lifecycle but not the supplied registry.
    Calling ``close()`` closes the executor; callers close the registry after
    they no longer need registration metadata.
    """

    def __init__(self, executor: _ExecutorLike, *, simulation: bool = False) -> None:
        if type(simulation) is not bool:
            raise TypeError("simulation must be a bool")
        registry = getattr(executor, "registry", None)
        if not isinstance(registry, ComponentRegistry):
            raise TypeError(
                "executor must expose its ComponentRegistry through registry"
            )
        for method_name in ("submit", "result", "release", "close"):
            if not callable(getattr(executor, method_name, None)):
                raise TypeError(
                    f"executor must provide a callable {method_name}()"
                )
        if not isinstance(getattr(executor, "closed", None), bool):
            raise TypeError("executor must expose a boolean closed property")
        self._executor = executor
        self._registry = registry
        self._handles: dict[str, InvocationHandle] = {}
        self._invocations: dict[str, InvocationSpec] = {}
        self._used_component_ids: set[str] = set()
        self._lock = RLock()
        self._simulation = simulation
        self._simulation_adapters: dict[str, SimulationAdapter] = {}
        self._execution_selections: dict[str, ExecutionSelection] = {}
        self._requested_registrations: dict[str, ComponentRegistration] = {}

    @property
    def simulation(self) -> bool:
        return self._simulation

    def register_simulation_adapter(
        self, component_id: str, *, factory: ComponentFactory,
        resources: ResourceRequest, required_devices: tuple[str, ...] = (),
        availability: Callable[[], bool] | None = None, backend: str = "cpu",
    ) -> None:
        """Register an opt-in substitute before resolving or using a component.

        A custom availability callback reports configured hardware, not idle
        capacity. Callback failures propagate; they never trigger simulation.
        """
        adapter = SimulationAdapter(factory, resources, required_devices, availability, backend)
        with self._lock:
            self._ensure_open()
            self._registry.get(component_id)
            if component_id in self._execution_selections or component_id in self._used_component_ids:
                raise ValidationError("cannot change simulation adapter after execution selection")
            if component_id in self._simulation_adapters:
                raise ValidationError("simulation adapter is already registered")
            self._simulation_adapters[component_id] = adapter

    def execution_selection(self, component_id: str) -> ExecutionSelection | None:
        with self._lock:
            return self._execution_selections.get(component_id)

    def execution_report(self) -> dict[str, object]:
        """Return payload-free execution provenance, also available after close."""
        with self._lock:
            return {
                "simulation_enabled": self._simulation,
                "selections": [self._execution_selections[key].as_dict()
                               for key in sorted(self._execution_selections)],
            }

    def resolve_execution(self, component_id: str) -> ExecutionSelection:
        """Select and pin an implementation before its first Task or Actor call."""
        with self._lock:
            self._ensure_open()
            if component_id in self._execution_selections:
                return self._execution_selections[component_id]
            original = self._registry.get(component_id)
            adapter = self._simulation_adapters.get(component_id)
            devices = (adapter.required_devices if adapter and adapter.required_devices
                       else requested_devices(original.spec.resources))
            available = True
            if self._simulation:
                if adapter and adapter.availability is not None:
                    available = adapter.availability()
                    if type(available) is not bool:
                        raise TypeError("simulation availability must return a bool")
                    if available:
                        # A configured HTTP device need not advertise a QPU
                        # token, but its explicit placement constraints must
                        # still match a live node's total capacity.
                        available = self._has_capacity(original.spec.resources, ())
                elif devices != ("CPU",):
                    available = self._has_capacity(original.spec.resources, devices)
            simulated = self._simulation and not available
            if simulated and adapter is None:
                raise UnavailableError(f"hardware is unavailable and no simulation adapter is registered for {component_id!r}")
            effective = adapter.resources if simulated else original.spec.resources
            selection = ExecutionSelection(
                component_id, simulated,
                "simulation_disabled" if not self._simulation else
                ("hardware_unavailable" if simulated else "hardware_available"),
                adapter.backend if simulated else "native", devices,
                ("CPU",) if simulated else devices, original.spec.resources, effective,
            )
            if simulated:
                self._registry.replace_registration(original, ComponentRegistration(
                    replace(original.spec, resources=effective), adapter.factory,
                ))
            self._requested_registrations[component_id] = original
            self._execution_selections[component_id] = selection
            return selection

    def _has_capacity(self, resources: ResourceRequest, devices: tuple[str, ...]) -> bool:
        capacity_reader = getattr(self._executor, "resource_capacities", None)
        if not callable(capacity_reader):
            raise ValidationError("simulation requires executor.resource_capacities()")
        return has_device_capacity(resources, devices, capacity_reader())

    @property
    def closed(self) -> bool:
        return self._executor.closed

    @property
    def registry(self) -> ComponentRegistry:
        return self._registry

    def register(
        self,
        spec: ComponentSpec,
        factory: ComponentFactory,
    ) -> ComponentRegistration:
        """Register an external component without constructing it."""

        self._ensure_open()
        return self._registry.register(spec, factory)

    def unregister(self, component_id: str) -> ComponentRegistration:
        """Remove an unused registration through the shared registry."""

        with self._lock:
            self._ensure_open()
            if component_id in self._used_component_ids:
                raise ValidationError(
                    "cannot unregister a component after this façade has "
                    "submitted it; close the executor first"
                )
            removed = self._registry.unregister(component_id)
            self._simulation_adapters.pop(component_id, None)
            self._execution_selections.pop(component_id, None)
            return self._requested_registrations.pop(component_id, removed)

    def describe(self, component_id: str) -> ComponentSpec:
        """Return framework registration metadata without invoking a component."""

        self._ensure_open()
        return self._requested_registrations.get(component_id, self._registry.get(component_id)).spec

    def reference(self, handle: InvocationHandle) -> ResultRef:
        """Return a value placeholder for a façade-owned handle."""

        with self._lock:
            self._ensure_open()
            return self._own_result_ref(handle)

    def submit(
        self,
        component_id: str,
        method: str,
        /,
        *args: Any,
        invocation_id: str,
        dependencies: Iterable[
            str | ResultRef | InvocationHandle
        ] = (),
        deadline: datetime | None = None,
        trace_context: StringMetadata | None = None,
        **kwargs: Any,
    ) -> InvocationHandle:
        """Submit one call, inferring dependencies from handles/ResultRefs."""

        invocation = InvocationSpec(
            invocation_id=invocation_id,
            component_id=component_id,
            method=method,
            args=args,
            kwargs=kwargs,
            dependencies=_dependency_ids(dependencies),
            deadline=deadline,
            trace_context=trace_context or StringMetadata(),
        )
        with self._lock:
            self._ensure_open()
            normalized = self._normalize_invocation(invocation)
            return self._submit_normalized(normalized)

    def invoke(
        self,
        component_id: str,
        method: str,
        /,
        *args: Any,
        invocation_id: str,
        dependencies: Iterable[
            str | ResultRef | InvocationHandle
        ] = (),
        deadline: datetime | None = None,
        trace_context: StringMetadata | None = None,
        **kwargs: Any,
    ) -> InvocationResult:
        """Submit and synchronously resolve one component call."""

        handle = self.submit(
            component_id,
            method,
            *args,
            invocation_id=invocation_id,
            dependencies=dependencies,
            deadline=deadline,
            trace_context=trace_context,
            **kwargs,
        )
        return self.result(handle)

    def submit_graph(
        self,
        invocations: Iterable[InvocationSpec],
    ) -> tuple[InvocationHandle, ...]:
        """Validate a DAG completely, then submit it in topological order.

        Structural graph errors are rejected before any node is submitted.
        Executor submission itself is intentionally not transactional.
        """

        if isinstance(invocations, (str, bytes)):
            raise TypeError("invocations must be an iterable of InvocationSpec")
        try:
            frozen = tuple(invocations)
        except TypeError as error:
            raise TypeError(
                "invocations must be an iterable of InvocationSpec"
            ) from error

        with self._lock:
            self._ensure_open()
            normalized = tuple(
                self._normalize_invocation(invocation)
                for invocation in frozen
            )
            existing_ids = tuple(self._handles)
            duplicates = tuple(
                invocation.invocation_id
                for invocation in normalized
                if invocation.invocation_id in self._handles
            )
            if duplicates:
                raise ValidationError(
                    "invocations already exist in this façade: "
                    + ", ".join(repr(item) for item in duplicates)
                )

            graph = InvocationGraph(
                normalized,
                external_dependencies=existing_ids,
            )
            for invocation in graph.invocations:
                self._validate_registration(invocation)
                if self._simulation:
                    self.resolve_execution(invocation.component_id)

            handles: list[InvocationHandle] = []
            for invocation in graph.topological_order():
                handles.append(self._submit_normalized(invocation))
            return tuple(handles)

    def result(self, handle: InvocationHandle) -> InvocationResult:
        """Resolve a façade-owned asynchronous handle."""

        with self._lock:
            self._owned_handle(handle)
        return self._executor.result(handle)

    def release(self, handle: InvocationHandle) -> None:
        """Release one completed result and its façade bookkeeping."""

        with self._lock:
            owned = self._owned_handle(handle)
        self._executor.release(owned)
        with self._lock:
            if self._handles.get(owned.invocation_id) is owned:
                self._handles.pop(owned.invocation_id, None)
                self._invocations.pop(owned.invocation_id, None)

    def submitted_handles(self) -> tuple[InvocationHandle, ...]:
        """Snapshot owned submissions, including a partially submitted graph."""
        with self._lock:
            return tuple(self._handles.values())

    def close(self) -> None:
        """Close the executor without closing caller-owned registrations."""

        self._executor.close()

    def __enter__(self) -> FusionFramework:
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _normalize_invocation(
        self,
        invocation: InvocationSpec,
    ) -> InvocationSpec:
        if not isinstance(invocation, InvocationSpec):
            raise TypeError("invocations must contain only InvocationSpec")
        args = _normalize_handle_references(
            invocation.args,
            self._own_result_ref,
        )
        kwargs = _normalize_handle_references(
            invocation.kwargs_dict(),
            self._own_result_ref,
        )
        referenced = result_ref_ids((args, kwargs))
        dependencies = list(invocation.dependencies)
        dependencies.extend(
            invocation_id
            for invocation_id in referenced
            if invocation_id not in dependencies
        )
        try:
            return InvocationSpec(
                invocation_id=invocation.invocation_id,
                component_id=invocation.component_id,
                method=invocation.method,
                args=args,
                kwargs=kwargs,
                dependencies=dependencies,
                deadline=invocation.deadline,
                trace_context=invocation.trace_context,
                schema_version=invocation.schema_version,
            )
        except (TypeError, ValueError) as error:
            raise ValidationError(
                str(error),
                framework_job_id=invocation.invocation_id,
            ) from None

    def _validate_registration(self, invocation: InvocationSpec) -> None:
        registration = self._registry.get(invocation.component_id)
        try:
            validate_invocation(registration.spec, invocation)
        except (TypeError, ValueError) as error:
            raise ValidationError(
                str(error),
                framework_job_id=invocation.invocation_id,
            ) from None

    def _submit_normalized(
        self,
        invocation: InvocationSpec,
    ) -> InvocationHandle:
        if self._simulation:
            selection = self.resolve_execution(invocation.component_id)
            invocation = replace(invocation, trace_context=StringMetadata.from_mapping(
                {**invocation.trace_context.as_dict(), **selection.trace_metadata()},
            ))
        self._validate_registration(invocation)
        if invocation.invocation_id in self._handles:
            raise ValidationError(
                f"invocation {invocation.invocation_id!r} already exists",
                framework_job_id=invocation.invocation_id,
            )
        handle = self._executor.submit(invocation)
        self._handles[invocation.invocation_id] = handle
        self._invocations[invocation.invocation_id] = invocation
        self._used_component_ids.add(invocation.component_id)
        return handle

    def _own_result_ref(self, handle: InvocationHandle) -> ResultRef:
        self._owned_handle(handle)
        return ResultRef.from_handle(handle)

    def _owned_handle(
        self,
        handle: InvocationHandle,
    ) -> InvocationHandle:
        if not isinstance(handle, InvocationHandle):
            raise TypeError("handle must be an InvocationHandle")
        owned = self._handles.get(handle.invocation_id)
        if (
            owned is None
            or owned.component_id != handle.component_id
            or owned.reference != handle.reference
        ):
            raise ValidationError(
                "invocation handle is not owned by this façade",
                framework_job_id=handle.invocation_id,
            )
        return owned

    def _ensure_open(self) -> None:
        if self._executor.closed:
            raise UnavailableError("fusion framework is closed")


def _dependency_ids(
    dependencies: Iterable[str | ResultRef | InvocationHandle],
) -> tuple[str, ...]:
    if isinstance(dependencies, (str, bytes)):
        raise TypeError(
            "dependencies must be an iterable of IDs, ResultRef, or handles"
        )
    try:
        frozen = tuple(dependencies)
    except TypeError as error:
        raise TypeError(
            "dependencies must be an iterable of IDs, ResultRef, or handles"
        ) from error

    normalized: list[str] = []
    for dependency in frozen:
        if isinstance(dependency, str):
            invocation_id = dependency
        elif isinstance(dependency, ResultRef):
            invocation_id = dependency.invocation_id
        elif isinstance(dependency, InvocationHandle):
            invocation_id = dependency.invocation_id
        else:
            raise TypeError(
                "dependencies must contain only IDs, ResultRef, or handles"
            )
        if invocation_id in normalized:
            raise ValueError("dependencies must not contain duplicates")
        normalized.append(invocation_id)
    return tuple(normalized)


__all__ = ["FusionFramework"]
