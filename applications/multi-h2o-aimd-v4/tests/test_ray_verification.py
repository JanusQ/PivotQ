"""Acceptance checks reject proxies and mismatched provenance without inference."""
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('water10_ray_verification',
    ROOT / 'tests/integration/run_cpu_water10.py')
verification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verification)


def write_smoke(directory, summary):
    verification.write_json(directory/'summary.json', summary)
    verification.write_json(directory/'validation.json', dict(status='passed'))
    (directory/'frame_000000.npz').write_bytes(b'fixture')
    (directory/'trajectory.traj').write_bytes(b'fixture')
    verification.write_json(directory/'artifacts.json', {
        path.name: dict(size_bytes=path.stat().st_size, sha256=verification.sha256(path))
        for path in directory.iterdir() if path.name != 'artifacts.json'})


def test_smoke_comparison_requires_completed_matching_inputs(tmp_path):
    summary = dict(model_sha256='model', geometry_sha256='geometry')
    smoke = dict(summary, status='succeeded', initial_energy_ev=-10.)
    write_smoke(tmp_path, smoke)
    assert verification.compare_smoke(summary, -10. + 5e-7, tmp_path)['passed']
    assert not verification.compare_smoke(summary, -10. + 2e-6, tmp_path)['passed']
    for key, value in [('model_sha256', 'other'), ('geometry_sha256', 'other'), ('status', 'failed')]:
        write_smoke(tmp_path, dict(smoke, **{key: value}))
        assert not verification.compare_smoke(summary, -10., tmp_path)['passed']
    write_smoke(tmp_path, smoke)
    (tmp_path/'frame_000000.npz').write_bytes(b'corrupted')
    assert not verification.compare_smoke(summary, -10., tmp_path)['passed']


@pytest.fixture
def completed_run(tmp_path):
    directory = tmp_path/'experimental'
    app = directory/'water10'
    app.mkdir(parents=True)
    model = tmp_path/'model.json'
    geometry = tmp_path/'geometry.json'
    verification.write_json(model, {})
    verification.write_json(geometry, {})
    entry = dict(label='experimental', run_id='fixture',
        model_sha256=verification.sha256(model), geometry_sha256=verification.sha256(geometry))
    summary = dict(status='succeeded', scientific_status='not_validated', run_id='fixture',
        model_sha256=entry['model_sha256'], geometry_sha256=entry['geometry_sha256'],
        calls=dict(energy_queries=1, geometries=1, quantum_batches=1, classical_batches=1),
        quantum_executions=[dict(method='statevector', num_qubits=30, device='CPU',
            precision='double', enable_truncation=False, elapsed_seconds=1., peak_rss_bytes=16*2**30)],
        runtime_execution=dict(simulation_enabled=False, selections=[]))
    records = []
    for component, method, mode, actor in [
        (verification.CLASSICAL_ID, 'create', 'actor', 'actor1'),
        (verification.QUANTUM_ID, 'execute_with_metadata', 'task', None),
        (verification.CLASSICAL_ID, 'predict', 'actor', 'actor1'),
        (verification.CLASSICAL_ID, 'terminate', 'actor', 'actor1'),
    ]:
        records.append(dict(component_id=component, method=method, execution_mode=mode,
            status='succeeded', backend='ray', resources=dict(num_cpus=1, num_gpus=0, custom_resources={}),
            trace_context=dict(run_id='fixture'),
            execution_ids=dict(task_id='task', actor_id=actor, node_id='node')))
    verification.write_json(directory/'fixture.manifest.json', dict(status='succeeded', exit_code=0, run_id='fixture',
        cleanup=dict(succeeded=True, framework_closed=True, registry_closed=True)))
    verification.write_json(app/'config_snapshot.json', dict(model_path=str(model), geometry_path=str(geometry)))
    verification.write_json(app/'energies.json', dict(energy_ev=[-10.]))
    verification.write_json(app/'input_geometry.json', {})

    def save():
        verification.write_json(app/'run_summary.json', summary)
        (app/'framework_trace.jsonl').write_text('\n'.join(verification.json.dumps(r) for r in records)+'\n')
        verification.write_json(app/'artifacts.json', {
            p.name: dict(size=p.stat().st_size, sha256=verification.sha256(p))
            for p in app.iterdir() if p.name != 'artifacts.json'})
    save()
    return tmp_path, entry, summary, records, save


@pytest.mark.parametrize('corruption', ['local_backend', 'different_actor', 'small_system', 'substitute',
                                      'input_changed', 'wrong_run_id', 'missing_manifest_entry'])
def test_ray_acceptance_rejects_wrong_execution(completed_run, corruption):
    output, entry, summary, records, save = completed_run
    assert verification.validate_model(output, entry)['passed']
    if corruption == 'local_backend':
        records[1]['backend'] = 'local'
    elif corruption == 'different_actor':
        records[2]['execution_ids']['actor_id'] = 'actor2'
    elif corruption == 'small_system':
        summary['quantum_executions'][0]['num_qubits'] = 3
    elif corruption == 'substitute':
        summary['runtime_execution']['selections'] = [
            dict(component_id=verification.QUANTUM_ID, simulated=True)]
    elif corruption == 'input_changed':
        (output/'geometry.json').write_text('{"changed":true}')
    elif corruption == 'wrong_run_id':
        records[1]['trace_context']['run_id'] = 'another-run'
    save()
    if corruption == 'missing_manifest_entry':
        path = output/'experimental/water10/artifacts.json'
        artifacts = verification.read_json(path)
        del artifacts['framework_trace.jsonl']
        verification.write_json(path, artifacts)
    assert not verification.validate_model(output, entry)['passed']


@pytest.mark.parametrize('selections', [[], [dict(simulated=False)]])
def test_native_ray_allows_empty_or_explicit_native_selections(completed_run, selections):
    output, entry, summary, records, save = completed_run
    summary['runtime_execution']['selections'] = selections
    save()
    result = verification.validate_model(output, entry)
    assert result['passed']
    assert result['checks']['framework_simulation_disabled']


def test_validate_only_does_not_call_inference(completed_run, monkeypatch):
    output, entry, summary, records, save = completed_run
    verification.write_json(output/'run_manifest.json', dict(models=[entry], status='succeeded',
        local_ray_shutdown=True, source_manifest_unchanged=True))
    smoke = output/'smoke'
    smoke.mkdir()
    write_smoke(smoke, dict(status='succeeded', initial_energy_ev=-10.,
        model_sha256=entry['model_sha256'], geometry_sha256=entry['geometry_sha256']))
    from pivotq._internal.jobs import driver
    monkeypatch.setattr(driver, 'run_driver', lambda *args, **kwargs: pytest.fail('must not execute Ray'))
    manifest_hash = verification.sha256(output/'run_manifest.json')
    assert verification.main(['--validate-only', '--output-dir', str(output), '--smoke-output', str(smoke)]) == 0
    result = verification.read_json(output/'validation.json')
    assert result['acceptance_complete']
    assert result['validator']['sha256'] == verification.sha256(verification.__file__)
    assert result['run_manifest_sha256'] == manifest_hash
    assert verification.sha256(output/'run_manifest.json') == manifest_hash
