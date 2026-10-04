"""Result references and validation for framework-owned invocation DAGs."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from pivotq._internal.errors import ExecutionError, ValidationError

from .models import InvocationHandle, InvocationResult, InvocationSpec


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True, slots=True)
class ResultRef:
    """A framework-owned placeholder for one successful invocation value."""

    invocation_id: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "invocation_id",
            _require_invocation_id(self.invocation_id),
        )
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
        ):
            raise TypeError("schema_version must be an integer")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be greater than zero")

    @classmethod
    def from_handle(cls, handle: InvocationHandle) -> ResultRef:
        """Create a reference without exposing the executor-owned token."""

        if not isinstance(handle, InvocationHandle):
            raise TypeError("handle must be an InvocationHandle")
        return cls(handle.invocation_id)


class InvocationGraph:
    """A validated, immutable view of a closed or externally rooted DAG.

    Dependencies outside ``invocations`` must be declared through
    ``external_dependencies``.  Result references must also appear in the
    corresponding invocation's dependency IDs, which lets executors transport
    values without inspecting arbitrary component payload objects.
    """

    __slots__ = (
        "_external_dependencies",
        "_invocations",
        "_topological_order",
    )

    def __init__(
        self,
        invocations: Iterable[InvocationSpec],
        *,
        external_dependencies: Iterable[str] = (),
    ) -> None:
        if isinstance(invocations, (str, bytes)):
            raise TypeError("invocations must be an iterable of InvocationSpec")
        try:
            frozen = tuple(invocations)
        except TypeError as error:
            raise TypeError(
                "invocations must be an iterable of InvocationSpec"
            ) from error
        if not all(isinstance(item, InvocationSpec) for item in frozen):
            raise TypeError("invocations must contain only InvocationSpec")

        nodes: dict[str, InvocationSpec] = {}
        for invocation in frozen:
            if invocation.invocation_id in nodes:
                raise ValidationError(
                    f"invocation {invocation.invocation_id!r} appears twice",
                    framework_job_id=invocation.invocation_id,
                )
            nodes[invocation.invocation_id] = invocation

        external = _freeze_external_dependencies(external_dependencies)
        available = set(nodes) | set(external)
        for invocation in frozen:
            referenced = result_ref_ids(
                (invocation.args, invocation.kwargs)
            )
            undeclared = tuple(
                item
                for item in referenced
                if item not in invocation.dependencies
            )
            if undeclared:
                raise ValidationError(
                    "result references must also be declared as dependencies: "
                    + ", ".join(repr(item) for item in undeclared),
                    framework_job_id=invocation.invocation_id,
                )

            missing = tuple(
                dependency
                for dependency in invocation.dependencies
                if dependency not in available
            )
            if missing:
                raise ValidationError(
                    "invocation dependencies are not present in the graph: "
                    + ", ".join(repr(item) for item in missing),
                    framework_job_id=invocation.invocation_id,
                )

        self._invocations = frozen
        self._external_dependencies = external
        self._topological_order = _topological_order(frozen, nodes)

    @property
    def invocations(self) -> tuple[InvocationSpec, ...]:
        return self._invocations

    @property
    def external_dependencies(self) -> tuple[str, ...]:
        return self._external_dependencies

    def topological_order(self) -> tuple[InvocationSpec, ...]:
        """Return a stable dependency-before-dependent submission order."""

        return self._topological_order


def result_ref_ids(value: object) -> tuple[str, ...]:
    """Find references in plain framework-owned containers.

    Component-specific objects remain opaque.  Only exact ``tuple``, ``list``
    and ``dict`` instances are traversed.  References in dictionary keys are
    rejected because an injected result is not guaranteed to be hashable.
    """

    ordered: list[str] = []
    seen_ids: set[str] = set()
    visited_containers: set[int] = set()

    def visit(candidate: object, *, dictionary_key: bool = False) -> None:
        if isinstance(candidate, ResultRef):
            if dictionary_key:
                raise ValidationError(
                    "result references cannot be used in dictionary keys"
                )
            if candidate.invocation_id not in seen_ids:
                seen_ids.add(candidate.invocation_id)
                ordered.append(candidate.invocation_id)
            return

        candidate_type = type(candidate)
        if candidate_type not in (tuple, list, dict):
            return
        container_id = id(candidate)
        if container_id in visited_containers:
            return
        visited_containers.add(container_id)

        if candidate_type is dict:
            for key, item in candidate.items():  # type: ignore[union-attr]
                visit(key, dictionary_key=True)
                visit(item)
        else:
            for item in candidate:  # type: ignore[union-attr]
                visit(item)

    visit(value)
    return tuple(ordered)


def resolve_result_references(
    value: Any,
    dependency_results: tuple[object, ...],
) -> Any:
    """Replace ``ResultRef`` leaves with successful dependency values."""

    reference_ids = result_ref_ids(value)
    if not reference_ids:
        return value

    results_by_id: dict[str, InvocationResult] = {}
    for dependency_result in dependency_results:
        if not isinstance(dependency_result, InvocationResult):
            raise ExecutionError(
                "a dependency returned an invalid framework result"
            )
        results_by_id[dependency_result.invocation_id] = dependency_result

    for invocation_id in reference_ids:
        dependency_result = results_by_id.get(invocation_id)
        if dependency_result is None:
            raise ExecutionError(
                f"result reference {invocation_id!r} is not a dependency"
            )
        if not dependency_result.succeeded:
            raise ExecutionError(
                f"result reference {invocation_id!r} did not succeed"
            )

    return _replace_references(
        value,
        lambda reference: results_by_id[reference.invocation_id].value,
        active_containers=set(),
    )[0]


def _normalize_handle_references(
    value: Any,
    resolve_handle: Callable[[InvocationHandle], ResultRef],
) -> Any:
    """Convert façade-owned handles while preserving opaque leaf objects."""

    if not callable(resolve_handle):
        raise TypeError("resolve_handle must be callable")
    if not _contains_handle(value):
        return value
    return _replace_handles(
        value,
        resolve_handle,
        active_containers=set(),
    )[0]


def _replace_references(
    value: Any,
    resolve: Callable[[ResultRef], Any],
    *,
    active_containers: set[int],
) -> tuple[Any, bool]:
    if isinstance(value, ResultRef):
        return resolve(value), True
    if not result_ref_ids(value):
        return value, False

    value_type = type(value)
    if value_type not in (tuple, list, dict):
        return value, False
    container_id = id(value)
    if container_id in active_containers:
        raise ExecutionError(
            "cyclic plain containers cannot contain result references"
        )
    active_containers.add(container_id)
    try:
        if value_type is dict:
            changed = False
            normalized: dict[Any, Any] = {}
            for key, item in value.items():
                resolved, item_changed = _replace_references(
                    item,
                    resolve,
                    active_containers=active_containers,
                )
                normalized[key] = resolved
                changed = changed or item_changed
            return (normalized, True) if changed else (value, False)

        normalized_items: list[Any] = []
        changed = False
        for item in value:
            resolved, item_changed = _replace_references(
                item,
                resolve,
                active_containers=active_containers,
            )
            normalized_items.append(resolved)
            changed = changed or item_changed
        if not changed:
            return value, False
        if value_type is tuple:
            return tuple(normalized_items), True
        return normalized_items, True
    finally:
        active_containers.remove(container_id)


def _contains_handle(value: object) -> bool:
    visited_containers: set[int] = set()

    def visit(candidate: object, *, dictionary_key: bool = False) -> bool:
        if isinstance(candidate, InvocationHandle):
            if dictionary_key:
                raise ValidationError(
                    "invocation handles cannot be used in dictionary keys"
                )
            return True
        candidate_type = type(candidate)
        if candidate_type not in (tuple, list, dict):
            return False
        container_id = id(candidate)
        if container_id in visited_containers:
            return False
        visited_containers.add(container_id)
        if candidate_type is dict:
            found = False
            for key, item in candidate.items():  # type: ignore[union-attr]
                found = visit(key, dictionary_key=True) or found
                found = visit(item) or found
            return found
        return any(visit(item) for item in candidate)  # type: ignore[union-attr]

    return visit(value)


def _replace_handles(
    value: Any,
    resolve: Callable[[InvocationHandle], ResultRef],
    *,
    active_containers: set[int],
) -> tuple[Any, bool]:
    if isinstance(value, InvocationHandle):
        return resolve(value), True
    if not _contains_handle(value):
        return value, False

    value_type = type(value)
    if value_type not in (tuple, list, dict):
        return value, False
    container_id = id(value)
    if container_id in active_containers:
        raise ValidationError(
            "cyclic plain containers cannot contain invocation handles"
        )
    active_containers.add(container_id)
    try:
        if value_type is dict:
            changed = False
            normalized: dict[Any, Any] = {}
            for key, item in value.items():
                resolved, item_changed = _replace_handles(
                    item,
                    resolve,
                    active_containers=active_containers,
                )
                normalized[key] = resolved
                changed = changed or item_changed
            return (normalized, True) if changed else (value, False)

        normalized_items: list[Any] = []
        changed = False
        for item in value:
            resolved, item_changed = _replace_handles(
                item,
                resolve,
                active_containers=active_containers,
            )
            normalized_items.append(resolved)
            changed = changed or item_changed
        if not changed:
            return value, False
        if value_type is tuple:
            return tuple(normalized_items), True
        return normalized_items, True
    finally:
        active_containers.remove(container_id)


def _topological_order(
    invocations: tuple[InvocationSpec, ...],
    nodes: dict[str, InvocationSpec],
) -> tuple[InvocationSpec, ...]:
    indegrees: dict[str, int] = {}
    dependents: dict[str, list[str]] = {
        invocation_id: [] for invocation_id in nodes
    }
    for invocation in invocations:
        internal_dependencies = tuple(
            dependency
            for dependency in invocation.dependencies
            if dependency in nodes
        )
        indegrees[invocation.invocation_id] = len(internal_dependencies)
        for dependency in internal_dependencies:
            dependents[dependency].append(invocation.invocation_id)

    ready = deque(
        invocation.invocation_id
        for invocation in invocations
        if indegrees[invocation.invocation_id] == 0
    )
    ordered_ids: list[str] = []
    while ready:
        invocation_id = ready.popleft()
        ordered_ids.append(invocation_id)
        for dependent in dependents[invocation_id]:
            indegrees[dependent] -= 1
            if indegrees[dependent] == 0:
                ready.append(dependent)

    if len(ordered_ids) != len(invocations):
        cyclic_ids = tuple(
            invocation.invocation_id
            for invocation in invocations
            if indegrees[invocation.invocation_id] > 0
        )
        raise ValidationError(
            "invocation graph contains a dependency cycle: "
            + ", ".join(repr(item) for item in cyclic_ids)
        )
    return tuple(nodes[invocation_id] for invocation_id in ordered_ids)


def _freeze_external_dependencies(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(
            "external_dependencies must be an iterable of invocation IDs"
        )
    try:
        frozen = tuple(_require_invocation_id(value) for value in values)
    except TypeError as error:
        raise TypeError(
            "external_dependencies must be an iterable of invocation IDs"
        ) from error
    if len(set(frozen)) != len(frozen):
        raise ValueError("external_dependencies must not contain duplicates")
    return frozen


def _require_invocation_id(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("invocation_id must be a string")
    if _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(
            "invocation_id must start with an alphanumeric character and "
            "contain only alphanumerics, '_', '-' or '.' "
            "(maximum 128 characters)"
        )
    return value


__all__ = [
    "InvocationGraph",
    "ResultRef",
    "resolve_result_references",
    "result_ref_ids",
]
