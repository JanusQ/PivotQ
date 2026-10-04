"""Numerical parity for the optional H2O application through the QPU service.

This suite needs the unified environment and frozen H2O assets. It keeps all
integration code in the framework and never changes the application package.
"""

from dataclasses import replace
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("single_h20_aimd")
import torch

from single_h20_aimd.api.contracts import QuantumFeatureRequest
from single_h20_aimd.configuration import load_config
from single_h20_aimd.core.factory import load_hybrid_potential
from single_h20_aimd.core.potential import HybridPotential
from single_h20_aimd.data import water_internal_to_cartesian
from single_h20_aimd.execution import ActorCallRequest, ActorRequest, ResourceRequest as ApplicationResources
from single_h20_aimd.execution import TaskRequest, execute_quantum_feature_task
from single_h20_aimd.execution.classical_actor import ClassicalPredictActor
from single_h20_aimd.quantum import ZX14_OBSERVABLES

from pivotq._internal.executors import LocalExecutor
from pivotq._internal.framework import (
    ComponentRegistry, ComponentSpec, ExecutionMode, FusionFramework, ResourceRequest,
)
from pivotq._internal.integrations.h2o import (
    CPUClassicalSessionsComponent, CPUQuantumFeaturesComponent,
    SimulatedQPUCircuitFeatureExtractor,
)
from pivotq._internal.qpu_integration import QPUCircuitService
from pivotq._internal.qpu_integration.simulation import StatevectorQPUComponent


APPLICATION_ROOT = Path(__file__).resolve().parents[4] / "applications/h2o-hybrid-aimd"


@pytest.fixture
def frozen_potential():
    config = load_config(APPLICATION_ROOT / "configs/h2o_aimd.yaml")
    return load_hybrid_potential(config, APPLICATION_ROOT / config["checkpoint"]["path"])


@pytest.fixture
def extractor():
    registry = ComponentRegistry()
    framework = FusionFramework(LocalExecutor(registry))
    framework.register(
        ComponentSpec(
            component_id="h2o-exact-test",
            execution=ExecutionMode.ACTOR,
            resources=ResourceRequest(num_cpus=1),
            allowed_methods=("run_quantum_circuits",),
            stateful=True,
        ),
        StatevectorQPUComponent,
    )
    context = SimpleNamespace(run_id="h2o-exact-parity", raise_if_stop_requested=lambda: None)
    service = QPUCircuitService(framework, context, component_id="h2o-exact-test")
    try:
        yield SimulatedQPUCircuitFeatureExtractor(service, shots=3000)
    finally:
        framework.close()
        registry.close()


@pytest.fixture
def geometries():
    return water_internal_to_cartesian(
        np.asarray([0.91, 0.97, 1.02]),
        np.asarray([1.02, 0.94, 0.91]),
        np.asarray([101.0, 108.0, 101.0]),
    )


def test_qpu_service_features_match_original_fourteen_observables(
    frozen_potential, extractor, geometries,
):
    request = QuantumFeatureRequest(
        request_id="h2o-frozen-parity",
        sample_ids=tuple(f"geometry-{index}" for index in range(len(geometries))),
        molecular_geometries_A=torch.as_tensor(geometries, dtype=torch.float64),
        atomic_numbers=(8, 1, 1),
        bond_lengths_A=None,
        encoding_spec=frozen_potential.encoding_spec,
        circuit_spec=frozen_potential.circuit_spec,
        observables=ZX14_OBSERVABLES,
        execution_spec={"mode": "real_qpu", "shots": 3000, "gradient_method": "none"},
    )
    result = extractor.extract_features(request)
    original = frozen_potential.quantum_api.extract_features(
        replace(request, execution_spec={
            "mode": "exact_statevector", "device": "cpu", "shots": None,
            "noise": False, "gradient_method": "none",
        })
    )

    assert result.features.shape == (3, 14)
    assert result.feature_names == ZX14_OBSERVABLES
    torch.testing.assert_close(result.features, original.features, atol=1e-12, rtol=0)
    # The first and last configurations exchange indistinguishable hydrogens.
    torch.testing.assert_close(result.features[0], result.features[2], atol=1e-12, rtol=0)
    assert result.backend_metadata["real_hardware"] is False
    assert result.execution_metrics["total_physical_executions"] == 0
    assert extractor.describe()["shots_per_measurement_basis"] is None
    assert result.feature_variances is None or torch.count_nonzero(result.feature_variances) == 0


def test_qpu_service_matches_frozen_energy_and_production_cartesian_force(
    frozen_potential, extractor, geometries,
):
    simulated = HybridPotential(
        quantum_api=extractor,
        classical_api=frozen_potential.classical_api,
        force_api=frozen_potential.force_api,
        observables=frozen_potential.observables,
        encoding_spec=frozen_potential.encoding_spec,
        circuit_spec=frozen_potential.circuit_spec,
        execution_spec={"mode": "real_qpu", "shots": 3000, "gradient_method": "none"},
    )

    expected = frozen_potential.predict_geometry_energy_and_force(geometries)
    actual = simulated.predict_geometry_energy_and_force(geometries)

    np.testing.assert_allclose(actual.energies_eV, expected.energies_eV, atol=1e-11, rtol=0)
    np.testing.assert_allclose(actual.forces_eV_per_A, expected.forces_eV_per_A, atol=1e-8, rtol=0)
    assert actual.forces_eV_per_A.shape == (3, 3, 3)
    assert np.isfinite(actual.forces_eV_per_A).all()


def test_gpu_quantum_adapter_copies_request_and_matches_cpu_features():
    example_path = APPLICATION_ROOT / (
        "single_h20_aimd/integration/fusion_framework/example_quantum_request.json"
    )
    cpu_request = TaskRequest.from_dict(json.loads(example_path.read_text()))
    gpu_payload = deepcopy(cpu_request.payload)
    gpu_payload["backend"] = "adapt_water_statevector_gpu"
    gpu_payload["quantum_request"]["execution_spec"].update(device="cuda")
    gpu_request = replace(
        cpu_request, payload=gpu_payload,
        resources=ApplicationResources(cpu=0.25, gpu=1.0),
    )
    original = deepcopy(gpu_request.to_dict())

    actual = CPUQuantumFeaturesComponent().execute(gpu_request)
    expected = execute_quantum_feature_task(cpu_request)

    assert actual.status == expected.status == "succeeded"
    np.testing.assert_allclose(actual.outputs["features"], expected.outputs["features"], atol=0, rtol=0)
    assert gpu_request.to_dict() == original
    assert actual.metadata["requested_resources"]["gpu"] == 1
    assert actual.metadata["actual_device"] == "cpu"
    assert actual.metadata["simulation"] is True


def test_gpu_classical_adapter_copies_request_and_matches_cpu_energy():
    config = load_config(APPLICATION_ROOT / "configs/h2o_aimd.yaml")
    checkpoint = APPLICATION_ROOT / config["checkpoint"]["path"]
    request = ActorRequest(
        run_id="gpu-actor-copy", actor_id="gpu-actor", actor_type="classical_predict",
        payload={"checkpoint_path": str(checkpoint), "device": "cuda", "require_gpu": True},
        resources=ApplicationResources(cpu=0.25, gpu=1.0),
    )
    original = deepcopy(request.to_dict())
    payload = {
        "request_id": "gpu-actor-predict", "sample_ids": ["first", "second"],
        "features": [[index / 14.0 for index in range(14)], [-index / 14.0 for index in range(14)]],
    }
    component = CPUClassicalSessionsComponent()
    try:
        handle = component.create(request)
        actual = component.call(handle, ActorCallRequest(
            run_id=request.run_id, task_id="gpu-actor-call", method="predict", payload=payload,
        ))
        expected = ClassicalPredictActor(checkpoint, device="cpu", require_gpu=False).predict(payload)
        assert actual.status == "succeeded", actual.error
        np.testing.assert_allclose(actual.outputs["energies_eV"], expected["energies_eV"], atol=0, rtol=0)
        assert actual.outputs["inference_metrics"]["actor_device"] == "cpu"
        assert request.to_dict() == original
        assert component.terminate(handle) is True
    finally:
        component.close()
