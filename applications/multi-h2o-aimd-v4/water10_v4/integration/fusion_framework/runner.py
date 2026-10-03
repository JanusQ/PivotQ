"""Cluster Driver coordinator; energy is the default, FD/MD explicitly opt in."""
import hashlib
import json
from pathlib import Path
import platform
import time
from importlib.metadata import version, PackageNotFoundError

import numpy as np

from .client import FusionPotential
from .config import load_config
from .model import ATOMIC_NUMBERS, geometries


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False,
        default=lambda v: v.tolist() if isinstance(v, np.ndarray) else v.item()) + '\n')
    tmp.replace(path)


def read_geometry(path):
    raw = Path(path).read_bytes()
    payload = json.loads(raw)
    if payload.get('position_unit', 'angstrom') != 'angstrom':
        raise ValueError('Geometry position_unit must be angstrom')
    if payload.get('atomic_numbers') != ATOMIC_NUMBERS or payload.get('pbc', False) is not False:
        raise ValueError('Expected ten OHH molecules, nonperiodic geometry JSON')
    return geometries(payload['molecular_geometries_A']), hashlib.sha256(raw).hexdigest()


def run_aimd(framework, context):
    """Public framework runner signature. No ray.init()/framework.close() here."""
    started = time.perf_counter()
    c = load_config()
    out = Path(context.output_dir) / 'water10'
    out.mkdir(parents=True, exist_ok=False)
    summary = dict(status='running', scientific_status='not_validated', mode=c['mode'],
        run_id=context.run_id, model_sha256=c['model_sha256'], quantum_target=c['quantum_target'],
        classical_device=c['classical_device'], num_qubits=30, feature_order='X0..X29,Z0..Z29',
        force_method='cartesian_central_difference_unvalidated' if c['mode'] != 'energy' else None,
        python=platform.python_version(), versions={})
    for package in ('numpy', 'qiskit', 'qiskit-aer', 'ray', 'ray-quantum', 'torch', 'ase'):
        try:
            summary['versions'][package] = version(package)
        except PackageNotFoundError:
            summary['versions'][package] = None
    potential = None
    write_json(out/'config_snapshot.json', c)
    try:
        context.raise_if_stop_requested()
        positions, digest = read_geometry(c['geometry_path'])
        summary['geometry_sha256'] = digest
        write_json(out/'input_geometry.json', dict(atomic_numbers=ATOMIC_NUMBERS,
            pbc=False, molecular_geometries_A=positions))
        with FusionPotential(framework, context, c) as potential:
            if c['mode'] == 'energy':
                write_json(out/'energies.json', dict(energy_ev=potential.energy(positions)))
            elif c['mode'] == 'energy_force':
                results = [potential.energy_force(r) for r in positions]
                write_json(out/'energy_force.json', dict(energy_ev=[r[0] for r in results],
                    forces_ev_per_A=np.asarray([r[1] for r in results])))
            else:
                if len(positions) != 1:
                    raise ValueError('AIMD requires exactly one initial geometry')
                _trajectory(potential, positions[0], c, context, out)
        summary['status'] = 'succeeded'
    except BaseException as error:
        summary.update(status='cancelled' if getattr(context, 'stop_requested', False) else 'failed',
            error=dict(type=type(error).__name__, message=str(error)))
        raise
    finally:
        if potential is not None:
            summary['calls'] = potential.calls
            summary['quantum_executions'] = potential.quantum_executions
            if potential.qpu is not None:
                summary['measurement_circuit_settings'] = 2*potential.calls['geometries']
                summary['shots_per_basis'] = c['shots']
        summary['elapsed_seconds'] = time.perf_counter() - started
        if framework is not None:
            summary['runtime_execution'] = framework.execution_report()
        write_json(out/'run_summary.json', summary)
        if getattr(context, 'trace_collector', None) is not None:
            from ray_quantum.observability import export_trace_jsonl
            export_trace_jsonl(context.trace_collector, out/'framework_trace.jsonl')
        manifest = {p.name: dict(size=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                    for p in sorted(out.iterdir()) if p.is_file() and p.name != 'artifacts.json'}
        write_json(out/'artifacts.json', manifest)


def _trajectory(potential, positions, config, context, out):
    from ase import Atoms, units
    from ase.calculators.calculator import Calculator, all_changes
    from ase.io.trajectory import Trajectory
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution, Stationary
    from ase.md.verlet import VelocityVerlet

    class CalculatorAdapter(Calculator):
        implemented_properties = ['energy', 'forces']

        def calculate(self, atoms=None, properties=('energy', 'forces'), system_changes=all_changes):
            super().calculate(atoms, properties, system_changes)
            context.raise_if_stop_requested()
            energy, force = potential.energy_force(self.atoms.positions)
            self.results = dict(energy=energy, forces=force)

    atoms = Atoms(numbers=ATOMIC_NUMBERS, positions=positions, pbc=False)
    atoms.calc = CalculatorAdapter()
    MaxwellBoltzmannDistribution(atoms, temperature_K=config['temperature_K'], rng=np.random.default_rng(config['seed']))
    if config['temperature_K'] > 0:
        Stationary(atoms)
    dynamics = VelocityVerlet(atoms, timestep=config['timestep_fs']*units.fs)
    with Trajectory(str(out/'trajectory.traj'), 'w', atoms) as trajectory, (out/'md_log.jsonl').open('w') as log:
        def record():
            context.raise_if_stop_requested()
            row = dict(step=dynamics.nsteps, time_fs=dynamics.nsteps*config['timestep_fs'],
                potential_ev=atoms.get_potential_energy(), kinetic_ev=atoms.get_kinetic_energy(),
                temperature_K=atoms.get_temperature(), max_force_ev_per_A=float(np.max(np.abs(atoms.get_forces()))))
            if not all(np.isfinite(v) for v in row.values()):
                raise FloatingPointError('Nonfinite MD state')
            trajectory.write(atoms)
            log.write(json.dumps(row)+'\n')
            log.flush()
        dynamics.attach(record, interval=1)
        dynamics.run(config['steps'])
