"""Run the two ten-water models once through real Ray CPU Task/Actor execution.

Use --validate-only --smoke-output PATH to compare an existing experimental
result with the independent dense-force smoke run without repeating inference.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tempfile
import time
from uuid import uuid4


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APPLICATION_ROOT = REPOSITORY_ROOT / 'applications/multi-h2o-aimd-v4'
MODELS = {'frozen': 'models/final/best_model.json',
          'experimental': 'models/experimental/current_model.json'}
QUANTUM_ID = 'water10.quantum.cpu'
CLASSICAL_ID = 'water10.classical'
ENERGY_TOLERANCE_EV = 1e-6


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_manifest():
    files = {Path(__file__).resolve(), REPOSITORY_ROOT / 'pyproject.toml',
             REPOSITORY_ROOT / 'uv.lock', APPLICATION_ROOT / 'pyproject.toml',
             APPLICATION_ROOT / 'configs/fusion_cpu.json'}
    for directory in (REPOSITORY_ROOT / 'packages/framework/ray_quantum',
                      APPLICATION_ROOT / 'water10_v4'):
        files.update(directory.rglob('*.py'))
    return {str(path.relative_to(REPOSITORY_ROOT)): sha256(path)
            for path in sorted(files) if path.is_file()}


def package_versions():
    values = {}
    for package in ('ray', 'ray-quantum', 'numpy', 'qiskit', 'qiskit-aer', 'torch', 'ase', 'psutil'):
        try:
            values[package] = version(package)
        except PackageNotFoundError:
            values[package] = None
    return values


def compare_smoke(summary, energy, smoke_output):
    """Compare existing results only, including model and input provenance."""
    path = Path(smoke_output).resolve() / 'summary.json'
    smoke = read_json(path)
    validation = read_json(path.parent / 'validation.json')
    artifacts = read_json(path.parent / 'artifacts.json')
    required = {'summary.json', 'validation.json', 'frame_000000.npz', 'trajectory.traj'}
    reference = float(smoke['initial_energy_ev'])
    difference = abs(energy - reference)
    checks = {
        'smoke_completed': smoke['status'] == 'succeeded',
        'smoke_validation_passed': validation['status'] == 'passed',
        'smoke_artifacts_intact': required.issubset(artifacts) and all(
            (path.parent / name).stat().st_size == entry['size_bytes']
            and sha256(path.parent / name) == entry['sha256']
            for name, entry in artifacts.items()),
        'same_model': smoke['model_sha256'] == summary['model_sha256'],
        'same_geometry': smoke['geometry_sha256'] == summary['geometry_sha256'],
        'finite_energies': math.isfinite(energy) and math.isfinite(reference),
        'energy_agrees': math.isfinite(difference) and difference <= ENERGY_TOLERANCE_EV,
    }
    return dict(passed=all(checks.values()), checks=checks,
                reference_summary=str(path), reference_summary_sha256=sha256(path),
                ray_energy_ev=energy, smoke_initial_energy_ev=reference,
                absolute_difference_ev=difference, tolerance_ev=ENERGY_TOLERANCE_EV)


def validate_model(output, entry, smoke_output=None):
    directory = output / entry['label']
    app = directory / 'water10'
    summary = read_json(app / 'run_summary.json')
    driver = read_json(directory / f"{entry['run_id']}.manifest.json")
    config = read_json(app / 'config_snapshot.json')
    energy = read_json(app / 'energies.json')['energy_ev']
    records = [json.loads(line) for line in (app / 'framework_trace.jsonl').read_text().splitlines()
               if line.strip()]
    quantum = [r for r in records if r['component_id'] == QUANTUM_ID]
    classical = [r for r in records if r['component_id'] == CLASSICAL_ID]
    actor_ids = {r['execution_ids']['actor_id'] for r in classical}
    artifacts = read_json(app / 'artifacts.json')
    executions = summary.get('quantum_executions', [])
    selections = summary.get('runtime_execution', {})
    checks = {
        'driver_succeeded': driver['status'] == 'succeeded' and driver['exit_code'] == 0,
        'resources_cleaned': driver['cleanup']['succeeded']
            and driver['cleanup']['framework_closed'] and driver['cleanup']['registry_closed'],
        'application_succeeded': summary['status'] == 'succeeded',
        'same_run_id': summary['run_id'] == driver['run_id'] == entry['run_id']
            and all(r['trace_context'].get('run_id') == entry['run_id'] for r in records),
        'scientific_scope_preserved': summary['scientific_status'] == 'not_validated',
        'single_finite_energy': len(energy) == 1 and all(math.isfinite(e) for e in energy),
        'inputs_unchanged': summary['model_sha256'] == entry['model_sha256']
            and summary['geometry_sha256'] == entry['geometry_sha256']
            and sha256(config['model_path']) == entry['model_sha256']
            and sha256(config['geometry_path']) == entry['geometry_sha256'],
        'one_full_statevector': len(executions) == 1 and all(
            e['method'] == 'statevector' and e['num_qubits'] == 30
            and e['device'] == 'CPU' and e['precision'] == 'double'
            and e['enable_truncation'] is False and e['elapsed_seconds'] >= 0
            and e['peak_rss_bytes'] > 0 for e in executions),
        'single_quantum_task': len(quantum) == 1 and all(
            r['execution_mode'] == 'task' and r['method'] == 'execute_with_metadata'
            for r in quantum),
        'same_classical_actor': len(classical) == 3 and len(actor_ids) == 1
            and None not in actor_ids
            and [r['method'] for r in classical] == ['create', 'predict', 'terminate']
            and all(r['execution_mode'] == 'actor' for r in classical),
        'real_ray_execution': len(records) == 4 and all(
            r['status'] == 'succeeded' and r['backend'] == 'ray'
            and r['execution_ids']['task_id'] and r['execution_ids']['node_id']
            for r in records),
        'cpu_resources_only': bool(records) and all(
            r['resources']['num_gpus'] == 0 and not r['resources']['custom_resources']
            and r['component_id'] in (QUANTUM_ID, CLASSICAL_ID) for r in records),
        'framework_simulation_disabled': selections.get('simulation_enabled') is False
            # With simulation disabled the facade does not resolve substitutes,
            # so ordinary native execution correctly has an empty selection list.
            and isinstance(selections.get('selections'), list)
            and all(s['simulated'] is False for s in selections['selections']),
        'one_geometry_queried': summary['calls'] == dict(
            energy_queries=1, geometries=1, quantum_batches=1, classical_batches=1),
        'artifact_hashes_match': {'run_summary.json', 'config_snapshot.json', 'input_geometry.json',
            'energies.json', 'framework_trace.jsonl'}.issubset(artifacts) and all(
            (app / name).stat().st_size == value['size']
            and sha256(app / name) == value['sha256'] for name, value in artifacts.items()),
    }
    result = dict(passed=all(checks.values()), checks=checks, energy_ev=energy,
                  quantum_executions=executions, classical_actor_ids=sorted(actor_ids, key=str))
    if entry['label'] == 'experimental' and smoke_output is not None:
        result['smoke_comparison'] = compare_smoke(summary, float(energy[0]), smoke_output)
        result['passed'] = result['passed'] and result['smoke_comparison']['passed']
    return result


def validate_outputs(output, smoke_output=None):
    manifest = read_json(output / 'run_manifest.json')
    models = {}
    for entry in manifest['models']:
        try:
            models[entry['label']] = validate_model(output, entry, smoke_output)
        except Exception as error:
            models[entry['label']] = dict(passed=False,
                error=dict(type=type(error).__name__, message=str(error)))
    needs_comparison = any(e['label'] == 'experimental' for e in manifest['models'])
    checks = {
        'run_completed': manifest['status'] == 'succeeded',
        'local_ray_shutdown': manifest.get('local_ray_shutdown') is True,
        'all_models_passed': bool(models) and all(value['passed'] for value in models.values()),
        'sources_unchanged_during_run': manifest.get('source_manifest_unchanged') is True,
    }
    passed = all(checks.values())
    comparison_complete = not needs_comparison or smoke_output is not None
    result = dict(passed=passed, acceptance_complete=passed and comparison_complete,
                  scientific_status='not_validated', checks=checks, models=models,
                  comparison_status='complete' if comparison_complete else 'pending_smoke_output',
                  validator=dict(path=str(Path(__file__).resolve().relative_to(REPOSITORY_ROOT)),
                                 sha256=sha256(__file__),
                                 verified_at_utc=datetime.now(timezone.utc).isoformat()),
                  run_manifest_sha256=sha256(output / 'run_manifest.json'))
    write_json(output / 'validation.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=(*MODELS, 'both'), default='both')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--geometry', type=Path, default=APPLICATION_ROOT / 'configs/fusion_geometry.json')
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--smoke-output', type=Path)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args(argv)
    if args.threads < 1:
        parser.error('--threads must be positive')
    if args.validate_only:
        if args.output_dir is None:
            parser.error('--validate-only requires --output-dir')
        validation = validate_outputs(args.output_dir.resolve(), args.smoke_output)
        print(json.dumps(validation, indent=2), flush=True)
        return 0 if validation['passed'] else 1
    run_id = f"water10-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}"
    output = (args.output_dir or APPLICATION_ROOT / 'outputs/integration' / run_id).resolve()
    if output.exists() and any(output.iterdir()):
        parser.error(f'output directory must be empty: {output}')
    output.mkdir(parents=True, exist_ok=True)
    environment = {'PYTHONDONTWRITEBYTECODE': '1', 'CUDA_VISIBLE_DEVICES': '',
        'OMP_NUM_THREADS': str(args.threads), 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
        'RAY_USAGE_STATS_ENABLED': '0', 'MPLBACKEND': 'Agg'}
    os.environ.update(environment)
    os.environ.pop('RAY_ADDRESS', None)
    import ray
    from ray_quantum.jobs.driver import RayJobDriverConfig, run_driver
    from water10_v4.runtime import require_memory_budget
    from water10_v4.integration.fusion_framework.config import CONFIG_ENV, resolve_template
    from water10_v4.integration.fusion_framework.runner import read_geometry
    if ray.is_initialized():
        parser.error('run this launcher in a fresh Python process')
    labels = list(MODELS) if args.model == 'both' else [args.model]
    manifest = dict(schema_version=1, run_id=run_id, status='running', simulation=False,
        scientific_status='not_validated', python=platform.python_version(),
        command=[sys.executable, *(sys.argv if argv is None else [str(Path(__file__)), *argv])],
        versions=package_versions(), threads=args.threads, models=[],
        source_sha256=source_manifest(), started_at=datetime.now(timezone.utc).isoformat(),
        git_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'],
            cwd=REPOSITORY_ROOT, text=True).strip())
    started = time.perf_counter()
    try:
        positions, geometry_hash = read_geometry(args.geometry.resolve())
        if len(positions) != 1:
            raise ValueError('Ray energy verification requires exactly one geometry')
        for label in labels:
            directory = output / label
            directory.mkdir()
            config = resolve_template(APPLICATION_ROOT / 'configs/fusion_cpu.json', APPLICATION_ROOT)
            model_path = APPLICATION_ROOT / MODELS[label]
            config.update(model_path=str(model_path), model_sha256=sha256(model_path),
                geometry_path=str(args.geometry.resolve()), mode='energy', quantum_target='cpu',
                classical_device='cpu', batch_size=1, quantum_num_threads=args.threads,
                quantum_timeout_seconds=7200)
            config_path = directory / 'runtime_config.json'
            write_json(config_path, config)
            manifest['models'].append(dict(label=label, run_id=f'{run_id}-{label}',
                model_sha256=config['model_sha256'], geometry_sha256=geometry_hash,
                runtime_config=str(config_path)))
        manifest['memory_preflight'] = require_memory_budget(32)
        write_json(output / 'run_manifest.json', manifest)
        print(f'WATER10_RAY_OUTPUT={output}', flush=True)
        with tempfile.TemporaryDirectory(prefix='ray-water10-') as ray_temp:
            try:
                ray.init(address='local', namespace=run_id, num_cpus=args.threads + 1,
                         num_gpus=0, include_dashboard=False, log_to_driver=True,
                         runtime_env={'env_vars': environment}, _temp_dir=ray_temp,
                         object_store_memory=256 * 1024 * 1024)
                for entry in manifest['models']:
                    os.environ[CONFIG_ENV] = entry['runtime_config']
                    print(f"WATER10_RAY_MODEL={entry['label']}", flush=True)
                    driver = run_driver(RayJobDriverConfig(run_id=entry['run_id'],
                        registration_target='water10_v4.integration.fusion_framework.registration:register_components',
                        runner_target='water10_v4.integration.fusion_framework.runner:run_aimd',
                        namespace=run_id, output_dir=output / entry['label'],
                        simulation=False, trace_max_records=1000, actor_close_timeout_seconds=30))
                    entry['driver_exit_code'] = driver.exit_code
                    write_json(output / 'run_manifest.json', manifest)
                    if driver.exit_code != 0:
                        raise RuntimeError(f"{entry['label']} Ray driver failed: {driver.failure_type}")
            finally:
                ray.shutdown()
        manifest['status'] = 'succeeded'
    except BaseException as error:
        manifest['status'] = 'failed'
        manifest['error'] = dict(type=type(error).__name__, message=str(error))
    finally:
        if ray.is_initialized():
            ray.shutdown()
        manifest['local_ray_shutdown'] = not ray.is_initialized()
        manifest['elapsed_seconds'] = time.perf_counter() - started
        manifest['driver_peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        manifest['source_manifest_unchanged'] = source_manifest() == manifest['source_sha256']
        manifest['finished_at'] = datetime.now(timezone.utc).isoformat()
        write_json(output / 'run_manifest.json', manifest)
    validation = validate_outputs(output, args.smoke_output)
    print(json.dumps(validation, indent=2), flush=True)
    return 0 if validation['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
