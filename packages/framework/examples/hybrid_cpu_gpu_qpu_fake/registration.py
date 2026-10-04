"""Register CPU, GPU, and logical-QPU stages for one validation Ray Job."""

from __future__ import annotations

from pivotq._internal.framework import (
    ComponentSpec,
    ExecutionMode,
    FusionFramework,
    ResourceRequest,
)
from pivotq._internal.qpu_integration.component import register_qpu_client
from tests.fixtures.qpu_device_fake import RecordingDeviceAdapter

from .components import CpuInputComponent, CudaAngleComponent


CPU_COMPONENT_ID = "hybrid-fake-cpu-input"
GPU_COMPONENT_ID = "hybrid-fake-gpu-angle"
CPU_HEAD_RESOURCE = "CPU_HEAD"


def register_components(framework: FusionFramework) -> None:
    """Explicit fixed-count fixture; validates communication, not a quantum model."""

    framework.register(
        ComponentSpec(
            component_id=CPU_COMPONENT_ID,
            execution=ExecutionMode.TASK,
            resources=ResourceRequest(
                num_cpus=0.25,
                custom_resources={CPU_HEAD_RESOURCE: 0.001},
            ),
            allowed_methods=("prepare",),
            timeout_seconds=120,
        ),
        CpuInputComponent,
    )
    framework.register(
        ComponentSpec(
            component_id=GPU_COMPONENT_ID,
            execution=ExecutionMode.TASK,
            resources=ResourceRequest(num_cpus=0, num_gpus=1),
            allowed_methods=("compute",),
            timeout_seconds=120,
        ),
        CudaAngleComponent,
    )
    register_qpu_client(
        framework,
        adapter_factory=RecordingDeviceAdapter,
        num_cpus=0.5,
        timeout_seconds=120,
    )


__all__ = [
    "CPU_COMPONENT_ID",
    "CPU_HEAD_RESOURCE",
    "GPU_COMPONENT_ID",
    "register_components",
]
