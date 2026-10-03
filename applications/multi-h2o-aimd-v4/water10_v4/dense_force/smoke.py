"""A short, real 30-qubit MD run; no training or scientific-accuracy claim."""
import argparse
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
import os
from pathlib import Path
import platform
import resource
import sys
import time

import numpy as np
import torch
from ase import Atoms, units
from ase.calculators.calculator import Calculator, all_changes
from ase.io import write
from ase.io.trajectory import Trajectory
from ase.md.velocitydistribution import MaxwellBoltzmannDistribution, Stationary, ZeroRotation
from ase.md.verlet import VelocityVerlet

from .adjoint import build_library
from .model import EnergyForceModel
from ..runtime import require_memory_budget

ROOT = Path(__file__).resolve().parents[2]
ATOMIC_NUMBERS = [8, 1, 1] * 10


def _json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(2**20), b''):
            digest.update(block)
    return digest.hexdigest()


def _versions():
    result = {'python': platform.python_version(), 'platform': platform.platform()}
    for package in ('numpy', 'torch', 'qiskit', 'qiskit-aer', 'ase', 'psutil'):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = None
    return result


def _peak_rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == 'darwin' else value * 1024)


def _read_geometry(path):
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    if data.get('atomic_numbers') != ATOMIC_NUMBERS or data.get('pbc', False) is not False:
        raise ValueError('Expected nonperiodic ten-water geometry in OHH order')
    if data.get('position_unit', 'angstrom') != 'angstrom':
        raise ValueError('Geometry coordinates must use angstrom')
    positions = np.asarray(data['molecular_geometries_A'], dtype=np.float64)
    if positions.shape != (1, 30, 3) or not np.isfinite(positions).all():
        raise ValueError('Smoke requires exactly one finite (30,3) initial geometry')
    return positions[0], data, hashlib.sha256(raw).hexdigest()


class _Calculator(Calculator):
    implemented_properties = ['energy', 'forces']

    def __init__(self, model):
        super().__init__()
        self.model = model
        self.calls = []

    def calculate(self, atoms=None, properties=('energy', 'forces'), system_changes=all_changes):
        super().calculate(atoms, properties, system_changes)
        started = time.monotonic()
        energy, forces = self.model.energy_forces(torch.tensor(self.atoms.positions, dtype=torch.float64))
        value = float(energy.detach())
        force = forces.detach().cpu().numpy()
        if energy.shape != () or force.shape != (30, 3) \
                or not math.isfinite(value) or not np.isfinite(force).all():
            raise FloatingPointError('Energy/forces must be a finite scalar and (30,3) array')
        self.results = dict(energy=value, forces=force)
        self.calls.append(dict(seconds=time.monotonic()-started, energy_ev=value,
                               peak_rss_bytes=_peak_rss_bytes()))


def run_smoke(output_dir, model_path=None, geometry_path=None, threads=8,
              steps=1, timestep_fs=0.1, temperature_K=300.0, seed=916):
    """Run without using formal training state or the separate 50 fs workflow."""
    if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
        raise ValueError('threads must be a positive integer')
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        raise ValueError('steps must be a positive integer')
    if not math.isfinite(timestep_fs) or timestep_fs <= 0:
        raise ValueError('timestep_fs must be finite and positive')
    if not math.isfinite(temperature_K) or temperature_K <= 0:
        raise ValueError('temperature_K must be finite and positive for the motion smoke check')
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError('seed must be a nonnegative integer')
    model_path = Path(model_path or ROOT/'models/experimental/current_model.json').resolve()
    geometry_path = Path(geometry_path or ROOT/'configs/fusion_geometry.json').resolve()
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    calculator = None
    summary = dict(status='running', scientific_status='not_validated', mode='analytic_force_md_smoke',
                   model_path=str(model_path), geometry_path=str(geometry_path),
                   model_status='experimental_not_converged', num_atoms=30, num_qubits=30,
                   amplitudes=2**30, readout_dimension=60, precision='complex128',
                   method='dense_statevector_adjoint', truncation=False, workers=1, threads=threads,
                   force_method='negative_analytic_energy_gradient',
                   timestep_fs=timestep_fs, target_steps=steps, temperature_K=temperature_K,
                   seed=seed, frames=0, completed_steps=0, completed_time_fs=0.0,
                   command=[sys.executable, *sys.argv], versions=_versions(), source_sha256={})
    validation = dict(status='running', scientific_status='not_validated')
    previous_stop = os.environ.get('WATER10_STOP_FILE')
    try:
        _json(out/'summary.json', summary)
        summary['memory_preflight'] = require_memory_budget(96)
        positions, geometry, digest = _read_geometry(geometry_path)
        summary.update(model_sha256=_sha256(model_path), geometry_sha256=digest,
                       sample_ids=geometry.get('sample_ids', []))
        sources = sorted((ROOT/'water10_v4').rglob('*.py')) + sorted((ROOT/'water10_v4').rglob('*.cpp'))
        sources.append(ROOT/'scripts/run_smoke.py')
        summary['source_sha256'] = {str(path.relative_to(ROOT)): _sha256(path) for path in sources}
        _json(out/'input_geometry.json', geometry)
        _json(out/'summary.json', summary)
        os.environ['WATER10_STOP_FILE'] = str(out/'STOP')
        torch.set_num_threads(1)
        library = build_library(out/'lib')
        summary['compiled_library_sha256'] = _sha256(library)
        model = EnergyForceModel.from_json(model_path, library, threads,
                                           expected_sha256=summary['model_sha256'])
        atoms = Atoms(numbers=ATOMIC_NUMBERS, positions=positions, pbc=False)
        MaxwellBoltzmannDistribution(atoms, temperature_K=temperature_K,
                                     rng=np.random.default_rng(seed))
        Stationary(atoms)
        ZeroRotation(atoms)
        calculator = _Calculator(model)
        atoms.calc = calculator
        dynamics = VelocityVerlet(atoms, timestep=timestep_fs * units.fs)
        snapshots = []
        rows = []
        with Trajectory(str(out/'trajectory.traj'), 'w', atoms) as trajectory, \
                (out/'md_log.jsonl').open('w') as log:
            for step in range(steps+1):
                if (out/'STOP').exists():
                    raise InterruptedError('Smoke stop requested')
                if step:
                    dynamics.run(1)
                energy = atoms.get_potential_energy()
                force = atoms.get_forces()
                velocity = atoms.get_velocities()
                kinetic = atoms.get_kinetic_energy()
                if atoms.positions.shape != (30, 3) or velocity.shape != (30, 3) \
                        or not all(np.isfinite(value).all() for value in
                                   (atoms.positions, velocity, force, energy, kinetic)):
                    raise FloatingPointError('Nonfinite or malformed MD frame')
                row = dict(step=step, time_fs=step*timestep_fs, energy_ev=float(energy),
                           kinetic_ev=float(kinetic), total_ev=float(energy+kinetic),
                           temperature_K=float(atoms.get_temperature()),
                           max_force_ev_per_A=float(np.max(np.abs(force))),
                           elapsed_seconds=time.monotonic()-started)
                frame = out/f'frame_{step:06d}.npz'
                temporary = frame.with_suffix('.tmp')
                with temporary.open('wb') as stream:
                    np.savez(stream, **row, atomic_numbers=atoms.numbers, positions_A=atoms.positions,
                             velocities_A_per_ase_time=velocity, forces_ev_per_A=force)
                temporary.replace(frame)
                trajectory.write(atoms)
                snapshot = atoms.copy()
                snapshot.info.update(row)
                snapshot.set_array('forces_ev_per_A', force.copy())
                snapshots.append(snapshot)
                rows.append(row)
                log.write(json.dumps(row, allow_nan=False)+'\n')
                log.flush()
                summary.update(frames=step+1, completed_steps=step, completed_time_fs=step*timestep_fs,
                               initial_energy_ev=rows[0]['energy_ev'], final_energy_ev=row['energy_ev'],
                               calls=calculator.calls, elapsed_seconds=time.monotonic()-started,
                               peak_rss_bytes=_peak_rss_bytes())
                _json(out/'summary.json', summary)
                print(json.dumps(dict(event='frame_completed', **row)), flush=True)
        write(out/'trajectory.extxyz', snapshots)
        displacement = float(np.max(np.abs(atoms.positions-positions)))
        validation.update(frames_expected=steps+1, frames_actual=len(rows),
                          atom_and_force_shapes=[30, 3], all_values_finite=True,
                          coordinates_changed=displacement>0, max_displacement_A=displacement,
                          completed_steps=dynamics.nsteps, completed_time_fs=rows[-1]['time_fs'],
                          energy_force_evaluations=len(calculator.calls))
        if len(rows) != steps+1 or dynamics.nsteps != steps or displacement <= 0 \
                or len(calculator.calls) < steps+1:
            raise RuntimeError('MD frame count, step count, or coordinate-motion validation failed')
        validation['status'] = 'passed'
        summary['status'] = 'succeeded'
        return summary
    except BaseException as error:
        summary.update(status='cancelled' if isinstance(error, (KeyboardInterrupt, InterruptedError)) else 'failed',
                       error=dict(type=type(error).__name__, message=str(error)))
        validation['status'] = 'failed'
        raise
    finally:
        if previous_stop is None:
            os.environ.pop('WATER10_STOP_FILE', None)
        else:
            os.environ['WATER10_STOP_FILE'] = previous_stop
        summary.update(elapsed_seconds=time.monotonic()-started, peak_rss_bytes=_peak_rss_bytes())
        if calculator is not None:
            summary['calls'] = calculator.calls
        _json(out/'summary.json', summary)
        _json(out/'validation.json', validation)
        _json(out/'artifacts.json', {str(path.relative_to(out)): dict(size_bytes=path.stat().st_size,
               sha256=_sha256(path)) for path in sorted(out.rglob('*'))
               if path.is_file() and path.name != 'artifacts.json'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--model-path', type=Path)
    parser.add_argument('--geometry-path', type=Path)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--steps', type=int, default=1)
    parser.add_argument('--timestep-fs', type=float, default=0.1)
    parser.add_argument('--temperature-K', type=float, default=300.0)
    parser.add_argument('--seed', type=int, default=916)
    args = parser.parse_args()
    result = run_smoke(**vars(args))
    print(json.dumps(result, indent=2, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
