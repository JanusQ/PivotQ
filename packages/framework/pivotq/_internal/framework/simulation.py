"""Explicit CPU substitutes and auditable, per-run execution decisions.

Availability describes installed/configured capacity, never idle capacity.
Adapters are selected before executing user code, not after a runtime failure.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json

from .component import ComponentFactory, validate_component_factory
from .models import ResourceRequest


def resources_dict(resources: ResourceRequest) -> dict[str, object]:
    return {
        "num_cpus": resources.num_cpus,
        "num_gpus": resources.num_gpus,
        "custom_resources": resources.custom_resources_dict(),
    }


def requested_devices(resources: ResourceRequest) -> tuple[str, ...]:
    devices = []
    if resources.num_gpus:
        devices.append("GPU")
    if any(key == "QPU" or key.startswith("qpu_device_")
           for key in resources.custom_resources_dict()):
        devices.append("QPU")
    return tuple(devices) or ("CPU",)


@dataclass(frozen=True, slots=True)
class SimulationAdapter:
    factory: ComponentFactory
    resources: ResourceRequest
    required_devices: tuple[str, ...] = ()
    availability: Callable[[], bool] | None = None
    backend: str = "cpu"

    def __post_init__(self) -> None:
        validate_component_factory(self.factory)
        if not isinstance(self.resources, ResourceRequest):
            raise TypeError("simulation resources must be a ResourceRequest")
        if self.resources.num_cpus <= 0 or self.resources.num_gpus != 0:
            raise ValueError("CPU simulation requires positive CPUs and zero GPUs")
        if any(key == "QPU" or key.startswith("qpu_device_")
               for key in self.resources.custom_resources_dict()):
            raise ValueError("CPU simulation cannot reserve QPU resources")
        if isinstance(self.required_devices, str):
            raise TypeError("required_devices must be a sequence of device names")
        devices = tuple(self.required_devices)
        if any(not isinstance(item, str) or not item.strip() or item != item.strip()
               for item in devices) or len(devices) != len(set(devices)):
            raise ValueError("required_devices must contain unique nonempty names")
        object.__setattr__(self, "required_devices", devices)
        if self.availability is not None and not callable(self.availability):
            raise TypeError("availability must be callable")
        if not isinstance(self.backend, str) or not self.backend.strip():
            raise ValueError("simulation backend must be nonempty text")


@dataclass(frozen=True, slots=True)
class ExecutionSelection:
    component_id: str
    simulated: bool
    reason: str
    backend: str
    requested_devices: tuple[str, ...]
    actual_devices: tuple[str, ...]
    requested_resources: ResourceRequest
    effective_resources: ResourceRequest

    def as_dict(self) -> dict[str, object]:
        return {
            "component_id": self.component_id,
            "simulated": self.simulated,
            "reason": self.reason,
            "backend": self.backend,
            "requested_devices": list(self.requested_devices),
            "actual_devices": list(self.actual_devices),
            "requested_resources": resources_dict(self.requested_resources),
            "effective_resources": resources_dict(self.effective_resources),
        }

    def trace_metadata(self) -> dict[str, str]:
        record = self.as_dict()
        return {
            "simulation.enabled": "true",
            "simulation.simulated": str(self.simulated).lower(),
            "simulation.backend": self.backend,
            "simulation.reason": self.reason,
            **{
                "simulation." + key: json.dumps(record[key], sort_keys=True, separators=(",", ":"))
                for key in ("requested_devices", "actual_devices", "requested_resources", "effective_resources")
            },
        }


def has_device_capacity(
    resources: ResourceRequest,
    devices: Sequence[str],
    capacities: Sequence[Mapping[str, float]],
) -> bool:
    """Check total capacity on a single eligible node, not currently idle slots."""
    requirements = resources.custom_resources_dict()
    requirements.update(CPU=resources.num_cpus, GPU=resources.num_gpus)
    for device in devices:
        # Named external QPU bindings are sufficient without a generic QPU token.
        if device == "QPU" and any(key.startswith("qpu_device_") for key in requirements):
            continue
        if device != "CPU":
            requirements[device] = max(requirements.get(device, 0), 1e-12)
    return any(all(node.get(name, 0) >= amount for name, amount in requirements.items())
               for node in capacities)


__all__ = ["ExecutionSelection", "SimulationAdapter"]
