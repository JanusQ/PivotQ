"""Public Jobs API preserves argv, identities and management semantics."""
import pickle
import shlex
from unittest.mock import patch
import pytest
from pivotq.jobs import JobClient, JobHandle, JobSpec, JobStatus, JobSubmissionError, JobStateError
from pivotq.errors import SubmissionDisposition
from pivotq._internal.jobs import RayJobClient
from tests.unit.jobs.test_client import _FakeJobsClient


def connected(fake):
    client = JobClient('http://127.0.0.1:8265')
    client._client = RayJobClient('http://127.0.0.1:8265', client_factory=lambda *a, **k: fake)
    return client


def test_job_spec_freezes_values_and_quotes_arguments():
    argv = ['python', '-c', 'print("a b; $(do-not-run)")']
    env = {'TOKEN': 'secret'}
    spec = JobSpec(argv, env_vars=env, num_cpus=1)
    argv.append('changed')
    env['TOKEN'] = 'changed'
    fake = _FakeJobsClient()
    handle = connected(fake).submit(spec)
    assert handle == JobHandle(spec.submission_id)
    assert shlex.split(fake.submit_arguments['entrypoint']) == list(spec.entrypoint)
    assert fake.submit_arguments['runtime_env'] == {'env_vars': {'TOKEN': 'secret'}}
    assert fake.submit_arguments['entrypoint_num_cpus'] == 1
    assert 'secret' not in repr(spec)
    assert 'num_gpus' not in JobSpec.__dataclass_fields__
    assert pickle.loads(pickle.dumps(spec)) == spec


def test_lazy_client_and_read_manage_methods():
    with patch('pivotq.jobs.client.RayJobClient', side_effect=AssertionError('connected')):
        JobClient('http://127.0.0.1:8265')
    fake = _FakeJobsClient()
    client = connected(fake)
    handle = JobHandle('test-job')
    assert client.status(handle) is JobStatus.RUNNING
    assert client.logs(handle) == 'driver output\n'
    with pytest.raises(JobStateError):
        client.delete(handle)
    assert client.stop(handle)
    fake.status_value = 'STOPPED'
    assert client.status(handle).is_terminal
    assert client.delete(handle)


def test_submission_failure_retains_reconcilable_id():
    fake = _FakeJobsClient()
    fake.submit_error = RuntimeError('server may have accepted, secret')
    client = connected(fake)
    spec = JobSpec(['python', 'app.py'])
    with pytest.raises(JobSubmissionError) as captured:
        client.submit(spec)
    error = captured.value
    assert error.framework_job_id == spec.submission_id
    assert error.disposition is SubmissionDisposition.UNKNOWN
    assert 'secret' not in str(error)
    assert pickle.loads(pickle.dumps(error)).framework_job_id == spec.submission_id
    with patch('pivotq.jobs.client.RayJobClient', side_effect=RuntimeError('offline')):
        with pytest.raises(JobSubmissionError) as captured:
            JobClient('http://127.0.0.1:8265').submit(spec)
    assert captured.value.disposition is SubmissionDisposition.NOT_SUBMITTED
    assert captured.value.framework_job_id == spec.submission_id


@pytest.mark.parametrize('argv', ['python app.py', [], [''], [1], ['python', 'bad\nline']])
def test_invalid_command(argv):
    with pytest.raises((TypeError, ValueError)):
        JobSpec(argv)
