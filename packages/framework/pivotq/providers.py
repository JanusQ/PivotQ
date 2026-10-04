"""Public contracts for explicitly registered quantum execution providers.

A provider receives a bound, measurement-free Qiskit circuit. It returns the
distribution of *all logical qubits* in ``q[n-1]...q0`` order. PivotQ owns the
user's measurement mapping and converts that distribution into QuantumResult.
Nothing in this module imports a device SDK, Qiskit, or Ray.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import inspect
import math
from numbers import Real
import re
from typing import Any, Literal, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from qiskit import QuantumCircuit


@dataclass(frozen=True, slots=True)
class BackendCapabilities:
    """Static capabilities; describing a backend never contacts its device.

    This first protocol accepts bound unitary circuits and terminal
    measurements only. Provider adapters compile gates to their native basis.
    """

    max_qubits: int
    is_simulated: bool
    min_qubits: int = 1
    supports_seed: bool = False

    def __post_init__(self) -> None:
        for name in ("min_qubits", "max_qubits"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.min_qubits > self.max_qubits:
            raise ValueError("min_qubits must not exceed max_qubits")
        if type(self.is_simulated) is not bool or type(self.supports_seed) is not bool:
            raise TypeError("is_simulated and supports_seed must be booleans")
        if not self.is_simulated and self.supports_seed:
            raise ValueError("physical quantum backends cannot support a sampling seed")


@dataclass(frozen=True, slots=True)
class QuantumRequest:
    """One execution request, created by PivotQ after circuit validation.

    ``circuit`` is an independent, measurement-free copy with logical qubits
    numbered from zero. Execute full Z readout after these gates and restore
    any layout permutation before returning results. ``request_id`` is stable
    throughout this call and should accompany remote device job records.
    """

    circuit: QuantumCircuit
    shots: int
    seed: int | None
    request_id: str


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Full logical-qubit distribution returned by a provider.

    Keys use ``q[n-1]...q0`` with no register separators. At least one of
    ``counts`` and ``probabilities`` must be present. When both are returned,
    probabilities must equal the count frequencies. Counts are never invented
    for a device that supplies probabilities only. ``shots`` must reflect the
    backend-confirmed repetition count. ``source`` identifies the actual data
    source, for example ``device_expr_prob`` or ``statevector_samples``.

    Metadata is standard-pickle serializable. Include ``backend_job_id`` and
    optionally ``device_id`` when available, so validation failures retain
    reconciliation identifiers. Do not include credentials.
    """

    shots: int
    source: str
    probabilities: Mapping[str, float] | None = None
    counts: Mapping[str, int] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class QuantumProvider(Protocol):
    """Synchronous provider constructed in the execution process.

    Use structured ``pivotq.errors`` exceptions for known failures. Once a
    physical device may have accepted work, raise ``ResultUnknownError`` with
    its job identity instead of claiming that no execution occurred. PivotQ
    does not retry calls or substitute a simulated provider.
    """

    def run(self, request: QuantumRequest) -> ProviderResult: ...

    def close(self) -> None:
        """Release local client resources; must be safe to call repeatedly."""
        ...


@dataclass(frozen=True, slots=True)
class _BackendRegistration:
    name: str
    factory: Callable[..., QuantumProvider] = field(repr=False)
    capabilities: BackendCapabilities
    execution: Literal["task", "actor"]
    num_cpus: float


def _make_registration(
    name: str,
    factory: Callable[..., QuantumProvider],
    *,
    capabilities: BackendCapabilities,
    execution: Literal["task", "actor"] | None = None,
    num_cpus: float | None = None,
) -> _BackendRegistration:
    """Validate a registration without constructing or connecting a provider."""
    if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", name):
        raise ValueError("backend name must be 1-128 letters, digits, '.', '_' or '-' starting with a letter or digit")
    if not callable(factory):
        raise TypeError("provider factory must be callable")
    candidates = (factory, getattr(factory, "__call__", None))
    if any(inspect.iscoroutinefunction(item) or inspect.isgeneratorfunction(item)
           or inspect.isasyncgenfunction(item) for item in candidates):
        raise TypeError("provider factory must be synchronous and return a provider instance")
    if not isinstance(capabilities, BackendCapabilities):
        raise TypeError("capabilities must be BackendCapabilities")
    if execution is None:
        execution = "task" if capabilities.is_simulated else "actor"
    if execution not in ("task", "actor"):
        raise ValueError("provider execution must be 'task' or 'actor'")
    if num_cpus is None:
        num_cpus = 1.0 if capabilities.is_simulated else 0.0
    if isinstance(num_cpus, bool) or not isinstance(num_cpus, Real) or not math.isfinite(num_cpus) or num_cpus < 0:
        raise ValueError("num_cpus must be a finite nonnegative number")
    if capabilities.is_simulated:
        if num_cpus <= 0:
            raise ValueError("simulated quantum providers must request positive num_cpus")
    elif execution != "actor" or num_cpus != 0:
        raise ValueError("physical quantum providers require serial actor execution with num_cpus=0")
    return _BackendRegistration(name, factory, capabilities, execution, float(num_cpus))


__all__ = ["BackendCapabilities", "QuantumRequest", "ProviderResult", "QuantumProvider"]
