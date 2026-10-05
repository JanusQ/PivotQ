"""Numerical and dataset evidence; writes a compact auditable report."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import h5py
import numpy as np
from water20.circuit import build, native, validate_templates
from water20.model import Model
from water20.potential import Potential
from water20.simulator import ExactSimulator, native_gates


def main(args):
    start = time.monotonic()
    report = dict(schema_version=1, status="running", host=platform.node(), python=sys.version,
                  training_updates=0, scientific_status="not_validated", real_qpu_validated=False)
    model = Model()
    _, blocks = validate_templates(model.config)
    report["semantic_structure"] = dict(shared_parameters=48, classical_parameters=9857, block_checks=blocks,
        order="encoding1B2B3B_trainable1B2B3B", n_qubits=60, terminal_features=120,
        encoding_policy="continuous_no_floor; bx/by share one orientation slot as v4 AIMD")
    run = subprocess.run([sys.executable, "-B", "-m", "pytest", str(ROOT/"tests"), "-q", "-p", "no:cacheprovider"],
                         capture_output=True, text=True)
    report["pytest"] = dict(returncode=run.returncode, stdout=run.stdout, stderr=run.stderr)
    if run.returncode:
        raise RuntimeError("Tests failed: "+run.stdout+run.stderr)
    checks = []
    with h5py.File(ROOT/"dataset_water20_mbpol_v1/water20.h5") as h:
        for index in (0, 1500, 3499):
            x = h["positions_angstrom"][index]
            gates, groups = model.gates(x)
            source_sampler, transpiled_sampler = ExactSimulator(), ExactSimulator()
            features = source_sampler.evaluate(gates)
            circuit = native(build(gates))
            compiled = transpiled_sampler.evaluate(native_gates(circuit))
            difference = float(np.max(np.abs(features-compiled)))
            if difference > 1e-10:
                raise ArithmeticError("60-qubit native/source observable mismatch")
            potential = Potential(model, source_sampler)
            energy, forces = potential.energy_force(x)
            force_errors = []
            for coordinate in (0, 7, 90, 179):
                plus, minus = x.copy(), x.copy()
                plus.flat[coordinate] += 2e-5
                minus.flat[coordinate] -= 2e-5
                fd = -(potential.energy(plus)-potential.energy(minus))/4e-5
                force_errors.append(float(abs(fd-forces.flat[coordinate])))
            if max(force_errors) > 3e-5:
                raise ArithmeticError("60-qubit model force/energy finite difference mismatch")
            checks.append(dict(sample_index=index, sample_id=h["sample_id"].asstr()[index],
                active_pairs=len(groups[2]), active_triples=len(groups[3]), logical_rotations=len(gates),
                native_gates=len(circuit.data), native_depth=circuit.depth(), max_observable_difference=difference,
                max_force_check_difference_ev_per_angstrom=max(force_errors), energy_ev=energy,
                net_force_ev_per_angstrom=forces.sum(0).tolist(), execution_metadata=source_sampler.last_metadata))
        if args.library:
            from water20.reference import MBX
            config = json.loads((ROOT/"configs/dataset.json").read_text())
            reference = MBX(args.library, config["mbx_settings"])
            x = h["positions_angstrom"][0]
            energy, force = reference.evaluate(x)
            saved_energy, saved_force = float(h["energy_ev"][0]), h["forces_ev_per_angstrom"][0]
            eps = 1e-5
            plus, minus = x.copy(), x.copy()
            plus[0, 0] += eps
            minus[0, 0] -= eps
            fd = -(reference.evaluate(plus)[0]-reference.evaluate(minus)[0])/(2*eps)
            report["mbx_label_audit"] = dict(energy_recompute_error_ev=abs(energy-saved_energy),
                max_force_recompute_error_ev_per_angstrom=float(np.max(abs(force-saved_force))),
                force_finite_difference_error_ev_per_angstrom=float(abs(fd-force[0, 0])))
            if abs(energy-saved_energy) > 1e-9 or np.max(abs(force-saved_force)) > 1e-8 or abs(fd-force[0, 0]) > 1e-4:
                raise ArithmeticError("MBX label/force verification failed")
    report["full_water20_checks"] = checks
    report["versions"] = {name: importlib.metadata.version(name) for name in ("numpy", "qiskit", "ase", "h5py", "httpx", "pytest")}
    report["model_status"] = model.metadata["model_status"]
    report["model_sha256"] = model.metadata["checkpoint_sha256"]
    report.update(status="passed", wall_seconds=time.monotonic()-start)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({k: report[k] for k in ("status", "host", "wall_seconds", "training_updates")}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--library", help="Optional external MBX adapter for independent label audit")
    p.add_argument("--output", type=Path, default=ROOT/"reports/validation.json")
    main(p.parse_args())
