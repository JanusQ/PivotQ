"""Adapt ordinary Python callables to the internal component protocol."""

from dataclasses import dataclass
from typing import Any, Callable


class FunctionComponent:
    def __init__(self, function: Callable[..., Any]) -> None:
        self._function = function

    def describe(self) -> dict[str, str]:
        return {"kind": "python-function"}

    def run(self, *args: Any, **kwargs: Any) -> Any:
        return self._function(*args, **kwargs)


@dataclass(frozen=True)
class FunctionFactory:
    # The callable travels in registration metadata, where Ray uses cloudpickle.
    # Invocation payloads retain the existing standard-pickle contract.
    function: Callable[..., Any]

    def __call__(self) -> FunctionComponent:
        return FunctionComponent(self.function)
