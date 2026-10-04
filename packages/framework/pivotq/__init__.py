"""PivotQ: Python CPU tasks and explicit quantum execution backends."""

from .errors import PivotQError
from .refs import ResultRef
from .runtime import Runtime
from .quantum import QuantumBackend, QuantumResult
from .components import ComponentHandle, ComponentSpec
from .workflow import NodeRef, Workflow, WorkflowRun, WorkflowSubmissionError
from .observability import ExecutionReport, InvocationStatus
from .providers import BackendCapabilities, QuantumProvider, QuantumRequest, ProviderResult

__version__ = "0.1.0.dev0"

__all__ = [
    "Runtime", "ResultRef", "QuantumBackend", "QuantumResult", "PivotQError",
    "ComponentSpec", "ComponentHandle", "Workflow", "WorkflowRun", "NodeRef",
    "WorkflowSubmissionError", "ExecutionReport", "InvocationStatus",
    "BackendCapabilities", "QuantumProvider", "QuantumRequest", "ProviderResult", "__version__",
]
