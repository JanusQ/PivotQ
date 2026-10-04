"""Small Python programming interface over PivotQ's component executors."""

from collections.abc import Callable, Mapping
import inspect
import math
import pickle
import copy
from numbers import Real
from threading import RLock
from typing import Any, TypeVar
from uuid import uuid4

from ._function import FunctionFactory
from ._internal.framework import (
    ComponentRegistry, ComponentSpec as InternalComponentSpec, ExecutionMode, FusionFramework,
    InvocationHandle, ResourceRequest, InvocationSpec, InvocationGraph,
    ResultRef as InternalResultRef,
)
from ._internal.framework.graph import result_ref_ids
from ._internal.models import StringMetadata
from ._internal.observability import TraceCollector
from .components import ComponentSpec, ComponentHandle, _ComponentFactory, _ActorFactory
from .errors import UnavailableError, ValidationError
from .observability import ExecutionReport, InvocationStatus, _public_trace
from .refs import ResultRef

T = TypeVar("T")


class Runtime:
    """Run CPU functions and explicit quantum backends.

    Construction is lazy. Entering a context or submitting work starts the
    executor. Local execution uses threads and may wait for dependencies during
    submission; Ray schedules dependencies remotely. ``max_workers`` applies to
    local execution. CPU quantities express requested placement, not hard CPU
    usage limits for a Python function.
    """

    def __init__(self, executor: str = "local", *, address: str | None = None,
                 max_workers: int = 4, trace: bool = False,
                 trace_max_records: int = 10_000) -> None:
        if executor not in ("local", "ray"):
            raise ValueError("executor must be 'local' or 'ray'")
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers <= 0:
            raise ValueError("max_workers must be a positive integer")
        if address is not None and (not isinstance(address, str) or not address.strip()):
            raise ValueError("address must be a nonempty string or None")
        if executor == "local" and address is not None:
            raise ValueError("address is only supported with executor='ray'")
        if executor == "ray" and max_workers != 4:
            raise ValueError("max_workers is only configurable for executor='local'")
        if type(trace) is not bool:
            raise TypeError("trace must be a bool")
        self._executor_name = executor
        self._max_workers = max_workers
        self._address = address
        self._runtime_id = uuid4().hex
        self._sequence = 0
        self._lock = RLock()
        self._closed = False
        self._registry: ComponentRegistry | None = None
        self._framework: FusionFramework | None = None
        self._executor: Any = None
        self._ray_lease: str | None = None
        self._registrations: dict[tuple[int, float], str] = {}
        self._handles: dict[str, InvocationHandle] = {}
        self._refs: dict[str, ResultRef[Any]] = {}
        self._components: dict[str, ComponentHandle] = {}
        self._backend_registrations: dict[str, Any] = {}
        self._backend_descriptions: list[dict[str, Any]] = []
        self._component_labels: dict[str, dict[str, str]] = {}
        self._trace_collector = TraceCollector(max_records=trace_max_records) if trace else None
        self._resource_snapshot: dict[str, Any] = {
            "executor": executor, "capacity_kind": "logical total capacity",
            "nodes": [], "quantum_backends": [],
        }

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def executor(self) -> str:
        return self._executor_name

    @property
    def max_workers(self) -> int:
        return self._max_workers

    def _ensure_started(self) -> None:
        with self._lock:
            if self._closed:
                raise UnavailableError("PivotQ runtime is closed")
            if self._framework is not None:
                return
            registry = ComponentRegistry()
            lease = None
            try:
                if self.executor == "local":
                    from ._internal.executors import LocalExecutor
                    executor = LocalExecutor(registry, max_workers=self.max_workers,
                                             trace_collector=self._trace_collector)
                else:
                    from . import _ray_lifecycle
                    _, lease = _ray_lifecycle.acquire(self._address)
                    from ._internal.executors import RayExecutor
                    executor = RayExecutor(registry, trace_collector=self._trace_collector)
                framework = FusionFramework(executor)
            except BaseException:
                registry.close()
                if lease is not None:
                    from . import _ray_lifecycle
                    _ray_lifecycle.release(lease)
                raise
            self._registry, self._executor = registry, executor
            self._framework, self._ray_lease = framework, lease

    def _new_component_id(self, prefix: str = "component") -> str:
        with self._lock:
            self._sequence += 1
            return f"{prefix}-{self._runtime_id}-{self._sequence}"

    def _check_resources(self, resources: ResourceRequest) -> None:
        self._ensure_started()
        if self.executor == "local":
            if resources.num_gpus or resources.custom_resources_dict():
                raise ValueError("local execution cannot allocate accelerator or custom resources")
            if resources.num_cpus > self.max_workers:
                raise ValueError("num_cpus exceeds local max_workers")
            return
        requested = {"CPU": resources.num_cpus, "GPU": resources.num_gpus,
                     **resources.custom_resources_dict()}
        if not any(all(capacity.get(key, 0) >= amount for key, amount in requested.items())
                   for capacity in self._executor.resource_capacities()):
            raise UnavailableError("no live Ray node has the requested resource capacity")

    def _register_component(self, spec: InternalComponentSpec, factory: Callable[[], object]) -> Any:
        with self._lock:
            self._ensure_started()
            self._check_resources(spec.resources)
            return self._framework.register(spec, factory)

    def _function_component(self, fn: Callable[..., Any], num_cpus: float) -> str:
        if not callable(fn):
            raise TypeError("fn must be callable")
        candidates = (fn, getattr(fn, "__call__", None))
        if any(inspect.iscoroutinefunction(item) or inspect.isgeneratorfunction(item)
               or inspect.isasyncgenfunction(item) for item in candidates):
            raise TypeError("submit requires a synchronous, non-generator function")
        if isinstance(num_cpus, bool) or not isinstance(num_cpus, Real) or not math.isfinite(num_cpus) or num_cpus <= 0:
            raise ValueError("num_cpus must be a finite positive number")
        resources = ResourceRequest(num_cpus=float(num_cpus))
        with self._lock:
            self._ensure_started()
            self._check_resources(resources)
            key = id(fn), resources.num_cpus
            component_id = self._registrations.get(key)
            if component_id is None:
                component_id = self._new_component_id("function")
                self._register_component(InternalComponentSpec(
                    component_id=component_id, execution=ExecutionMode.TASK,
                    resources=resources, allowed_methods=("run",),
                    max_concurrency=self.max_workers,
                ), FunctionFactory(fn))
                self._registrations[key] = component_id
                self._component_labels[component_id] = {
                    "component.name": getattr(fn, "__name__", type(fn).__name__),
                    "task.kind": "cpu",
                }
            return component_id

    def submit(self, fn: Callable[..., T], /, *args: Any, num_cpus: float = 1,
               kwargs: Mapping[str, Any] | None = None) -> ResultRef[T]:
        """Submit a synchronous CPU function; business keywords go in ``kwargs``.

        Functions must not capture runtime objects or live hardware connections.
        Arguments and returned values must be standard-pickle serializable.
        """
        with self._lock:
            component_id = self._function_component(fn, num_cpus)
            return self._submit_component(component_id, "run", *args, kwargs=kwargs)

    def register(self, spec: ComponentSpec, factory: Callable[[], object]) -> ComponentHandle:
        """Register an explicit CPU component without constructing its instance."""
        if not isinstance(spec, ComponentSpec):
            raise TypeError("spec must be a public pivotq.ComponentSpec")
        if not callable(factory):
            raise TypeError("factory must be callable")
        with self._lock:
            self._ensure_started()
            if any(handle.spec.name == spec.name for handle in self._components.values()):
                raise ValidationError(f"component name {spec.name!r} is already registered")
            component_id = self._new_component_id("component")
            self._register_component(InternalComponentSpec(
                component_id, ExecutionMode(spec.execution), ResourceRequest(num_cpus=spec.num_cpus),
                allowed_methods=spec.methods, stateful=spec.execution == "actor",
                max_concurrency=(spec.max_concurrency or 1) if spec.execution == "actor" else self.max_workers,
                timeout_seconds=spec.timeout_seconds,
                metadata=StringMetadata.from_mapping(spec.metadata_dict()),
            ), _ComponentFactory(factory, spec))
            handle = ComponentHandle(self, spec, component_id)
            self._components[component_id] = handle
            self._component_labels[component_id] = {
                "component.name": spec.name, "task.kind": "cpu",
                **{f"component.metadata.{key}": value for key, value in spec.metadata},
            }
            return handle

    def actor(self, constructor: Callable[..., object], /, *args: Any,
              methods: tuple[str, ...], name: str | None = None, num_cpus: float = 1,
              max_concurrency: int = 1, timeout_seconds: float | None = None,
              metadata: Mapping[str, str] | None = None,
              kwargs: Mapping[str, Any] | None = None) -> ComponentHandle:
        """Construct a reusable CPU actor in the executor on its first call."""
        if not callable(constructor):
            raise TypeError("constructor must be callable")
        if kwargs is not None and (not isinstance(kwargs, Mapping)
                or any(not isinstance(key, str) for key in kwargs)):
            raise TypeError("kwargs must be a mapping with string keys")
        keywords = dict(kwargs or {})
        try:
            pickle.dumps((args, keywords))
        except Exception:
            raise ValueError("actor constructor arguments must be ordinary pickle-serializable values") from None
        return self.register(ComponentSpec(
            name=name or self._new_component_id("actor"), methods=methods,
            execution="actor", num_cpus=num_cpus, max_concurrency=max_concurrency,
            timeout_seconds=timeout_seconds, metadata=metadata or {},
        ), _ActorFactory(constructor, args, keywords))

    def _owned_handle(self, ref: ResultRef[Any]) -> InvocationHandle:
        if not isinstance(ref, ResultRef):
            raise TypeError("expected a PivotQ ResultRef")
        if ref._runtime_id != self._runtime_id:
            raise ValidationError("result reference belongs to a different runtime")
        if self._refs.get(ref._invocation_id) is not ref:
            raise ValidationError("result reference was released or is not owned by this runtime")
        return self._handles[ref._invocation_id]

    def _convert_refs(self, value: Any, active: set[int] | None = None,
                      *, dictionary_key: bool = False) -> Any:
        if isinstance(value, ResultRef):
            if dictionary_key:
                raise ValidationError("result references cannot be dictionary keys")
            return self._owned_handle(value)
        if type(value) not in (tuple, list, dict):
            return value
        active = set() if active is None else active
        if id(value) in active:
            raise ValidationError("cyclic argument containers are not supported")
        active.add(id(value))
        try:
            if type(value) is dict:
                return {self._convert_refs(key, active, dictionary_key=True):
                        self._convert_refs(item, active, dictionary_key=dictionary_key)
                        for key, item in value.items()}
            items = [self._convert_refs(item, active, dictionary_key=dictionary_key)
                     for item in value]
            return tuple(items) if type(value) is tuple else items
        finally:
            active.remove(id(value))

    def _submit_component(self, component_id: str, method: str, /, *args: Any,
                          kwargs: Mapping[str, Any] | None = None) -> ResultRef[Any]:
        if kwargs is not None and not isinstance(kwargs, Mapping):
            raise TypeError("kwargs must be a mapping or None")
        if kwargs is not None and any(not isinstance(key, str) for key in kwargs):
            raise TypeError("kwargs keys must be strings")
        with self._lock:
            self._ensure_started()
            args = self._convert_refs(args)
            keywords = self._convert_refs(dict(kwargs or {}))
            invocation_id = self._new_component_id("call")
            # Pass an InvocationSpec via submit_graph so business keyword names
            # never collide with facade's invocation_id/dependencies/deadline.
            invocation = InvocationSpec(invocation_id, component_id, method,
                                        args=args, kwargs=keywords,
                                        trace_context=self._trace_context(component_id))
            handle, = self._framework.submit_graph((invocation,))
            return self._adopt_handle(handle)

    def _adopt_handle(self, handle: InvocationHandle) -> ResultRef[Any]:
        ref = ResultRef(self._runtime_id, handle.invocation_id)
        self._handles[handle.invocation_id] = handle
        self._refs[handle.invocation_id] = ref
        return ref

    def _trace_context(self, component_id: str, **metadata: str) -> StringMetadata:
        return StringMetadata.from_mapping({
            "trace_id": self._runtime_id,
            **self._component_labels.get(component_id, {}), **metadata,
        })

    def run(self, workflow: Any, *, inputs: Mapping[str, Any] | None = None,
            bindings: Mapping[str, Any] | None = None) -> Any:
        """Validate and submit one Workflow; repeated runs get fresh references."""
        from .workflow import Workflow, WorkflowRun, WorkflowSubmissionError, NodeRef, _walk
        from .quantum import QuantumBackend
        if not isinstance(workflow, Workflow):
            raise TypeError("workflow must be a Workflow")
        if inputs is not None and not isinstance(inputs, Mapping):
            raise TypeError("inputs must be a mapping")
        if bindings is not None and not isinstance(bindings, Mapping):
            raise TypeError("bindings must be a mapping")
        inputs, bindings = dict(inputs or {}), dict(bindings or {})
        with self._lock, workflow._lock:
            self._ensure_started()
            if set(inputs) != set(workflow._inputs):
                raise ValidationError("inputs must match the workflow's declared input names")
            if not workflow._outputs:
                raise ValidationError("workflow must declare at least one output")
            # References hidden in unsupported input objects fail pickle here.
            try:
                inputs = pickle.loads(pickle.dumps(inputs))
            except Exception:
                raise ValidationError("workflow inputs must be ordinary pickle-serializable values") from None
            nodes = tuple(workflow._nodes.values())
            expected_bindings = {node.target for node in nodes if node.kind != "task"}
            if set(bindings) != expected_bindings:
                raise ValidationError("bindings must match the workflow's component/backend aliases")
            run_id = self._new_component_id("workflow")
            invocation_ids = {node.ref.name: self._new_component_id("call") for node in nodes}

            def resolve(ref: Any) -> Any:
                workflow._reference(ref)
                return inputs[ref.name] if ref._input else InternalResultRef(invocation_ids[ref.name])

            invocations = []
            previous_serial_actor: dict[str, str] = {}
            for node in nodes:
                args, keywords = _walk((node.args, node.kwargs), resolve, snapshot=True)
                if node.kind == "task":
                    component_id, method = self._function_component(node.target, node.num_cpus), "run"
                elif node.kind == "component":
                    target = bindings[node.target]
                    if not isinstance(target, ComponentHandle) or target._runtime is not self or self._components.get(target._component_id) is not target:
                        raise ValidationError("component bindings must be handles owned by this runtime")
                    component_id, method = target._component_id, node.method
                else:
                    target = bindings[node.target]
                    if not isinstance(target, QuantumBackend) or target._runtime is not self:
                        raise ValidationError("quantum bindings must be backends owned by this runtime")
                    component_id, method, args, keywords = target._invocation_payload(*args, **keywords)
                spec = self._registry.get(component_id).spec
                if method not in spec.allowed_methods:
                    raise ValidationError(f"method {method!r} is not registered for this component")
                dependencies = list(result_ref_ids((args, keywords)))
                if spec.execution is ExecutionMode.ACTOR and spec.max_concurrency == 1:
                    previous = previous_serial_actor.get(component_id)
                    if previous is not None and previous not in dependencies:
                        dependencies.append(previous)
                    previous_serial_actor[component_id] = invocation_ids[node.ref.name]
                invocations.append(InvocationSpec(
                    invocation_ids[node.ref.name], component_id, method,
                    args=args, kwargs=keywords, dependencies=dependencies,
                    trace_context=self._trace_context(component_id, **{
                        "workflow.id": run_id, "workflow.name": workflow.name,
                        "workflow.node": node.ref.name,
                    }),
                ))
            InvocationGraph(invocations)
            workflow._frozen = True
            before = {handle.invocation_id for handle in self._framework.submitted_handles()}
            try:
                handles = self._framework.submit_graph(invocations)
            except Exception as error:
                handles = tuple(handle for handle in self._framework.submitted_handles()
                                if handle.invocation_id not in before)
                refs = tuple(self._adopt_handle(handle) for handle in handles)
                if not refs:
                    raise
                partial = WorkflowRun(self, run_id, workflow.name, {}, refs)
                raise WorkflowSubmissionError(partial) from error
            refs = tuple(self._adopt_handle(handle) for handle in handles)
            by_id = {ref._invocation_id: ref for ref in refs}
            outputs = {name: by_id[invocation_ids[ref.name]] for name, ref in workflow._outputs.items()}
            return WorkflowRun(self, run_id, workflow.name, outputs, refs)

    def get(self, ref: ResultRef[T]) -> T:
        """Wait for a result; repeated gets and reuse as dependencies are allowed."""
        with self._lock:
            self._ensure_started()
            handle = self._owned_handle(ref)
            framework = self._framework
        result = framework.result(handle)
        if not result.succeeded:
            raise result.error
        return result.value

    def release(self, *refs: ResultRef[Any]) -> None:
        """Release completed values after their last use; no implicit get occurs."""
        with self._lock:
            self._ensure_started()
            # Validate ownership before releasing any reference in the batch.
            handles = [(ref, self._owned_handle(ref)) for ref in refs]
            for ref, handle in handles:
                if ref._invocation_id not in self._handles:
                    continue
                self._framework.release(handle)
                self._handles.pop(ref._invocation_id)
                self._refs.pop(ref._invocation_id)

    def status(self, ref: ResultRef[Any]) -> InvocationStatus:
        """Return a terminal state, or pending (queued or running)."""
        with self._lock:
            self._ensure_started()
            handle, executor = self._owned_handle(ref), self._executor
        result = executor.poll(handle)
        return InvocationStatus.PENDING if result is None else InvocationStatus(result.status.value)

    def wait(self, refs: Any, *, num_returns: int = 1,
             timeout: float | None = None) -> tuple[tuple[ResultRef[Any], ...], tuple[ResultRef[Any], ...]]:
        """Wait for at least num_returns ready calls; timeout never cancels work."""
        refs = tuple(refs)
        with self._lock:
            self._ensure_started()
            handles = tuple(self._owned_handle(ref) for ref in refs)
            executor = self._executor
        ready, pending = executor.wait(handles, num_returns=num_returns, timeout=timeout)
        by_id = {ref._invocation_id: ref for ref in refs}
        return (tuple(by_id[handle.invocation_id] for handle in ready),
                tuple(by_id[handle.invocation_id] for handle in pending))

    def register_quantum_backend(self, name: str, factory: Callable[..., Any], *,
                                 capabilities: Any, execution: str | None = None,
                                 num_cpus: float | None = None) -> None:
        """Register a provider lazily; no device is contacted during registration."""
        from .providers import _make_registration
        with self._lock:
            if self._closed:
                raise UnavailableError("PivotQ runtime is closed")
            if name in ("simulator", "lab-qpu") or name in self._backend_registrations:
                raise ValidationError(f"quantum backend {name!r} is already registered")
            self._backend_registrations[name] = _make_registration(
                name, factory, capabilities=capabilities, execution=execution, num_cpus=num_cpus,
            )

    def quantum_backend(self, name: str, **config: Any) -> Any:
        """Configure an explicit quantum simulator or QPU backend."""
        self._ensure_started()
        from .quantum import QuantumBackend
        backend = QuantumBackend(self, name, **config)
        description = backend.describe()
        from dataclasses import asdict
        capabilities = asdict(description)
        with self._lock:
            self._backend_descriptions.append({"name": name, **capabilities})
            self._component_labels[backend._component_id] = {
                "component.name": name, "task.kind": "quantum", "quantum.backend": name,
                "quantum.is_simulated": str(description.is_simulated).lower(),
            }
        return backend

    def resources(self) -> dict[str, Any]:
        """Snapshot total CPU capacity and configured quantum capabilities.

        This is neither free capacity nor a hardware health probe. A closed
        runtime returns its last snapshot. GPU fields stay internal.
        """
        with self._lock:
            if not self._closed:
                self._ensure_started()
                self._resource_snapshot = {
                    "executor": self.executor, "capacity_kind": "logical total capacity",
                    "nodes": [{"num_cpus": node.get("CPU", 0)}
                              for node in self._executor.resource_capacities()],
                    "quantum_backends": copy.deepcopy(self._backend_descriptions),
                }
            return copy.deepcopy(self._resource_snapshot)

    def report(self) -> ExecutionReport:
        """Snapshot retained terminal traces, available even after close/release."""
        with self._lock:
            if self._executor is not None:
                self._executor.flush_traces()
            resources = self.resources()
            collector = self._trace_collector
            records = () if collector is None else tuple(_public_trace(record) for record in collector.snapshot())
            return ExecutionReport(self._runtime_id, self.executor, self._closed,
                                   collector is not None, records,
                                   0 if collector is None else collector.dropped_records, resources)

    def close(self) -> None:
        """Close components and release this runtime's Ray connection lease."""
        with self._lock:
            if self._closed:
                return
            if self._executor is not None:
                try:
                    self.resources()
                except Exception:
                    pass  # Cleanup must continue if Ray has disconnected.
            self._closed = True
            errors: list[BaseException] = []
            try:
                if self._framework is not None:
                    self._framework.close()
            except BaseException as error:
                errors.append(error)
            try:
                if self._registry is not None:
                    self._registry.close()
            except BaseException as error:
                errors.append(error)
            try:
                if self._ray_lease is not None:
                    from . import _ray_lifecycle
                    _ray_lifecycle.release(self._ray_lease)
            except BaseException as error:
                errors.append(error)
            finally:
                self._handles.clear()
                self._refs.clear()
                self._registrations.clear()
                self._components.clear()
                self._component_labels.clear()
                self._backend_registrations.clear()
                self._framework = self._registry = self._executor = None
                self._ray_lease = None
            if errors:
                for extra in errors[1:]:
                    errors[0].add_note(f"additional cleanup failure: {type(extra).__name__}")
                raise errors[0]

    def __enter__(self) -> "Runtime":
        self._ensure_started()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        try:
            self.close()
        except BaseException as error:
            if exc_value is None:
                raise
            exc_value.add_note(f"PivotQ cleanup also failed: {type(error).__name__}")


__all__ = ["Runtime"]
