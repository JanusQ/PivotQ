"""Opt-in real Jobs acceptance using an isolated local service, never a shared cluster."""
import os
from pathlib import Path
import socket
import sys
import time
import tempfile

import pytest

from pivotq.jobs import JobClient, JobSpec, JobStatus


@pytest.mark.skipif(os.environ.get('PIVOTQ_TEST_JOBS') != '1', reason='set PIVOTQ_TEST_JOBS=1')
def test_real_jobs_submit_logs_status_stop(tmp_path):
    import ray
    if ray.is_initialized():
        pytest.skip('requires a fresh process')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    context = ray.init(address='local', num_cpus=2, include_dashboard=True,
                       dashboard_host='127.0.0.1', dashboard_port=port,
                       _temp_dir=tempfile.mkdtemp(prefix='pq-jobs-'), object_store_memory=100 * 1024 * 1024,
                       log_to_driver=False)
    client = JobClient('http://127.0.0.1:' + str(port))
    submitted = []

    def wait(job, expected):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            status = client.status(job)
            if status in expected:
                return status
            if status.is_terminal:
                pytest.fail(f'{status}: {client.logs(job)}')
            time.sleep(.2)
        pytest.fail(f'job timed out: {client.logs(job)}')

    try:
        source = tmp_path / 'app'
        source.mkdir()
        (source / 'main.py').write_text('import pivotq as pq\n'
            'def add(a,b): return a+b\n'
            'with pq.Runtime(executor="ray",address="auto") as runtime:\n'
            '    print("pivotq-job-result",runtime.get(runtime.submit(add,20,22)),flush=True)\n')
        completed = client.submit(JobSpec([sys.executable, 'main.py'], working_dir=str(source)))
        submitted.append(completed)
        assert wait(completed, {JobStatus.SUCCEEDED}) is JobStatus.SUCCEEDED
        assert 'pivotq-job-result 42' in client.logs(completed)
        assert client.delete(completed)
        submitted.remove(completed)
        running = client.submit(JobSpec([sys.executable, '-c',
                            'import time; print("waiting",flush=True); time.sleep(120)']))
        submitted.append(running)
        wait(running, {JobStatus.RUNNING})
        assert client.stop(running)
        assert wait(running, {JobStatus.STOPPED}) is JobStatus.STOPPED
        assert client.delete(running)
        submitted.remove(running)
    finally:
        for job in submitted:
            try:
                if not client.status(job).is_terminal:
                    client.stop(job)
            except Exception:
                pass
        ray.shutdown()
