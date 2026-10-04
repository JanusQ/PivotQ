"""References to values owned by one PivotQ runtime."""

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True, eq=False)
class ResultRef(Generic[T]):
    """A pending value; use ``runtime.get(ref)`` to obtain its result.

    References belong to their creating runtime and are not transport payloads.
    Pass them directly, or inside plain lists, tuples, or dictionary values.
    """

    _runtime_id: str
    _invocation_id: str

    def __bool__(self) -> bool:
        raise TypeError("use runtime.get(ref) before testing a result")

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("ResultRef must be passed through its owning runtime")

    def __repr__(self) -> str:
        return f"ResultRef({self._invocation_id!r})"


__all__ = ["ResultRef"]
