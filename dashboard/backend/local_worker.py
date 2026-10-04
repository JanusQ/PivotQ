"""One isolated local Ray runtime, with production registrations and no source exec."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import tempfile
import traceback

from .program import digest


def verify_job(job):
    program = job['program']
    unsigned = dict(program)
    expected = unsigned.pop('execution_sha256')
    if digest(json.dumps(unsigned, sort_keys=True, ensure_ascii=True)) != expected:
        raise ValueError('程序快照校验失败')
    if digest(program['source']) != program['source_sha256']:
        raise ValueError('源代码快照校验失败')
    if program['task_id'] != job['task_id'] or program['inputs'] != job['inputs']:
        raise ValueError('程序与任务参数不一致')
    if program['hardware_targets'] != job['hardware_targets']:
        raise ValueError('程序与硬件分配不一致')
    if program.get('target_snapshots', {}) != job.get('target_snapshots', {}):
        raise ValueError('程序与目标参数快照不一致')
    for stage_id, snapshot in job.get('target_snapshots', {}).items():
        if snapshot['id'] != job['hardware_targets'].get(stage_id) or snapshot['kind'] != job.get('hardware', {}).get(stage_id):
            raise ValueError('目标参数快照与硬件分配不一致')
    if job['task_id'] == 'quantum-circuit':
        from .circuit_runner import verify
        verify(program)
    elif job['task_id'] == 'h2o-hybrid-aimd':
        from .program import source_request
        parsed = source_request({'task_id': job['task_id'], 'source': program['source']})
        if parsed['inputs'] != job['inputs']:
            raise ValueError('源代码与 AIMD 参数不一致')
        checkpoint = Path(job['checkpoint_path'])
        if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != program['checkpoint_sha256']:
            raise ValueError('模型快照校验失败')
    else:
        raise ValueError('不支持的任务类型')


def prepare_environment(job):
    # These limits affect the coordinator and all worker children. Never attach
    # to an inherited Ray cluster or make a real QPU provider visible locally.
    os.environ.update({
        'CUDA_VISIBLE_DEVICES': '', 'OMP_NUM_THREADS': '1',
        'MKL_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
        'MPLBACKEND': 'Agg', 'RAY_USAGE_STATS_ENABLED': '0',
        'PYTHONDONTWRITEBYTECODE': '1',
    })
    for name in list(os.environ):
        if name == 'RAY_ADDRESS' or name.startswith(('QPU_', 'CIRCUIT_', 'AIMD_')):
            os.environ.pop(name, None)
    hardware = job.get('hardware', {})
    if job['task_id'] == 'quantum-circuit':
        path = Path(job['output_dir']) / 'program.json'
        path.write_text(json.dumps(job['program'], ensure_ascii=False), encoding='utf-8')
        os.environ['CIRCUIT_PROGRAM_PATH'] = str(path)
        os.environ['CIRCUIT_LOGICAL_TARGET'] = hardware.get('circuit_execution', 'cpu')
        return 'backend.circuit_runner:register_cpu_components', 'backend.circuit_runner:run_circuit'
    inputs = job['inputs']
    overrides = {'aimd': {key: inputs[key] for key in ('steps', 'temperature_K', 'time_step_fs', 'seed')},
                 'project': {'seed': inputs['seed']}}
    quantum_target = hardware.get('quantum_features', 'cpu')
    # The scientific coordinator accepts gpu/qpu stage keys. The framework
    # bridge maps a logical CPU selection to the existing CPU component without
    # rewriting the application's validated, frozen GPU scheduling config.
    os.environ.update({
        'AIMD_CONFIG_PATH': job['config_path'],
        'AIMD_CHECKPOINT_PATH': job['checkpoint_path'],
        'AIMD_EXECUTION_MODE': 'heterogeneous',
        'AIMD_QUANTUM_TARGET': 'qpu' if quantum_target == 'qpu' else 'gpu',
        'AIMD_LOGICAL_HARDWARE_JSON': json.dumps(hardware),
        'AIMD_CONFIG_OVERRIDES_JSON': json.dumps(overrides),
    })
    return 'pivotq._internal.integrations.h2o:register_components', 'pivotq._internal.integrations.h2o:run'


def execute(job):
    verify_job(job)
    registration, runner = prepare_environment(job)
    import ray
    from pivotq._internal.jobs.driver import RayJobDriverConfig, run_driver

    if ray.is_initialized():
        raise RuntimeError('本地任务必须使用独立进程')
    config = RayJobDriverConfig(
        run_id=job['run_id'], namespace=job['run_id'], output_dir=job['output_dir'],
        registration_target=registration, runner_target=runner,
        trace_max_records=max(20000, job['inputs'].get('steps', 0) * 32 + 1000),
        simulation=True,
    )
    def request_stop(signum, frame):
        raise KeyboardInterrupt('任务取消')
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    ray_temp = tempfile.mkdtemp(prefix='qhai-dashboard-ray-')
    try:
        ray.init(address='local', namespace=job['run_id'], num_cpus=job['num_cpus'],
                 num_gpus=0, include_dashboard=False, log_to_driver=True,
                 _temp_dir=ray_temp, object_store_memory=256 * 1024 * 1024)
        manifest = run_driver(config)
        return manifest.exit_code or 0
    finally:
        ray.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True, type=Path)
    args = parser.parse_args()
    job = json.loads(args.job.read_text(encoding='utf-8'))
    try:
        return execute(job)
    except BaseException as error:
        report = {'type': type(error).__name__, 'message': str(error)}
        (Path(job['output_dir']) / 'worker-error.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        traceback.print_exc()
        return 130 if isinstance(error, KeyboardInterrupt) else 1


if __name__ == '__main__':
    raise SystemExit(main())
