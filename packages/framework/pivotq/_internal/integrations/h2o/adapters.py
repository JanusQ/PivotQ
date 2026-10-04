"""CPU adapters around the unchanged application's public execution boundary."""

from copy import deepcopy
from dataclasses import replace

import torch

from single_h20_aimd.execution.contracts import ActorRequest, TaskRequest, ResourceRequest
from single_h20_aimd.integration.fusion_framework.components import (
    ClassicalPredictSessionsComponent, StatevectorQuantumFeaturesComponent,
)
from single_h20_aimd.integration.fusion_framework.qpu_circuit_adapter import (
    FusionQPUCircuitFeatureExtractor,
)


def _cpu_resources(resources):
    return ResourceRequest(cpu=max(resources.cpu, 0.25), memory_bytes=resources.memory_bytes)


class CPUQuantumFeaturesComponent(StatevectorQuantumFeaturesComponent):
    def execute(self, request):
        task = request if isinstance(request, TaskRequest) else TaskRequest.from_dict(request)
        payload = deepcopy(task.payload)
        payload["backend"] = "adapt_water_statevector"
        payload["quantum_request"].setdefault("execution_spec", {}).update(
            device="cpu", mode="exact_statevector", gradient_method="none",
        )
        result = super().execute(replace(task, payload=payload, resources=_cpu_resources(task.resources)))
        return replace(result, metadata={
            **result.metadata,
            "simulation": True,
            "requested_resources": task.resources.to_dict(),
            "actual_device": "cpu",
            "simulation_backend": "adapt_water_statevector",
        })


class CPUClassicalSessionsComponent(ClassicalPredictSessionsComponent):
    def create(self, request):
        actor = request if isinstance(request, ActorRequest) else ActorRequest.from_dict(request)
        payload = deepcopy(actor.payload)
        payload.update(device="cpu", require_gpu=False)
        return super().create(replace(actor, payload=payload, resources=_cpu_resources(actor.resources)))


class SimulatedQPUCircuitFeatureExtractor(FusionQPUCircuitFeatureExtractor):
    """Reuse F2 circuits/parities, correcting exact-probability execution semantics."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._batches = 0
        self._geometries = 0

    def describe(self):
        return {
            **super().describe(),
            "backend_name": "fusion_qpu_exact_statevector_v1",
            "simulation": True,
            "simulation_backend": "qiskit_statevector",
            "mode": "exact_probabilities",
            "actual_device": "cpu",
            "real_hardware": False,
            "requested_shots": self._shots,
            "effective_shots": None,
            "shots_per_measurement_basis": None,
            "total_physical_executions": 0,
            "sampling": False,
            "supports_noise": False,
            "variance_semantics": "zero estimator variance for exact probabilities",
        }

    def extract_features(self, request):
        response = super().extract_features(request)
        self._batches += 1
        self._geometries += len(request.sample_ids)
        return replace(
            response,
            feature_variances=torch.zeros_like(response.features),
            execution_metrics={
                **response.execution_metrics,
                "shots": None,
                "requested_shots": self._shots,
                "effective_shots": None,
                "total_physical_executions": 0,
                "simulation": True,
                "mode": "exact_probabilities",
            },
        )

    def execution_counters(self):
        return {
            "total_batches": self._batches,
            "total_circuit_evaluations": self._geometries,
            "total_measurement_circuit_settings": 2 * self._geometries,
            "total_physical_executions": 0,
        }
