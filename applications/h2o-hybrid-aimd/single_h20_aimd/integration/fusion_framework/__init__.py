"""把 pivotq._internal 融合框架适配为项目现有异构执行客户端。"""

from .components import (
    ClassicalPredictSessionsComponent,
    QPUQuantumFeaturesComponent,
    StatevectorQuantumFeaturesComponent,
)
from .fusion_client import FusionComponentIds, FusionExecutionClient
from .qpu_circuit_adapter import FusionQPUCircuitFeatureExtractor
from .registration import register_components, register_fusion_components
from .runner import run_aimd

__all__ = [
    "ClassicalPredictSessionsComponent",
    "FusionComponentIds",
    "FusionExecutionClient",
    "FusionQPUCircuitFeatureExtractor",
    "QPUQuantumFeaturesComponent",
    "StatevectorQuantumFeaturesComponent",
    "register_components",
    "register_fusion_components",
    "run_aimd",
]
