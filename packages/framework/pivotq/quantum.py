"""Quantum execution for the public CPU/QPU programming interface.

The module is safe to import without initializing Qiskit, Ray, or a device.
Circuit validation and execution happen inside the selected executor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
import inspect
import json
import math
from numbers import Real
import os
import pickle
from pathlib import Path
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from .providers import BackendCapabilities, ProviderResult, QuantumRequest, _make_registration

if TYPE_CHECKING:
    from .refs import ResultRef
    from .runtime import Runtime


@dataclass(frozen=True, slots=True)
class QuantumResult:
    """A measured distribution, with keys ordered most significant bit first.

    Explicit measurement uses flattened classical bits ``c[n-1]...c0``.
    Without measurement instructions, all qubits use ``q[n-1]...q0``.
    Zero-probability states may be absent. ``counts=None`` means that the
    backend supplied probabilities without raw sample counts.
    """

    probabilities: dict[str, float]
    counts: dict[str, int] | None
    backend: str
    is_simulated: bool
    shots: int
    bit_order: str
    metadata: dict[str, Any] = field(default_factory=dict)


class QuantumBackend:
    """A Runtime-owned built-in or explicitly registered quantum backend.

    Obtain this object with ``runtime.quantum_backend(name, **config)``.
    Simulator configuration accepts ``max_qubits`` (default 20).
    Lab configuration accepts ``server_url``, ``api_key``,
    ``timeout_seconds``. Omitted settings are
    captured from the existing QPU environment/configuration at creation.
    """

    def __init__(self, runtime: Runtime, name: str, **config: Any) -> None:
        from ._internal.framework import ComponentSpec, ExecutionMode, ResourceRequest

        self._runtime = runtime
        self._name = name
        custom_resources = ()
        if name == "simulator":
            _reject_unknown(config, {"max_qubits"})
            max_qubits = config.get("max_qubits", 20)
            _positive_integer("max_qubits", max_qubits)
            registration = _make_registration(
                name, _Simulator, capabilities=BackendCapabilities(max_qubits, True, supports_seed=True),
            )
            provider_config = {}
        elif name == "lab-qpu":
            _reject_unknown(config, {"server_url", "api_key", "timeout_seconds"})
            settings = _LabSettings.resolve(config)
            registration = _make_registration(
                name, _LabQPU, capabilities=BackendCapabilities(3, False, min_qubits=3),
            )
            provider_config = {"settings": settings}
            custom_resources = settings.custom_resources
        else:
            registration = runtime._backend_registrations.get(name)
            if registration is None:
                raise ValueError(f"quantum backend {name!r} is not registered")
            provider_config = config
        self._capabilities = registration.capabilities
        # Mutable configuration objects must not change after backend creation.
        # The factory remains in registration metadata for Ray cloudpickle.
        try:
            provider_config = pickle.loads(pickle.dumps(provider_config))
        except Exception:
            raise TypeError("quantum backend configuration must be standard-pickle serializable") from None
        try:
            signature = inspect.signature(registration.factory)
        except (ValueError, TypeError):
            signature = None
        if signature is not None:
            try:
                signature.bind(**provider_config)
            except TypeError:
                raise TypeError("quantum backend configuration does not match its provider factory") from None
        mode = ExecutionMode(registration.execution)
        resources = ResourceRequest(num_cpus=registration.num_cpus, custom_resources=custom_resources)
        runtime._ensure_started()
        self._component_id = runtime._new_component_id(prefix="quantum")
        runtime._register_component(
            ComponentSpec(
                component_id=self._component_id,
                execution=mode,
                resources=resources,
                allowed_methods=("run",),
                stateful=mode is ExecutionMode.ACTOR,
                max_concurrency=1 if mode is ExecutionMode.ACTOR else runtime.max_workers,
            ),
            _ProviderComponentFactory(
                name, registration.factory, self._capabilities, provider_config,
            ),
        )

    @property
    def name(self) -> str:
        return self._name

    def describe(self) -> BackendCapabilities:
        """Return static capabilities without constructing or contacting a provider."""
        return self._capabilities

    def submit(self, circuit_or_ref: Any, *, shots: int = 1024, seed: int | None = None) -> ResultRef:
        """Submit a Qiskit circuit or a reference to one; return a result reference.

        ``seed`` makes simulator sampling reproducible. Real devices do not
        accept a seed and are never silently replaced by a simulator.
        """
        component_id, method, args, kwargs = self._invocation_payload(circuit_or_ref, shots=shots, seed=seed)
        return self._runtime._submit_component(component_id, method, *args, kwargs=kwargs)

    def _invocation_payload(self, circuit_or_ref: Any, *, shots: int = 1024, seed: int | None = None):
        """Build a call for immediate submission or a Workflow's compiled DAG."""
        _positive_integer("shots", shots)
        if seed is not None and (type(seed) is not int or seed < 0):
            raise ValueError("seed must be a nonnegative integer or None")
        if seed is not None and not self._capabilities.supports_seed:
            raise ValueError(f"{self.name} does not support seed")
        return (
            self._component_id, "run", (circuit_or_ref,),
            {"shots": shots, "seed": seed, "request_id": f"sdk-{uuid4().hex}"},
        )


def _positive_integer(name: str, value: Any) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _reject_unknown(config: dict[str, Any], allowed: set[str]) -> None:
    unknown = config.keys() - allowed
    if unknown:
        raise TypeError(f"unsupported backend configuration: {', '.join(sorted(unknown))}")


@dataclass(frozen=True, slots=True)
class _Measurement:
    mapping: tuple[tuple[int, int], ...]
    width: int
    explicit: bool

    @property
    def bit_order(self) -> str:
        return "c[n-1]...c0" if self.explicit else "q[n-1]...q0"

    def key(self, qubit_key: str) -> str:
        """Convert a Qiskit full-qubit key into flattened classical output."""
        bits = ["0"] * self.width
        for qubit, classical in self.mapping:
            bits[self.width - 1 - classical] = qubit_key[-1 - qubit]
        return "".join(bits)


def _unitary_operation(operation: Any, depth: int = 0) -> None:
    from qiskit.circuit import Gate

    if depth > 100:
        raise ValueError("circuit instruction definitions are nested too deeply")
    if (
        operation.name in {"measure", "reset", "initialize", "delay", "store"}
        or operation.num_clbits
        or getattr(operation, "condition", None) is not None
        or hasattr(operation, "blocks")
    ):
        raise ValueError(f"unsupported non-unitary instruction: {operation.name}")
    definition = operation.definition
    if definition is not None:
        for item in definition.data:
            if item.operation.name != "barrier":
                _unitary_operation(item.operation, depth + 1)
    elif not isinstance(operation, Gate):
        raise ValueError(f"unsupported instruction: {operation.name}")


def _prepare(circuit: Any, *, max_qubits: int, min_qubits: int = 1, exact_qubits: int | None = None) -> tuple[Any, _Measurement]:
    from qiskit import QuantumCircuit

    if not isinstance(circuit, QuantumCircuit):
        raise TypeError("quantum execution requires a Qiskit QuantumCircuit")
    if exact_qubits is not None and circuit.num_qubits != exact_qubits:
        raise ValueError(f"backend requires exactly {exact_qubits} qubits")
    if not min_qubits <= circuit.num_qubits <= max_qubits:
        raise ValueError(f"circuit must contain between {min_qubits} and {max_qubits} qubits")
    if circuit.parameters:
        raise ValueError("bind every circuit parameter before execution")
    body = QuantumCircuit(circuit.num_qubits)
    body.global_phase = circuit.global_phase
    mapping = []
    seen_qubits: set[int] = set()
    seen_clbits: set[int] = set()
    measured = False
    for item in circuit.data:
        operation = item.operation
        if operation.name == "barrier":
            continue
        qubits = [circuit.find_bit(bit).index for bit in item.qubits]
        if operation.name == "measure":
            measured = True
            qubit = qubits[0]
            classical = circuit.find_bit(item.clbits[0]).index
            if qubit in seen_qubits or classical in seen_clbits:
                raise ValueError("each qubit and classical bit may be measured at most once")
            seen_qubits.add(qubit)
            seen_clbits.add(classical)
            mapping.append((qubit, classical))
        else:
            if measured:
                raise ValueError("only terminal measurements are supported")
            _unitary_operation(operation)
            body.append(operation, qubits, copy=True)
    if measured:
        measurement = _Measurement(tuple(mapping), circuit.num_clbits, True)
    else:
        measurement = _Measurement(tuple((q, q) for q in range(circuit.num_qubits)), circuit.num_qubits, False)
    return body, measurement


def _validated_prepare(circuit: Any, **limits: int) -> tuple[Any, _Measurement]:
    from ._internal.errors import ValidationError

    try:
        return _prepare(circuit, **limits)
    except (TypeError, ValueError) as error:
        raise ValidationError(str(error)) from None


def _distribution(values: Any, *, width: int, counts: bool) -> dict:
    from numbers import Integral

    label = "counts" if counts else "probabilities"
    if not isinstance(values, Mapping) or not values:
        raise ValueError(f"provider {label} must be a nonempty mapping")
    result = {}
    for key, value in values.items():
        if not isinstance(key, str) or len(key) != width or set(key) - {"0", "1"}:
            raise ValueError(f"provider distribution keys must contain {width} bits in q[n-1]...q0 order")
        if isinstance(value, bool):
            raise ValueError(f"provider {label} cannot contain boolean values")
        if counts:
            if not isinstance(value, Integral) or value < 0:
                raise ValueError("provider counts must be nonnegative integers")
            result[key] = int(value)
        else:
            if not isinstance(value, Real) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("provider probabilities must be finite numbers between zero and one")
            result[key] = float(value)
    return result


def _validated_result(result: Any, *, width: int, shots: int) -> ProviderResult:
    if not isinstance(result, ProviderResult):
        raise ValueError("provider run() must return ProviderResult")
    if type(result.shots) is not int or result.shots != shots:
        raise ValueError("provider confirmed shots must equal requested shots")
    if not isinstance(result.source, str) or not result.source.strip():
        raise ValueError("provider result source must be nonempty text")
    if result.counts is None and result.probabilities is None:
        raise ValueError("provider result must contain counts or probabilities")
    counts = None if result.counts is None else _distribution(result.counts, width=width, counts=True)
    probabilities = None if result.probabilities is None else _distribution(result.probabilities, width=width, counts=False)
    if counts is not None and sum(counts.values()) != shots:
        raise ValueError("provider count total must equal confirmed shots")
    if probabilities is not None and not math.isclose(math.fsum(probabilities.values()), 1.0, rel_tol=0, abs_tol=1e-6):
        raise ValueError("provider probabilities must sum to one")
    if counts is not None:
        frequencies = {key: count / shots for key, count in counts.items()}
        if probabilities is not None and any(
            not math.isclose(probabilities.get(key, 0), frequencies.get(key, 0), rel_tol=0, abs_tol=1e-6)
            for key in probabilities.keys() | frequencies.keys()
        ):
            raise ValueError("provider probabilities differ from its count frequencies")
        probabilities = frequencies
    if not isinstance(result.metadata, Mapping):
        raise ValueError("provider result metadata must be a mapping")
    if any(not isinstance(key, str) for key in result.metadata):
        raise ValueError("provider result metadata keys must be strings")
    if result.metadata.keys() & {"backend", "is_simulated", "bit_order", "request_id", "source"}:
        raise ValueError("provider result metadata cannot override PivotQ result fields")
    try:
        metadata = pickle.loads(pickle.dumps(dict(result.metadata)))
    except Exception:
        raise ValueError("provider result metadata must be standard-pickle serializable") from None
    return ProviderResult(shots, result.source, probabilities, counts, metadata)


@dataclass(frozen=True, slots=True)
class _ProviderComponentFactory:
    name: str
    provider_factory: Any = field(repr=False)
    capabilities: BackendCapabilities
    config: dict[str, Any] = field(repr=False)

    def __call__(self) -> _ProviderComponent:
        return _ProviderComponent(self)


class _ProviderComponent:
    """Shared validation, lifecycle, and measurement adapter for every provider."""

    def __init__(self, factory: _ProviderComponentFactory) -> None:
        self._factory = factory
        self._provider = None
        self._closed = False

    def describe(self) -> dict[str, Any]:
        return {"backend": self._factory.name, "is_simulated": self._factory.capabilities.is_simulated}

    def _instance(self):
        if self._provider is None:
            # Give each instance an independent configuration snapshot, even
            # for local TASK providers that mutate their constructor arguments.
            config = pickle.loads(pickle.dumps(self._factory.config))
            self._provider = self._factory.provider_factory(**config)
        for name in ("run", "close"):
            method = getattr(self._provider, name, None)
            if not callable(method) or inspect.iscoroutinefunction(method) or inspect.isgeneratorfunction(method) or inspect.isasyncgenfunction(method):
                raise ValueError("provider must expose synchronous run(request) and close() methods")
        return self._provider

    def run(self, circuit: Any, *, shots: int, seed: int | None, request_id: str) -> QuantumResult:
        from .errors import ExecutionError, PivotQError, ResultUnknownError

        caps = self._factory.capabilities
        limits = {"max_qubits": caps.max_qubits, "min_qubits": caps.min_qubits}
        if caps.min_qubits == caps.max_qubits:
            limits["exact_qubits"] = caps.min_qubits
        body, measurement = _validated_prepare(circuit, **limits)
        width = body.num_qubits
        request = QuantumRequest(body, shots, seed, request_id)
        result = None
        try:
            if self._closed:
                raise ValueError("provider component is closed")
            result = self._instance().run(request)
        except PivotQError as error:
            if error.framework_job_id is None:
                # Keep backend/device identities and the subtype (including
                # SubmissionError disposition) while adding our request ID.
                fields = error._constructor_kwargs() | {"framework_job_id": request_id}
                raise type(error)(error.message, **fields) from None
            raise
        except Exception as error:
            kind = ExecutionError if caps.is_simulated else ResultUnknownError
            raise kind(
                f"quantum provider raised {type(error).__name__}; request_id={request_id}",
                framework_job_id=request_id,
            ) from None
        try:
            validated = _validated_result(result, width=width, shots=shots)
        except (TypeError, ValueError) as error:
            kind = ExecutionError if caps.is_simulated else ResultUnknownError
            identifiers = {}
            if isinstance(result, ProviderResult) and isinstance(result.metadata, Mapping):
                for key in ("backend_job_id", "device_id"):
                    value = result.metadata.get(key)
                    if isinstance(value, str) and value.strip() and value == value.strip():
                        identifiers[key] = value
            raise kind(
                f"{error}; request_id={request_id}", framework_job_id=request_id, **identifiers,
            ) from None
        probabilities: dict[str, float] = {}
        for qubit_key, value in validated.probabilities.items():
            if value:
                key = measurement.key(qubit_key)
                probabilities[key] = probabilities.get(key, 0.0) + value
        counts = None
        if validated.counts is not None:
            counts = {}
            for qubit_key, value in validated.counts.items():
                if value:
                    key = measurement.key(qubit_key)
                    counts[key] = counts.get(key, 0) + value
            counts = dict(sorted(counts.items()))
            # Calculate measured frequencies directly to avoid floating-point
            # accumulation differences after marginalizing several states.
            probabilities = {key: count / shots for key, count in counts.items()}
        return QuantumResult(
            probabilities=dict(sorted(probabilities.items())), counts=counts,
            backend=self._factory.name, is_simulated=caps.is_simulated,
            shots=validated.shots, bit_order=measurement.bit_order,
            metadata=dict(validated.metadata) | {"source": validated.source, "request_id": request_id},
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._provider is not None and callable(getattr(self._provider, "close", None)):
            self._provider.close()


class _Simulator:
    def run(self, request: QuantumRequest) -> ProviderResult:
        from qiskit.quantum_info import Statevector

        state = Statevector.from_instruction(request.circuit)
        state.seed(request.seed)
        return ProviderResult(
            counts={str(key): int(value) for key, value in state.sample_counts(shots=request.shots).items()},
            shots=request.shots, source="qiskit_statevector_sample_counts",
            metadata={"seed": request.seed},
        )

    def close(self) -> None:
        pass


@dataclass(frozen=True, slots=True)
class _LabSettings:
    server_url: str
    api_key: str = field(repr=False)
    timeout_seconds: float
    journal_dir: str | None
    archive_dir: str | None
    custom_resources: tuple[tuple[str, float], ...]

    @classmethod
    def resolve(cls, config: dict[str, Any]) -> _LabSettings:
        from ._internal.framework import ResourceRequest
        from ._internal.qpu_integration.device_adapter import DeviceProtocolNotConfiguredError

        device: dict[str, Any] = {}
        path = os.environ.get("QPU_DEVICE_CONFIG_FILE")
        if path and config.get("server_url") is None:
            try:
                device = json.loads(Path(path).read_text())[os.environ.get("QPU_DEVICE_ID", "")]
                if not isinstance(device, dict) or not isinstance(device["url"], str):
                    raise ValueError
            except (OSError, KeyError, ValueError, TypeError):
                raise DeviceProtocolNotConfiguredError("Registered QPU configuration is unavailable") from None
        url = config.get("server_url")
        if url is None:
            url = device.get("url", os.environ.get("QPU_DEVICE_URL", ""))
        key = config.get("api_key")
        if key is None:
            key = device.get("api_key", os.environ.get("QPU_DEVICE_API_KEY", ""))
        key = "" if key is None else key
        if not isinstance(url, str) or not isinstance(key, str):
            raise ValueError("server_url and api_key must be strings or None")
        timeout = config.get("timeout_seconds", device.get("timeout_seconds", 600.0))
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 86400:
            raise ValueError("timeout_seconds must be between 1 and 86400")
        resources = device.get("custom_resources", {})
        resource_spec = ResourceRequest(num_cpus=0, custom_resources=resources)
        return cls(
            url, key, float(timeout),
            os.environ.get("QPU_JOB_JOURNAL_DIR"), os.environ.get("QPU_RESULT_ARCHIVE_DIR"),
            tuple(resource_spec.custom_resources),
        )


class _LabQPU:
    def __init__(self, settings: _LabSettings) -> None:
        self._settings = settings
        self._client = None

    def run(self, request: QuantumRequest) -> ProviderResult:
        from .errors import ValidationError
        from ._internal.qpu_integration.component import QPUClientComponent
        from ._internal.qpu_integration.contracts import QuantumCircuitRequest
        from ._internal.qpu_integration.device_adapter import QPUDeviceAdapter, DeviceProtocolNotConfiguredError
        from ._internal.qpu_integration.qasm3_export import CircuitExportError

        if self._client is None:
            settings = self._settings
            try:
                self._client = QPUClientComponent(adapter=QPUDeviceAdapter(
                    server_url=settings.server_url,
                    api_key=settings.api_key,
                    timeout_seconds=settings.timeout_seconds,
                    probability_source="expr_prob",
                    journal_dir=settings.journal_dir,
                    archive_dir=settings.archive_dir,
                    use_environment=False,
                ))
            except DeviceProtocolNotConfiguredError as error:
                raise ValidationError(str(error), framework_job_id=request.request_id) from None
        try:
            result, = self._client.run_quantum_circuits(
                [QuantumCircuitRequest(request.request_id, request.circuit, "Z")],
                shots=request.shots, request_id=request.request_id,
            )
        except CircuitExportError as error:
            # Compilation happens before the adapter can submit a device job.
            raise ValidationError(str(error), framework_job_id=request.request_id) from None
        metadata: dict[str, Any] = {}
        if "device_timing" in result:
            metadata["device_timing"] = result["device_timing"]
        return ProviderResult(
            probabilities={key[::-1]: value for key, value in result["probabilities"].items()},
            shots=result["shots"], source="device_expr_prob", metadata=metadata,
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


__all__ = ["QuantumBackend", "QuantumResult"]
