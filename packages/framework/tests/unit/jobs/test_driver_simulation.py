"""Driver carries explicit simulation provenance without changing normal manifests."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from pivotq._internal.framework import ComponentSpec, ExecutionMode, ResourceRequest
from pivotq._internal.jobs.driver import RayJobDriverConfig, RayJobDriverStatus, main, run_driver
from tests.unit.jobs.test_driver import _FakeRay, _FakeRayExecutor
from tests.unit.framework.test_simulation import CpuCounter, NativeCounter


def test_driver_manifest_retains_requested_and_actual_execution_after_cleanup(tmp_path):
    config = RayJobDriverConfig(
        run_id="sim-run", registration_target="fixture:register", runner_target="fixture:run",
        namespace="p72-tests", output_dir=tmp_path, simulation=True,
    )
    def register(framework):
        framework.register(ComponentSpec("gpu", ExecutionMode.TASK,
                           ResourceRequest(num_gpus=1), ("increment",)), NativeCounter)
        framework.register_simulation_adapter(
            "gpu", factory=CpuCounter, resources=ResourceRequest(),
            required_devices=("GPU",), availability=lambda: False,
        )
    def run(framework, context):
        assert framework.simulation
        assert framework.resolve_execution("gpu").simulated
    with patch("pivotq._internal.jobs.driver._load_callable", side_effect=[register, run]), \
         patch("pivotq._internal.jobs.driver._load_ray_module", return_value=_FakeRay()), \
         patch("pivotq._internal.jobs.driver._load_ray_executor", return_value=_FakeRayExecutor):
        result = run_driver(config)
    assert result.status is RayJobDriverStatus.SUCCEEDED
    record = json.loads(config.manifest_path.read_text())["runtime_execution"]
    assert record["simulation_enabled"] is True
    assert record["selections"][0]["requested_devices"] == ["GPU"]
    assert record["selections"][0]["actual_devices"] == ["CPU"]


def test_driver_cli_requires_explicit_simulation_flag(tmp_path):
    base = ["--run-id", "test", "--registration", "fixture:register", "--runner", "fixture:run",
            "--namespace", "test", "--output-dir", str(tmp_path)]
    terminal = SimpleNamespace(status=RayJobDriverStatus.SUCCEEDED, exit_code=0)
    with patch("pivotq._internal.jobs.driver.run_driver", return_value=terminal) as run:
        assert main(base) == 0
        assert run.call_args.args[0].simulation is False
        assert main([*base, "--simulation"]) == 0
        assert run.call_args.args[0].simulation is True
