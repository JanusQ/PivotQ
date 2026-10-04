"""Validate H2O GPU/QPU requests through framework simulation on local CPUs.

Run from the unified environment: ``python tests/integration/run_cpu_aimd.py``.
The default trajectory is the frozen 1000-step experiment; ``--steps`` is only
a temporary smoke-test override. The framework substitutes CPU simulators for
the application's GPU/QPU components; no hardware provider is contacted.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
from uuid import uuid4


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APPLICATION_ROOT = REPOSITORY_ROOT / "applications/h2o-hybrid-aimd"
QUANTUM_COMPONENTS = {
    "qpu": "qpu-circuits",
    "gpu": "h2o-f2-quantum-features-gpu",
}
CLASSICAL_COMPONENT = "h2o-classical-predict"


def source_manifest() -> dict[str, str]:
    """Hash the executed source trees, locked environment, and frozen inputs."""
    files = {
        REPOSITORY_ROOT / "pyproject.toml",
        REPOSITORY_ROOT / "uv.lock",
        Path(__file__).resolve(),
        APPLICATION_ROOT / "configs/h2o_aimd.yaml",
        APPLICATION_ROOT / "checkpoints/hybrid_model.pt",
    }
    for directory in (
        REPOSITORY_ROOT / "packages/framework/pivotq",
        APPLICATION_ROOT / "single_h20_aimd",
    ):
        files.update(directory.rglob("*.py"))
    return {
        str(path.relative_to(REPOSITORY_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
    }


def git_baseline() -> dict[str, str]:
    """Record the checkout while source hashes identify uncommitted code."""
    return {
        key: subprocess.check_output(
            ["git", *arguments], cwd=REPOSITORY_ROOT, text=True
        ).strip()
        for key, arguments in (
            ("commit", ["rev-parse", "HEAD"]),
            ("branch", ["branch", "--show-current"]),
            ("status_porcelain", ["status", "--porcelain=v1"]),
        )
    }


def runtime_overrides(steps: int) -> dict:
    """Override trajectory length while preserving GPU/QPU scheduling intent."""
    return {"aimd": {"steps": steps}}


def validate_outputs(output: Path, run_id: str, steps: int, quantum_target: str) -> dict:
    """Check scientific acceptance and requested versus actual execution."""
    import numpy as np
    import yaml
    from ase.io.trajectory import Trajectory

    manifest = json.loads((output / f"{run_id}.manifest.json").read_text())
    result = json.loads((output / f"{run_id}.aimd-result.json").read_text())
    metrics = json.loads((output / "aimd/metrics.json").read_text())
    simulation = metrics["simulation"]
    records = [
        json.loads(line)
        for line in (output / f"{run_id}.trace.jsonl").read_text().splitlines()
        if line.strip()
    ]
    quantum_component = QUANTUM_COMPONENTS[quantum_target]
    quantum = [record for record in records if record["component_id"] == quantum_component]
    classical = [record for record in records if record["component_id"] == CLASSICAL_COMPONENT]
    actor_ids = {record["execution_ids"]["actor_id"] for record in classical}
    quantum_actor_ids = {record["execution_ids"]["actor_id"] for record in quantum}
    runtime_execution = manifest.get("runtime_execution", {})
    result_runtime = result["outputs"].get("runtime_execution", {})
    requested_execution = result["outputs"].get("requested_execution", {})
    selections = {
        selection["component_id"]: selection
        for selection in runtime_execution.get("selections", [])
    }
    expected_devices = {
        quantum_component: quantum_target.upper(),
        CLASSICAL_COMPONENT: "GPU",
    }
    declared_config = yaml.safe_load((APPLICATION_ROOT / "configs/h2o_aimd.yaml").read_text())
    resolved_config = yaml.safe_load((output / "aimd/resolved_config.yaml").read_text())
    with Trajectory(simulation["trajectory"], "r") as trajectory:
        frame_count = len(trajectory)
        frames_finite = all(np.isfinite(atoms.positions).all() for atoms in trajectory)
    with Path(simulation["log"]).open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    artifact_entries = result["outputs"]["artifact_manifest"]
    artifacts_valid = bool(artifact_entries) and all(
        hashlib.sha256((output / entry["relative_path"]).read_bytes()).hexdigest()
        == entry["sha256"]
        for entry in artifact_entries
    )
    checks = {
        "driver_succeeded": manifest["status"] == "succeeded",
        "driver_resources_cleaned": manifest["cleanup"]["succeeded"],
        "application_succeeded": result["status"] == "succeeded",
        "scientific_acceptance_passed": result["outputs"]["scientific_status"] == "passed"
        and metrics["acceptance"]["passed"]
        and all(metrics["acceptance"]["checks"].values()),
        "trajectory_frames_match": frame_count == steps + 1 and frames_finite,
        "log_steps_and_time_match": len(rows) == steps + 1
        and [int(row["step"]) for row in rows] == list(range(steps + 1))
        and bool(np.isclose(float(rows[-1]["time_fs"]), steps * 0.1)),
        "quantum_component_scheduled": len(quantum) >= steps + 1
        and all(
            record["execution_mode"] == ("actor" if quantum_target == "qpu" else "task")
            and record["method"] == ("run_quantum_circuits" if quantum_target == "qpu" else "execute")
            for record in quantum
        )
        and (
            quantum_target != "qpu"
            or len(quantum_actor_ids) == 1 and None not in quantum_actor_ids
        ),
        "persistent_classical_actor_used": len(classical) >= steps + 3
        and len(actor_ids) == 1
        and None not in actor_ids
        and {record["method"] for record in classical} == {"create", "call", "terminate"}
        and all(record["execution_mode"] == "actor" for record in classical),
        "all_invocations_succeeded_on_ray": bool(records)
        and all(
            record["status"] == "succeeded"
            and record["backend"] == "ray"
            and record["execution_ids"]["task_id"]
            and record["execution_ids"]["node_id"]
            for record in records
        ),
        "only_cpu_resources_executed": bool(records)
        and all(
            record["component_id"] in expected_devices
            and record["resources"]["num_gpus"] == 0
            and not record["resources"]["custom_resources"]
            for record in records
        ),
        "framework_selected_cpu_simulators": runtime_execution.get("simulation_enabled") is True
        and all(
            component_id in selections
            and selections[component_id].get("simulated") is True
            and selections[component_id].get("reason") == "hardware_unavailable"
            and device in selections[component_id].get("requested_devices", [])
            and selections[component_id].get("actual_devices") == ["CPU"]
            and selections[component_id]["effective_resources"]["num_gpus"] == 0
            and not selections[component_id]["effective_resources"]["custom_resources"]
            for component_id, device in expected_devices.items()
        ),
        "trace_identifies_requested_and_actual_devices": bool(records)
        and all(
            record["trace_context"].get("simulation.enabled") == "true"
            and record["trace_context"].get("simulation.simulated") == "true"
            and json.loads(record["trace_context"].get("simulation.actual_devices", "null")) == ["CPU"]
            and expected_devices.get(record["component_id"])
            in json.loads(record["trace_context"].get("simulation.requested_devices", "[]"))
            for record in records
        ),
        "application_hardware_schedule_preserved": resolved_config["scheduling"] == declared_config["scheduling"],
        "application_requested_devices_preserved": requested_execution.get("mode") == "heterogeneous"
        and requested_execution.get("quantum_target") == quantum_target
        and requested_execution.get("classical_actor_target") == "gpu",
        "runtime_reports_consistent": result_runtime.get("simulation_enabled") is True
        and result_runtime.get("selections") == runtime_execution.get("selections"),
        "artifact_hashes_match": artifacts_valid,
    }
    if quantum_target == "qpu":
        qpu_simulation = result_runtime.get("qpu_simulation", {})
        checks["qpu_returns_exact_probabilities_without_hardware_shots"] = (
            qpu_simulation.get("simulation") is True
            and qpu_simulation.get("simulation_backend") == "qiskit_statevector"
            and qpu_simulation.get("mode") == "exact_probabilities"
            and qpu_simulation.get("actual_device") == "cpu"
            and qpu_simulation.get("real_hardware") is False
            and qpu_simulation.get("sampling") is False
            and qpu_simulation.get("supports_noise") is False
            and qpu_simulation.get("requested_shots")
            == declared_config["scheduling"]["quantum_targets"]["qpu"]["execution"]["shots"]
            and qpu_simulation.get("effective_shots") is None
            and qpu_simulation.get("shots_per_measurement_basis") is None
            and qpu_simulation.get("total_physical_executions") == 0
        )
        checks["qpu_simulation_counters_match_framework_calls"] = (
            qpu_simulation.get("total_batches") == len(quantum)
            and qpu_simulation.get("total_circuit_evaluations", 0) >= len(quantum)
            and qpu_simulation.get("total_measurement_circuit_settings", 0)
            == 2 * qpu_simulation.get("total_circuit_evaluations", 0)
        )
    return {
        "passed": bool(all(checks.values())),
        "checks": checks,
        "scientific_checks": metrics["acceptance"]["checks"],
        "simulation": simulation,
        "framework_invocations": dict(Counter(record["component_id"] for record in records)),
        "requested_execution": requested_execution,
        "runtime_execution": result_runtime,
        "classical_actor_ids": sorted(actor_ids, key=str),
        "quantum_actor_ids": sorted(quantum_actor_ids, key=str) if quantum_target == "qpu" else [],
        "artifact_count": len(artifact_entries),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--quantum-target", choices=("qpu", "gpu"), default="qpu")
    parser.add_argument("--run-id")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.steps < 1:
        parser.error("--steps must be positive")
    run_id = args.run_id or (
        f"sim-{args.quantum_target}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}"
    )
    output = (
        args.output_dir or APPLICATION_ROOT / "outputs/integration" / run_id
    ).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        parser.error(f"output directory must be empty: {output}")

    # Both the coordinator and its worker processes inherit these restrictions.
    environment = {
        "CUDA_VISIBLE_DEVICES": "",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MPLBACKEND": "Agg",
        "PYTHONDONTWRITEBYTECODE": "1",
        "RAY_USAGE_STATS_ENABLED": "0",
        "AIMD_CONFIG_PATH": str(APPLICATION_ROOT / "configs/h2o_aimd.yaml"),
        "AIMD_CHECKPOINT_PATH": str(APPLICATION_ROOT / "checkpoints/hybrid_model.pt"),
        "AIMD_EXECUTION_MODE": "heterogeneous",
        "AIMD_QUANTUM_TARGET": args.quantum_target,
        "AIMD_CONFIG_OVERRIDES_JSON": json.dumps(runtime_overrides(args.steps)),
    }
    os.environ.update(environment)
    os.environ.pop("RAY_ADDRESS", None)
    # This launcher specifically validates simulation, so inherited device
    # bindings must not make a real provider appear available to the framework.
    for name in (
        "QPU_DEVICE_CONFIG_FILE",
        "QPU_DEVICE_ID",
        "QPU_DEVICE_URL",
        "QPU_DEVICE_API_KEY",
        "QPU_COMPONENT_ID",
        "QPU_CUSTOM_RESOURCES_JSON",
        "QPU_JOB_JOURNAL_DIR",
    ):
        os.environ.pop(name, None)
    import ray
    from pivotq._internal.jobs.driver import RayJobDriverConfig, run_driver

    if ray.is_initialized():
        parser.error("run this launcher in a fresh Python process")
    config = RayJobDriverConfig(
        run_id=run_id,
        registration_target="pivotq._internal.integrations.h2o:register_components",
        runner_target="pivotq._internal.integrations.h2o:run",
        namespace=run_id,
        output_dir=str(output),
        trace_max_records=max(20_000, args.steps * 32 + 1000),
        simulation=True,
    )
    output.mkdir(parents=True, exist_ok=True)
    ray_temp = tempfile.mkdtemp(prefix="qhai-aimd-ray-")
    validation = {
        "passed": False,
        "run_id": run_id,
        "scope": "framework simulation of requested GPU/QPU components on local CPU Ray workers",
        "ray_temp_dir": ray_temp,
        "steps": args.steps,
        "quantum_target": args.quantum_target,
        "framework_simulation": True,
        "python": platform.python_version(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("ray", "torch", "numpy", "qiskit", "ase")
        },
        "overrides": runtime_overrides(args.steps),
        "git_baseline": git_baseline(),
        "source_sha256": source_manifest(),
    }
    print(f"AIMD_OUTPUT_DIR={output}", flush=True)
    try:
        # Explicit local avoids attaching to another user's existing Ray cluster.
        ray.init(
            address="local",
            namespace=run_id,
            num_cpus=4,
            num_gpus=0,
            include_dashboard=False,
            log_to_driver=True,
            _temp_dir=ray_temp,
            object_store_memory=256 * 1024 * 1024,
        )
        manifest = run_driver(config)
        validation["driver_manifest"] = manifest.as_dict()
        if manifest.exit_code == 0:
            validation.update(validate_outputs(output, run_id, args.steps, args.quantum_target))
        else:
            result_path = output / f"{run_id}.aimd-result.json"
            if result_path.exists():
                validation["application_error"] = json.loads(result_path.read_text()).get("error")
    except Exception as error:
        validation["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        ray.shutdown()
        validation["local_ray_shutdown"] = not ray.is_initialized()
        try:
            final_sources = source_manifest()
            original_sources = validation["source_sha256"]
            validation["source_changes"] = {
                name: {"before": original_sources.get(name), "after": final_sources.get(name)}
                for name in sorted(original_sources.keys() | final_sources.keys())
                if original_sources.get(name) != final_sources.get(name)
            }
            validation.setdefault("checks", {})["source_manifest_unchanged"] = not validation["source_changes"]
        except Exception as error:
            validation.setdefault("checks", {})["source_manifest_unchanged"] = False
            validation["source_manifest_error"] = {"type": type(error).__name__, "message": str(error)}
        validation["passed"] = bool(
            validation["passed"]
            and validation["local_ray_shutdown"]
            and validation["checks"]["source_manifest_unchanged"]
        )
        (output / "validation.json").write_text(
            json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    console_result = {key: value for key, value in validation.items() if key != "source_sha256"}
    console_result["source_file_count"] = len(validation["source_sha256"])
    print(json.dumps(console_result, ensure_ascii=False, indent=2), flush=True)
    return 0 if validation["passed"] and validation["local_ray_shutdown"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
