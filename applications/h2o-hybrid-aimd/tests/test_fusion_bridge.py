from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

from single_h20_aimd.configuration import load_config
from single_h20_aimd.execution import ActorCallRequest, ActorRequest, ResourceRequest, TaskRequest
from single_h20_aimd.integration.fusion_framework.components import (
    ClassicalPredictSessionsComponent,
    StatevectorQuantumFeaturesComponent,
)
from single_h20_aimd.integration.fusion_framework.fusion_client import (
    FusionExecutionClient,
    _encode_invocation_id,
)
from single_h20_aimd.integration.fusion_framework.registration import register_fusion_components
from single_h20_aimd.integration.fusion_framework.runner import _build_request
from single_h20_aimd.integration.fusion_framework.submit_job import (
    REGISTRATION_TARGET,
    RUNNER_TARGET,
    build_job_spec,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs/h2o_aimd.yaml"
CHECKPOINT = PROJECT_ROOT / "checkpoints/hybrid_model.pt"
QUANTUM_EXAMPLE = (
    PROJECT_ROOT / "single_h20_aimd/integration/fusion_framework/example_quantum_request.json"
)


@dataclass(frozen=True)
class _InvocationResult:
    succeeded: bool
    value: object | None = None
    status: str = "succeeded"
    error: object | None = None


class _InvocationError:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def to_record(self):
        return {"type": type(self.error).__name__, "message": str(self.error), "retryable": False}


class _DocumentedFramework:
    def __init__(self) -> None:
        self.components = {}
        self.results = {}
        self.released = []
        self.invocations = []
        self.trace_contexts = []
        self._next_handle = 0

    def add_component(self, component_id, factory, *, actor=False):
        self.components[component_id] = (factory, factory() if actor else None)

    def register(self, spec, factory):
        actor = str(spec.execution).lower().endswith("actor")
        self.add_component(spec.component_id, factory, actor=actor)

    def submit(self, component_id, method, *args, invocation_id, **kwargs):
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", invocation_id) is None:
            raise ValueError(f"Invalid invocation_id: {invocation_id}")
        self._next_handle += 1
        handle = self._next_handle
        self.invocations.append((component_id, method, invocation_id))
        self.trace_contexts.append(dict(kwargs.pop("trace_context", {})))
        factory, actor = self.components[component_id]
        component = actor if actor is not None else factory()
        try:
            value = getattr(component, method)(*args, **kwargs)
            result = _InvocationResult(succeeded=True, value=value)
        except Exception as error:
            result = _InvocationResult(
                succeeded=False,
                status="failed",
                error=_InvocationError(error),
            )
        self.results[handle] = result
        return handle

    def result(self, handle):
        return self.results[handle]

    def release(self, handle):
        self.released.append(handle)


class _FailingQuantumComponent:
    def execute(self, request):
        del request
        raise RuntimeError("framework component exploded")


class _Context:
    def __init__(self, output_dir: Path) -> None:
        self.run_id = "runner-build-request"
        self.output_dir = str(output_dir)
        self.trace_collector = None

    def raise_if_stop_requested(self) -> None:
        return None


class FusionFrameworkBridgeTests(unittest.TestCase):
    def _request(self) -> TaskRequest:
        return TaskRequest.from_dict(json.loads(QUANTUM_EXAMPLE.read_text(encoding="utf-8")))

    def test_quantum_task_uses_submit_result_release_lifecycle(self) -> None:
        framework = _DocumentedFramework()
        framework.add_component("h2o-f2-quantum-features-cpu", StatevectorQuantumFeaturesComponent)
        request = self._request()
        client = FusionExecutionClient(framework)

        handle = client.submit(request)
        self.assertEqual(client.status(handle), "running")
        result = client.result(handle)

        self.assertEqual(result.status, "succeeded", result.error)
        self.assertEqual(client.status(handle), "succeeded")
        self.assertEqual(np_shape(result.outputs["features"]), (2, 14))
        self.assertEqual(
            framework.invocations[0][2],
            _encode_invocation_id("task", request.run_id, request.task_id),
        )
        self.assertEqual(framework.released, [1])

    def test_invocation_id_is_safe_and_stable(self) -> None:
        framework = _DocumentedFramework()
        framework.add_component("h2o-f2-quantum-features-cpu", StatevectorQuantumFeaturesComponent)
        request = replace(
            self._request(),
            run_id="run:with spaces/中文",
            task_id="task:" + "very long id/" * 20,
        )
        client = FusionExecutionClient(framework)
        result = client.result(client.submit(request))
        invocation_id = framework.invocations[0][2]
        self.assertEqual(result.status, "succeeded")
        self.assertRegex(invocation_id, r"^[A-Za-z0-9_.-]{1,128}$")
        self.assertEqual(invocation_id, _encode_invocation_id("task", request.run_id, request.task_id))

    def test_framework_failure_is_structured_and_released(self) -> None:
        framework = _DocumentedFramework()
        framework.add_component("h2o-f2-quantum-features-cpu", _FailingQuantumComponent)
        client = FusionExecutionClient(framework)
        result = client.result(client.submit(self._request()))
        self.assertEqual(result.status, "failed")
        self.assertIn("framework component exploded", result.error["message"])
        self.assertEqual(framework.released, [1])

    def test_classical_actor_create_call_terminate_lifecycle(self) -> None:
        framework = _DocumentedFramework()
        framework.add_component(
            "h2o-classical-predict",
            ClassicalPredictSessionsComponent,
            actor=True,
        )
        client = FusionExecutionClient(framework)
        request = ActorRequest(
            run_id="bridge actor:run/中文",
            actor_id="bridge actor:id/中文",
            actor_type="classical_predict",
            payload={
                "checkpoint_path": str(CHECKPOINT),
                "device": "cpu",
                "require_gpu": False,
            },
            resources=ResourceRequest(cpu=1.0),
        )
        handle = client.create_actor(request)
        result = client.call_actor(
            handle,
            ActorCallRequest(
                run_id=handle.run_id,
                task_id="bridge actor:call/中文",
                method="predict",
                payload={
                    "request_id": "bridge-predict",
                    "sample_ids": ["sample-0"],
                    "features": [[0.0] * 14],
                },
            ),
        )
        self.assertTrue(client.terminate_actor(handle))
        self.assertEqual(result.status, "succeeded", result.error)
        self.assertEqual(len(result.outputs["energies_eV"]), 1)
        self.assertEqual(len(framework.released), 3)

    def test_registration_maps_h2o_resources_without_importing_ray(self) -> None:
        framework_module = ModuleType("pivotq._internal.framework")

        class ExecutionMode:
            TASK = "task"
            ACTOR = "actor"

        class FrameworkResourceRequest:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class ComponentSpec:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        framework_module.ExecutionMode = ExecutionMode
        framework_module.ResourceRequest = FrameworkResourceRequest
        framework_module.ComponentSpec = ComponentSpec
        package_module = ModuleType("pivotq._internal")
        package_module.framework = framework_module
        framework = _DocumentedFramework()
        with patch.dict(
            sys.modules,
            {"pivotq._internal": package_module, "pivotq._internal.framework": framework_module},
        ):
            ids = register_fusion_components(framework, load_config(CONFIG_PATH))
        self.assertEqual(ids.quantum_cpu, "h2o-f2-quantum-features-cpu")
        self.assertIn(ids.quantum_cpu, framework.components)
        self.assertIn(ids.quantum_gpu, framework.components)
        self.assertIn(ids.classical_actor, framework.components)
        self.assertNotIn(ids.quantum_qpu, framework.components)

    def test_runner_builds_cpu_coordinator_request_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = _Context(Path(directory))
            environment = {
                "AIMD_CONFIG_PATH": str(CONFIG_PATH),
                "AIMD_CHECKPOINT_PATH": str(CHECKPOINT),
                "AIMD_EXECUTION_MODE": "heterogeneous",
                "AIMD_QUANTUM_TARGET": "gpu",
                "AIMD_TASK_ID": "runner-build-request.aimd",
                "AIMD_CONFIG_OVERRIDES_JSON": "{}",
            }
            with patch.dict(os.environ, environment, clear=False):
                request = _build_request(context)
        self.assertEqual(request.resources.cpu, 1.0)
        self.assertEqual(request.resources.gpu, 0.0)
        self.assertEqual(request.quantum_target, "gpu")
        self.assertEqual(request.config_path, str(CONFIG_PATH))

    def test_job_spec_uses_standalone_targets_and_no_bytecode(self) -> None:
        class RuntimeEnvironment:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class DriverResources:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class JobSpec:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        jobs = type(
            "Jobs",
            (),
            {
                "RayJobRuntimeEnvironment": RuntimeEnvironment,
                "RayJobDriverResources": DriverResources,
                "RayJobSpec": JobSpec,
            },
        )
        with patch(
            "single_h20_aimd.integration.fusion_framework.submit_job._jobs_api",
            return_value=jobs,
        ):
            spec = build_job_spec(
                submission_id="h2o-f2-test",
                working_dir=str(PROJECT_ROOT),
                config_path="/cluster/single_h20_aimd/configs/h2o_aimd.yaml",
                checkpoint_path="/cluster/single_h20_aimd/checkpoints/hybrid_model.pt",
                output_dir="/cluster/single_h20_aimd/outputs/fusion/h2o-f2-test",
            )
        self.assertIn(REGISTRATION_TARGET, spec.entrypoint)
        self.assertIn(RUNNER_TARGET, spec.entrypoint)
        self.assertEqual(spec.runtime_environment.env_vars["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(spec.metadata["scientific_scope"], "h2o-f2-adapt-energy-force-nve-aimd")

    def test_job_spec_accepts_qpu_target_and_registers_framework_backend(self) -> None:
        class RuntimeEnvironment:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class DriverResources:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class JobSpec:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        jobs = type(
            "Jobs",
            (),
            {
                "RayJobRuntimeEnvironment": RuntimeEnvironment,
                "RayJobDriverResources": DriverResources,
                "RayJobSpec": JobSpec,
            },
        )
        internal_package = ModuleType("pivotq._internal")
        qpu_integration = ModuleType("pivotq._internal.qpu_integration")
        qpu_registration = ModuleType("pivotq._internal.qpu_integration.registration")
        qpu_registration.QOS_HELPER_MODULE_ENV = "QOS_HELPER_MODULE"
        qpu_registration.QOS_DATA_TREE_TARGET_ENV = "QOS_DATA_TREE_TARGET"
        qpu_integration.registration = qpu_registration
        internal_package.qpu_integration = qpu_integration
        with patch.dict(
            sys.modules,
            {
                "pivotq._internal": internal_package,
                "pivotq._internal.qpu_integration": qpu_integration,
                "pivotq._internal.qpu_integration.registration": qpu_registration,
            },
        ), patch(
            "single_h20_aimd.integration.fusion_framework.submit_job._jobs_api",
            return_value=jobs,
        ):
            spec = build_job_spec(
                submission_id="h2o-f2-qpu-test",
                working_dir=str(PROJECT_ROOT),
                config_path="/cluster/single_h20_aimd/configs/h2o_aimd.yaml",
                checkpoint_path="/cluster/single_h20_aimd/checkpoints/model.pt",
                output_dir="/cluster/single_h20_aimd/outputs/fusion/h2o-f2-qpu-test",
                quantum_target="qpu",
                qos_helper_module="provider_qpu_backend",
                qos_data_tree_target="provider_qpu_backend:DataTree",
            )
        self.assertEqual(spec.runtime_environment.env_vars["AIMD_QUANTUM_TARGET"], "qpu")
        self.assertEqual(
            spec.runtime_environment.env_vars["QOS_HELPER_MODULE"],
            "provider_qpu_backend",
        )
        self.assertEqual(
            spec.runtime_environment.env_vars["QOS_DATA_TREE_TARGET"],
            "provider_qpu_backend:DataTree",
        )


def np_shape(values) -> tuple[int, ...]:
    if not isinstance(values, list):
        return ()
    if not values:
        return (0,)
    if isinstance(values[0], list):
        return (len(values), len(values[0]))
    return (len(values),)


if __name__ == "__main__":
    unittest.main()
