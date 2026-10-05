"""Inference and short AIMD execution; never train or update weights."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import h5py
import numpy as np
from ase import Atoms, units
from ase.io import write
from ase.md.velocitydistribution import MaxwellBoltzmannDistribution, Stationary, ZeroRotation
from ase.md.verlet import VelocityVerlet

from water20.hardware import HardwareProfile
from water20.model import Model
from water20.potential import ASEPotential, Potential, DEFAULT_COORDINATE_FD_STEP
from water20.qpu import QPUClient
from water20.simulator import ExactSimulator


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    model = Model(ROOT)
    if args.geometry:
        geometry = json.loads(args.geometry.read_text())
        if geometry.get("atomic_numbers") != [8, 1, 1]*20 or geometry.get("pbc") is not False:
            raise ValueError("Input must be isolated water20 in fixed OHH order")
        x = np.array(geometry["positions_angstrom"], dtype=float)
        sample_id = geometry.get("sample_id", "external")
    else:
        with h5py.File(ROOT/"dataset_water20_mbpol_v1/water20.h5") as dataset:
            if dataset["split"].asstr()[args.sample_index] != "train":
                raise ValueError("Default validation run must use a training geometry")
            x = dataset["positions_angstrom"][args.sample_index]
            sample_id = dataset["sample_id"].asstr()[args.sample_index]
    (output/"input.json").write_text(json.dumps(dict(sample_id=sample_id, atomic_numbers=[8, 1, 1]*20,
                                                   pbc=False, positions_angstrom=x.tolist()), indent=2)+"\n")
    if args.backend == "qpu":
        profile = HardwareProfile.load(args.hardware_profile)
        sampler = QPUClient(profile, output/"qpu_journal", timeout_seconds=args.timeout)
        sampler.shots = args.shots
        method = args.force_method or "coordinate_fd"
    else:
        sampler = ExactSimulator()
        method = args.force_method or "adjoint"
    potential = Potential(model, sampler)
    start = time.monotonic()
    summary = dict(status="running", backend=args.backend, mode=args.mode, sample_id=sample_id, host=platform.node(),
                   n_atoms=60, n_qubits=60, n_features=120, model_status=model.metadata["model_status"],
                   training_updates=0, scientific_status="not_validated", force_method=method,
                   force_geometry_derivative=("central_difference_of_total_energy" if method == "coordinate_fd"
                                              else "central_difference_of_continuous_classical_encoder"),
                   fd_step_angstrom=args.fd_step_angstrom if method == "coordinate_fd" else None,
                   shots_per_circuit=args.shots if args.backend == "qpu" else None,
                   geometry_sha256=hashlib.sha256(x.tobytes()).hexdigest(),
                   model_sha256=model.metadata["checkpoint_sha256"])
    try:
        if args.mode == "energy":
            summary["energy_ev"] = potential.energy(x)
        elif args.mode == "energy_force":
            energy, force = (potential.coordinate_fd(x, step=args.fd_step_angstrom) if method == "coordinate_fd" else
                             potential.energy_force(x, method=method))
            summary.update(energy_ev=energy, forces_ev_per_angstrom=force.tolist(),
                           net_force_ev_per_angstrom=force.sum(0).tolist())
        else:
            atoms = Atoms(numbers=[8, 1, 1]*20, positions=x, pbc=False)
            atoms.calc = ASEPotential(potential, method, fd_step=args.fd_step_angstrom)
            rng = np.random.default_rng(20261004)
            MaxwellBoltzmannDistribution(atoms, temperature_K=300, rng=rng)
            Stationary(atoms)
            ZeroRotation(atoms)
            dynamics = VelocityVerlet(atoms, args.dt_fs*units.fs)
            frames = []
            for step in range(args.steps+1):
                energy = atoms.get_potential_energy()
                force = atoms.get_forces()
                frame = atoms.copy()
                frame.info.update(step=step, time_fs=step*args.dt_fs, energy_ev=energy,
                                  scientific_status="not_validated", model_status="initialized_untrained")
                frame.arrays["model_forces"] = force.copy()
                frames.append(frame)
                if step < args.steps:
                    dynamics.run(1)
            write(output/"trajectory.extxyz", frames)
            summary.update(steps=args.steps, dt_fs=args.dt_fs, frames=len(frames),
                           initial_energy_ev=float(frames[0].info["energy_ev"]),
                           final_energy_ev=float(frames[-1].info["energy_ev"]),
                           all_frames_finite=all(np.isfinite(f.positions).all() for f in frames))
        summary.update(status="succeeded", quantum_evaluations=potential.evaluations,
                       execution_metadata=sampler.last_metadata)
    except Exception as exc:
        summary.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        summary["wall_seconds"] = time.monotonic()-start
        import resource
        summary["peak_rss_platform_units"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
        if hasattr(sampler, "close"):
            sampler.close()
    print(json.dumps({k: summary[k] for k in ("status", "mode", "backend", "wall_seconds", "training_updates")}), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend", choices=("cpu", "qpu"), default="cpu")
    p.add_argument("--mode", choices=("energy", "energy_force", "aimd"), default="energy")
    p.add_argument("--geometry", type=Path)
    p.add_argument("--sample-index", type=int, default=0)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--hardware-profile", type=Path, default=ROOT/"configs/hardware_profile.template.json")
    p.add_argument("--shots", type=int, default=3000)
    p.add_argument("--timeout", type=float, default=600)
    p.add_argument("--force-method", choices=("adjoint", "parameter_shift", "coordinate_fd"))
    p.add_argument("--fd-step-angstrom", type=float, default=DEFAULT_COORDINATE_FD_STEP,
                   help="Coordinate finite-difference displacement in Angstrom (default: 0.02); distinct from --dt-fs")
    p.add_argument("--steps", type=int, default=1)
    p.add_argument("--dt-fs", type=float, default=.1)
    a = p.parse_args()
    if a.steps < 0 or a.dt_fs <= 0 or not np.isfinite(a.dt_fs):
        p.error("steps must be nonnegative and dt finite positive")
    if a.fd_step_angstrom <= 0 or not np.isfinite(a.fd_step_angstrom):
        p.error("fd-step-angstrom must be finite and positive")
    run(a)
