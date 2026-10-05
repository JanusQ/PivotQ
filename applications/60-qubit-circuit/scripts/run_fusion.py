"""One actual Ray quantum -> classical application Job, simulation=False."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(args):
    import h5py
    import ray
    from ray_quantum.executors.ray import RayExecutor
    from ray_quantum.framework import ComponentRegistry, FusionFramework
    from ray_quantum.observability import TraceCollector, export_trace_jsonl
    from water20.fusion import register, FusionEnergy
    args.output.mkdir(parents=True, exist_ok=False)
    with h5py.File(ROOT/"dataset_water20_mbpol_v1/water20.h5") as h:
        if h["split"].asstr()[0] != "train":
            raise ValueError("Use training geometry for execution checks")
        x = h["positions_angstrom"][0]
    namespace = "water20-"+uuid.uuid4().hex
    env = {"PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
    # Credentials stay in the process runtime environment, never report files.
    env.update({k: os.environ[k] for k in ("QPU_DEVICE_URL", "QPU_DEVICE_API_KEY") if k in os.environ})
    if args.address:
        ray.init(address=args.address, namespace=namespace, runtime_env={"env_vars": env})
    else:
        ray.init(num_cpus=2, namespace=namespace, include_dashboard=False,
                 object_store_memory=256*1024**2, _temp_dir=tempfile.mkdtemp(prefix="w20-ray-"),
                 runtime_env={"env_vars": env})
    registry, trace = ComponentRegistry(), TraceCollector()
    executor = RayExecutor(registry, actor_namespace=namespace, trace_collector=trace)
    framework = FusionFramework(executor, simulation=False)
    report = dict(backend=args.backend, training_updates=0, scientific_status="not_validated", namespace=namespace)
    start = time.monotonic()
    try:
        register(framework, ROOT, backend=args.backend, profile=args.profile,
                 journal=args.output/"qpu_journal", shots=args.shots)
        potential = FusionEnergy(framework, ROOT)
        report.update(energy_ev=potential.energy(x), second_energy_ev=potential.energy(x),
                      metadata=potential.last_metadata, execution_report=framework.execution_report(),
                      geometry_sha256=hashlib.sha256(x.tobytes()).hexdigest(), status="succeeded")
        if report["metadata"]["classical_calls"] != 2:
            raise RuntimeError("Classical Actor was not persistent")
        if args.backend == "cpu" and abs(report["energy_ev"]-report["second_energy_ev"]) > 1e-12:
            raise ArithmeticError("Repeated exact CPU energies differ")
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        framework.close()
        registry.close()
        report["wall_seconds"] = time.monotonic()-start
        report["executor_closed"] = executor.closed
        export_trace_jsonl(trace.snapshot(), args.output/"framework_trace.jsonl")
        (args.output/"summary.json").write_text(json.dumps(report, indent=2)+"\n")
        ray.shutdown()
    print(json.dumps({k: report[k] for k in ("status", "backend", "wall_seconds", "energy_ev")}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend", choices=("cpu", "qpu"), default="cpu")
    p.add_argument("--profile", type=Path, default=ROOT/"configs/hardware_profile.template.json")
    p.add_argument("--shots", type=int, default=3000)
    p.add_argument("--address", help="Optional existing Ray cluster address")
    p.add_argument("--output", type=Path, required=True)
    main(p.parse_args())
