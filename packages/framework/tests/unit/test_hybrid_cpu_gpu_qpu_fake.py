"""Fast contract tests for the bounded CPU/GPU/fake-QPU example."""

from __future__ import annotations

from pathlib import Path
import os
import unittest
from unittest.mock import patch

from examples.hybrid_cpu_gpu_qpu_fake.registration import (
    CPU_COMPONENT_ID,
    GPU_COMPONENT_ID,
    register_components,
)
from examples.hybrid_cpu_gpu_qpu_fake.submit_job import (
    _terminal_exit_code,
    build_job_spec,
)
from pivotq._internal.jobs import RayJobStatus
from pivotq._internal.qpu_integration.component import DEFAULT_QPU_COMPONENT_ID


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class HybridFakeRegistrationTest(unittest.TestCase):
    def test_registration_preserves_cpu_gpu_requests_without_client_marker(self) -> None:
        recorder = _Recorder()
        register_components(recorder)  # type: ignore[arg-type]

        by_id = {spec.component_id: spec for spec, _ in recorder.items}
        self.assertEqual(set(by_id), {CPU_COMPONENT_ID, GPU_COMPONENT_ID, DEFAULT_QPU_COMPONENT_ID})
        self.assertEqual(by_id[CPU_COMPONENT_ID].resources.custom_resources_dict(), {"CPU_HEAD": 0.001})
        self.assertEqual(by_id[GPU_COMPONENT_ID].resources.num_gpus, 1.0)
        self.assertEqual(by_id[DEFAULT_QPU_COMPONENT_ID].resources.custom_resources_dict(), {})
        self.assertEqual(by_id[DEFAULT_QPU_COMPONENT_ID].resources.num_cpus, 0.5)
        self.assertEqual(by_id[DEFAULT_QPU_COMPONENT_ID].max_concurrency, 1)

    def test_job_uses_deployable_fakes_and_no_hardware_claim(self) -> None:
        spec = build_job_spec(
            submission_id="hybrid-fake-001",
            working_dir=str(_PROJECT_ROOT),
            output_dir="/opt/ray-quantum/artifacts",
        )
        environment = spec.runtime_environment.as_ray_dict()["env_vars"]
        self.assertEqual(environment, {"PYTHONPATH": "src:."})
        self.assertEqual(spec.metadata_dict()["fixed_count_fixture"], "true")
        self.assertEqual(spec.metadata_dict()["qpu_hardware_used"], "false")
        self.assertIn("--trace-max-records 3", spec.entrypoint)

    def test_submitter_returns_zero_only_for_succeeded_status(self) -> None:
        self.assertEqual(_terminal_exit_code(RayJobStatus.SUCCEEDED), 0)
        for status in (
            RayJobStatus.PENDING,
            RayJobStatus.RUNNING,
            RayJobStatus.STOPPED,
            RayJobStatus.FAILED,
        ):
            with self.subTest(status=status):
                self.assertEqual(_terminal_exit_code(status), 1)


class _Recorder:
    def __init__(self) -> None:
        self.items: list[tuple[object, object]] = []

    def register(self, spec: object, factory: object):
        self.items.append((spec, factory))
        return object()


if __name__ == "__main__":
    unittest.main()
