from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest


class FrameworkAimdIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import ray

        if ray.is_initialized():
            raise RuntimeError("integration test requires a fresh Python process")
        os.environ.pop("RAY_ADDRESS", None)
        cls.ray_temp = tempfile.TemporaryDirectory(prefix="qhai-integration-ray-")
        ray.init(
            address="local",
            num_cpus=2,
            num_gpus=0,
            include_dashboard=False,
            log_to_driver=False,
            _temp_dir=cls.ray_temp.name,
            object_store_memory=256 * 1024 * 1024,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        import ray

        ray.shutdown()
        cls.ray_temp.cleanup()

    def test_aimd_quantum_component_runs_through_ray_framework(self) -> None:
        from pivotq._internal.executors import RayExecutor
        from pivotq._internal.framework import (
            ComponentRegistry,
            ComponentSpec,
            ExecutionMode,
            FusionFramework,
            ResourceRequest,
        )
        from single_h20_aimd.execution import TaskRequest
        from single_h20_aimd.integration.fusion_framework.components import (
            StatevectorQuantumFeaturesComponent,
        )
        from single_h20_aimd.integration.fusion_framework.fusion_client import (
            FusionExecutionClient,
        )

        application_root = (
            Path(__file__).resolve().parents[2] / "applications/h2o-hybrid-aimd"
        )
        request_path = (
            application_root
            / "single_h20_aimd/integration/fusion_framework/example_quantum_request.json"
        )
        request = TaskRequest.from_dict(
            json.loads(request_path.read_text(encoding="utf-8"))
        )

        registry = ComponentRegistry()
        executor = RayExecutor(registry)
        framework = FusionFramework(executor)
        try:
            framework.register(
                ComponentSpec(
                    component_id="h2o-f2-quantum-features-cpu",
                    execution=ExecutionMode.TASK,
                    resources=ResourceRequest(num_cpus=1.0),
                    allowed_methods=("execute",),
                    timeout_seconds=60.0,
                ),
                StatevectorQuantumFeaturesComponent,
            )
            client = FusionExecutionClient(framework)
            result = client.result(client.submit(request))

            self.assertEqual(result.status, "succeeded", result.error)
            self.assertEqual(len(result.outputs["features"]), 2)
            self.assertTrue(
                all(len(row) == 14 for row in result.outputs["features"])
            )
        finally:
            try:
                framework.close()
            finally:
                registry.close()


if __name__ == "__main__":
    unittest.main()
