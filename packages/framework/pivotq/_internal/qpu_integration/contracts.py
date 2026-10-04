"""AIMD-facing input and output contracts for QPU circuit execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NotRequired, Protocol, TypedDict

if TYPE_CHECKING:
    from qiskit import QuantumCircuit


@dataclass(frozen=True, slots=True)
class QuantumCircuitRequest:
    """One three-qubit Qiskit circuit supplied by AIMD for QPU execution.

    ``measurement_basis`` is AIMD-supplied metadata.  The framework validates
    and echoes it, but does not add basis-change gates to ``circuit``.
    """

    circuit_id: str
    circuit: QuantumCircuit
    measurement_basis: Literal["X", "Y", "Z"]

    def __post_init__(self) -> None:
        if not isinstance(self.circuit_id, str):
            raise TypeError("circuit_id must be a string")
        if not self.circuit_id or self.circuit_id != self.circuit_id.strip():
            raise ValueError(
                "circuit_id must be non-empty without surrounding whitespace"
            )

        if not isinstance(self.measurement_basis, str):
            raise TypeError("measurement_basis must be a string")
        if self.measurement_basis not in ("X", "Y", "Z"):
            raise ValueError("measurement_basis must be exactly 'X', 'Y' or 'Z'")


class CircuitResult(TypedDict):
    """Complete three-bit distribution with all eight states, including zeros.

    Keys run from ``000`` to ``111`` and zero probabilities are explicit 0.0.
    The device adapter verifies completeness before filling zeros. Characters
    correspond to logical qubits 0, 1, 2, from left to right. Wider interfaces
    are deferred; missing public result keys are a contract violation.
    """

    circuit_id: str
    shots: int
    measurement_basis: Literal["X", "Y", "Z"]
    measurement_qubits: list[int]
    probabilities: dict[str, float]
    device_timing: NotRequired[dict[str, object]]
    simulation: NotRequired[dict[str, object]]


class RunnerContext(Protocol):
    """Subset of ``RayJobDriverContext`` used by the public service."""

    @property
    def run_id(self) -> str: ...

    def raise_if_stop_requested(self) -> None: ...


__all__ = [
    "CircuitResult",
    "QuantumCircuitRequest",
    "RunnerContext",
]
