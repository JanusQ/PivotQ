"""Public contracts for registering and invoking external components.

This package intentionally has no dependency on Ray or scientific-computing
libraries.  Executors translate these contracts to local calls or Ray public
APIs in later implementation stages.
"""

from .component import (
    ComponentAdapter,
    ComponentFactory,
    validate_component_factory,
    validate_component_instance,
    validate_invocation,
)
from .facade import FusionFramework
from .graph import (
    InvocationGraph,
    ResultRef,
    resolve_result_references,
    result_ref_ids,
)
from .models import (
    ComponentSpec,
    ExecutionMode,
    InvocationHandle,
    InvocationResult,
    InvocationSpec,
    InvocationStatus,
    ResourceRequest,
)
from .registry import ComponentRegistration, ComponentRegistry
from .resources import RayResourceOptions, resource_request_to_ray_options
from .simulation import ExecutionSelection, SimulationAdapter

__all__ = [
    "ComponentAdapter",
    "ComponentFactory",
    "ComponentRegistration",
    "ComponentRegistry",
    "ComponentSpec",
    "ExecutionMode",
    "ExecutionSelection",
    "FusionFramework",
    "InvocationHandle",
    "InvocationGraph",
    "InvocationResult",
    "InvocationSpec",
    "InvocationStatus",
    "ResourceRequest",
    "SimulationAdapter",
    "ResultRef",
    "RayResourceOptions",
    "validate_component_factory",
    "validate_component_instance",
    "validate_invocation",
    "resolve_result_references",
    "result_ref_ids",
    "resource_request_to_ray_options",
]
