"""Submit exactly one Ray Job for the complete application invocation."""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import time

from .config import CONFIG_ENV

REGISTRATION = 'water10_v4.integration.fusion_framework.registration:register_components'
RUNNER = 'water10_v4.integration.fusion_framework.runner:run_aimd'


def job_arguments(*, submission_id, working_dir, config_path, output_dir):
    if not isinstance(submission_id, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', submission_id) is None:
        raise ValueError('submission_id must be 1-100 safe identifier characters')
    working = Path(working_dir).expanduser().resolve()
    if not (working/'water10_v4').is_dir():
        raise ValueError('working_dir must contain water10_v4 (use a small deployment directory)')
    for value in (config_path, output_dir):
        if not PurePosixPath(value).is_absolute():
            raise ValueError('config_path/output_dir must be absolute paths on the Ray cluster')
    parts = ['python', '-B', '-m', 'pivotq.jobs.driver', '--run-id', submission_id,
        '--registration', REGISTRATION, '--runner', RUNNER, '--namespace', f'water10-{submission_id}',
        '--output-dir', output_dir, '--trace-max-records', '10000']
    return dict(submission_id=submission_id, entrypoint=shlex.join(parts), working_dir=str(working),
        env_vars={CONFIG_ENV: config_path, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': '.',
                  'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'})


def build_job_spec(**kwargs):
    from pivotq._internal.jobs import RayJobSpec, RayJobRuntimeEnvironment, RayJobDriverResources
    values = job_arguments(**kwargs)
    return RayJobSpec(submission_id=values['submission_id'], entrypoint=values['entrypoint'],
        runtime_environment=RayJobRuntimeEnvironment(working_dir=values['working_dir'], env_vars=values['env_vars']),
        driver_resources=RayJobDriverResources(num_cpus=1),
        metadata={'application': 'multi-h2o-aimd-v4', 'interface_version': '1'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('submission-id', 'working-dir', 'config-path', 'output-dir'):
        parser.add_argument('--'+key, required=True)
    parser.add_argument('--address')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--wait', action='store_true')
    parser.add_argument('--wait-timeout', type=float, default=7200)
    args = parser.parse_args()
    kwargs = {k: getattr(args, k) for k in ('submission_id', 'working_dir', 'config_path', 'output_dir')}
    if args.dry_run:
        print(json.dumps(job_arguments(**kwargs), indent=2))
        return 0
    if not args.address:
        parser.error('--address is required unless --dry-run')
    if not 0 < args.wait_timeout < float('inf'):
        parser.error('--wait-timeout must be finite and positive')
    from pivotq._internal.jobs import RayJobClient
    client = RayJobClient(args.address)
    handle = client.submit(build_job_spec(**kwargs))
    print(f'WATER10_SUBMISSION_ID={handle.submission_id}', flush=True)
    if not args.wait:
        return 0
    deadline = time.monotonic() + args.wait_timeout
    while True:
        status = client.status(handle.submission_id)
        if status.is_terminal:
            print(f'WATER10_STATUS={status.value}')
            if status.value != 'succeeded':
                print(client.logs(handle))
            return 0 if status.value == 'succeeded' else 1
        if time.monotonic() >= deadline:
            raise TimeoutError(f'Job may still be running; inspect or stop {handle.submission_id}')
        time.sleep(2)


if __name__ == '__main__':
    raise SystemExit(main())
