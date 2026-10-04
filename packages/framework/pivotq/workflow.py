"""Reusable, explicit execution DAGs; performance models are maintained separately."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import pickle
from threading import RLock
from types import MappingProxyType
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from .errors import PivotQError, ValidationError
from .refs import ResultRef

if TYPE_CHECKING:
    from .runtime import Runtime


@dataclass(frozen=True, slots=True, eq=False)
class NodeRef:
    """A value in a Workflow, not an already submitted runtime result."""

    _workflow_id: str
    name: str
    _input: bool = False

    def __bool__(self) -> bool:
        raise TypeError("Workflow references are values resolved when the workflow runs")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("Workflow references must be in plain argument containers")


@dataclass(frozen=True)
class _Node:
    ref: NodeRef
    kind: str
    target: Any
    method: str | None
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    num_cpus: float = 1


def _walk(value: Any, replace: Callable[[Any], Any], active: set[int] | None = None,
          *, key: bool = False, snapshot: bool = False) -> Any:
    if isinstance(value, (NodeRef, ResultRef)):
        if key:
            raise ValidationError("references cannot be dictionary keys")
        return replace(value)
    if type(value) not in (tuple, list, dict):
        if snapshot:
            try:
                return pickle.loads(pickle.dumps(value))
            except Exception:
                raise ValidationError("workflow literal arguments must be pickle-serializable values") from None
        return value
    active = set() if active is None else active
    if id(value) in active:
        raise ValidationError("cyclic workflow argument containers are not supported")
    active.add(id(value))
    try:
        if type(value) is dict:
            return {_walk(k, replace, active, key=True, snapshot=snapshot):
                    _walk(v, replace, active, key=key, snapshot=snapshot)
                    for k, v in value.items()}
        result = [_walk(item, replace, active, key=key, snapshot=snapshot) for item in value]
        return tuple(result) if type(value) is tuple else result
    finally:
        active.remove(id(value))


class Workflow:
    """Build once, then run with different inputs and Runtime-local bindings.

    Nodes may reference earlier nodes and declared inputs. This guarantees a
    DAG by construction. Its first validated submission freezes its structure.
    Literal arguments are snapshotted when nodes are added. Python loops and
    conditionals remain outside the Workflow.
    """

    def __init__(self, name: str = "workflow") -> None:
        self.name = _name(name)
        self._id = uuid4().hex
        self._inputs: dict[str, NodeRef] = {}
        self._nodes: dict[str, _Node] = {}
        self._outputs: dict[str, NodeRef] = {}
        self._frozen = False
        self._lock = RLock()

    def _editable(self) -> None:
        if self._frozen:
            raise ValidationError("workflow structure is frozen after its first submission")

    def input(self, name: str) -> NodeRef:
        with self._lock:
            self._editable()
            name = _name(name)
            if name in self._inputs or name in self._nodes:
                raise ValidationError(f"duplicate workflow value name {name!r}")
            ref = NodeRef(self._id, name, True)
            self._inputs[name] = ref
            return ref

    def _reference(self, ref: Any) -> NodeRef:
        if not isinstance(ref, NodeRef) or ref._workflow_id != self._id:
            raise ValidationError("workflow arguments must use references from this workflow")
        owned = self._inputs.get(ref.name) if ref._input else getattr(self._nodes.get(ref.name), "ref", None)
        if owned is not ref:
            raise ValidationError("workflow reference is not an existing input or earlier node")
        return ref

    def _add(self, kind: str, target: Any, method: str | None, args: tuple[Any, ...],
             kwargs: Mapping[str, Any] | None, name: str | None, num_cpus: float = 1) -> NodeRef:
        with self._lock:
            self._editable()
            name = _name(name if name is not None else f"node-{len(self._nodes) + 1}")
            if name in self._nodes or name in self._inputs:
                raise ValidationError(f"duplicate workflow value name {name!r}")
            if kwargs is not None and (not isinstance(kwargs, Mapping)
                    or any(not isinstance(key, str) for key in kwargs)):
                raise TypeError("kwargs must be a mapping with string keys")
            args, keywords = _walk((args, dict(kwargs or {})), self._reference, snapshot=True)
            ref = NodeRef(self._id, name)
            self._nodes[name] = _Node(ref, kind, target, method, args, keywords, num_cpus)
            return ref

    def task(self, fn: Callable[..., Any], /, *args: Any, num_cpus: float = 1,
             kwargs: Mapping[str, Any] | None = None, name: str | None = None) -> NodeRef:
        return self._add("task", fn, None, args, kwargs, name, num_cpus)

    def component(self, binding: str, method: str, /, *args: Any,
                  kwargs: Mapping[str, Any] | None = None, name: str | None = None) -> NodeRef:
        return self._add("component", _name(binding), _name(method), args, kwargs, name)

    def quantum(self, binding: str, circuit: Any, *, shots: int = 1024,
                seed: int | None = None, name: str | None = None) -> NodeRef:
        return self._add("quantum", _name(binding), None, (circuit,),
                         {"shots": shots, "seed": seed}, name)

    def output(self, name: str, ref: NodeRef) -> None:
        with self._lock:
            self._editable()
            name = _name(name)
            self._reference(ref)
            if ref._input:
                raise ValidationError("workflow outputs must reference computation nodes")
            if name in self._outputs:
                raise ValidationError(f"duplicate workflow output {name!r}")
            self._outputs[name] = ref


class WorkflowRun:
    """References for one run, including intermediates needed for release."""

    def __init__(self, runtime: Runtime, run_id: str, name: str,
                 outputs: Mapping[str, ResultRef[Any]], refs: tuple[ResultRef[Any], ...]) -> None:
        self._runtime = runtime
        self.run_id, self.name = run_id, name
        self.outputs = MappingProxyType(dict(outputs))
        self.refs = refs

    def release(self) -> None:
        """Release all completed invocations belonging to this run."""
        self._runtime.release(*self.refs)


class WorkflowSubmissionError(PivotQError):
    """Submission stopped after some nodes were accepted; inspect partial_run."""

    code = "workflow_submission_failed"

    def __init__(self, partial_run: WorkflowRun) -> None:
        super().__init__("workflow submission failed; accepted references are in partial_run")
        self.partial_run = partial_run


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("name must be nonempty text")
    return value


__all__ = ["Workflow", "WorkflowRun", "NodeRef", "WorkflowSubmissionError"]
