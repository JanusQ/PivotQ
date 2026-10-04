"""Exercise the real HTTP boundary with an isolated local store, without jobs."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error

from backend import server
from backend.program import CIRCUIT_SOURCE, H2O_SOURCE
from backend.paths import data_path
from backend.models import Run, WorkflowPlan


class DashboardHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            'FUSION_EXECUTOR': 'local_cpu', 'FUSION_DEVICE_REGISTRATION': '',
            'FUSION_RUN_HISTORY_FILE': str(self.root / 'runs.json'),
            'FUSION_RAY_OUTPUT_ROOT': str(self.root / 'outputs'),
            'FUSION_PERF_OUTPUT_ROOT': str(self.root / 'performance'),
            'FUSION_DEVICE_STATE_FILE': str(self.root / 'devices.json'),
        })
        self.env.start()
        (self.root / 'frontend/dist/assets').mkdir(parents=True)
        (self.root / 'frontend/dist/index.html').write_text('<title>Dashboard test</title>')
        (self.root / 'frontend/dist/assets/main.js').write_text('const app = true;')
        (self.root / 'secrets').mkdir()
        (self.root / 'secrets/registration.token').write_text('test-secret')
        self.static = patch.object(server, 'DASHBOARD_ROOT', self.root)
        self.static.start()
        server.initialize()
        self.httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.httpd.server_port}'

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        server.close()
        self.static.stop()
        self.env.stop()
        self.temp.cleanup()

    def request(self, path, body=None, method=None):
        request_method = method or ('POST' if body is not None else 'GET')
        request = urllib.request.Request(self.base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json'}, method=request_method)
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            payload = response.read()
            return response.status, json.loads(payload) if 'application/json' in response.headers['Content-Type'] else payload

    def test_same_origin_static_and_real_local_capabilities(self):
        self.assertIn(b'Dashboard test', self.request('/')[1])
        self.assertEqual(self.request('/assets/main.js')[0], 200)
        status, data = self.request('/api/v1/system/status')
        self.assertEqual(status, 200)
        self.assertEqual(data['executor'], 'local_cpu')
        self.assertEqual(data['capabilities']['performance']['available'], data['qperfsim']['available'])
        _, targets = self.request('/api/v1/hardware-targets')
        self.assertEqual([(x['id'], x['kind']) for x in targets['items']], [('cpu-0', 'cpu'), ('gpu-0', 'gpu'), ('fake-sc-36', 'qpu')])
        _, tasks = self.request('/api/v1/task-types')
        for task in tasks['items']:
            for stage in task['stages']:
                if stage['id'] in ('circuit_execution', 'quantum_features'):
                    self.assertEqual(stage['default_device'], 'qpu')
                    self.assertEqual(stage['allowed_devices'], ['cpu', 'gpu', 'qpu'])

    def test_project_files_expose_real_task_sources(self):
        status, project = self.request('/api/v1/projects/project-h2o-demo')
        self.assertEqual(status, 200)
        files = {item['path']: item['content'] for item in project['files']}
        self.assertEqual(files['main.py'], H2O_SOURCE)
        for path in (
            'applications/h2o-hybrid-aimd/scripts/run_aimd.py',
            'applications/h2o-hybrid-aimd/single_h20_aimd/workflows/run_aimd.py',
            'applications/h2o-hybrid-aimd/single_h20_aimd/execution/quantum_worker.py',
        ):
            self.assertIn(path, files)
            self.assertTrue(files[path].strip())
        self.assertFalse(any(path.endswith(('.pt', '.csv', '.json')) for path in files))

        status, project = self.request('/api/v1/projects/project-circuit-demo')
        self.assertEqual(status, 200)
        files = {item['path']: item['content'] for item in project['files']}
        self.assertEqual(files['main.py'], CIRCUIT_SOURCE)
        self.assertIn('dashboard/backend/tasks/circuit.py', files)
        self.assertIn('dashboard/backend/circuit_runner.py', files)

    def test_paths_and_unknown_api_never_serve_sensitive_files(self):
        for path in ['/api/v1/absent', '/assets/missing.js', '/secrets/registration.token',
                     '/%2e%2e/secrets/registration.token', '/assets/%2e%2e/%2e%2e/secrets/registration.token']:
            status, body = self.request(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn('test-secret', str(body))
        (self.root / 'frontend/dist/assets/leak').symlink_to(self.root / 'secrets/registration.token')
        self.assertEqual(self.request('/assets/leak')[0], 404)

    def test_cpu_circuit_compile_keeps_source_and_device(self):
        status, data = self.request('/api/v1/projects/project-circuit-demo/compile', {
            'source': CIRCUIT_SOURCE, 'inputs': {'shots': 128, 'seed': 7},
            'hardware': {'circuit_execution': 'cpu-0'},
        })
        self.assertEqual(status, 200, data)
        self.assertEqual(data['program']['source'], CIRCUIT_SOURCE)
        self.assertEqual(data['plan']['stages'][0]['device'], 'cpu')
        self.assertEqual(data['plan']['normalized_inputs']['shots'], 128)
        status, data = self.request('/api/v1/projects/project-circuit-demo/compile', {
            'source': CIRCUIT_SOURCE, 'hardware': {'circuit_execution': 'gpu-0'},
        })
        self.assertEqual(status, 200, data)
        self.assertEqual(data['plan']['stages'][0]['device'], 'gpu')

    def test_cpu_prediction_refuses_gpu_calibration(self):
        from backend.program import H2O_SOURCE
        status, data = self.request('/api/v1/performance/run', {'source': H2O_SOURCE, 'task_id': 'h2o-hybrid-aimd',
                                                             'hardware': {'quantum_features': 'cpu-0'}})
        self.assertEqual(status, 422)
        self.assertEqual(data['error'], 'unsupported_configuration')

    def test_prediction_preview_works_when_ray_discovery_is_offline(self):
        request = {'source': H2O_SOURCE, 'task_id': 'h2o-hybrid-aimd',
                   'inputs': {'steps': 1},
                   'hardware': {'quantum_features': 'fake-sc-36', 'classical_predict': 'cpu-0'}}
        with patch.dict(os.environ, {'FUSION_EXECUTOR': 'ray'}), \
             patch.object(server, 'active_hardware', side_effect=AssertionError('live discovery forbidden')), \
             patch.object(server.QPerfSimClient, 'availability', side_effect=AssertionError('native probe forbidden')):
            status, result = self.request('/api/v1/performance/preview', request)
        self.assertEqual(status, 200, result)
        self.assertNotIn('result', result)
        self.assertEqual(result['plan']['stages'][2]['device'], 'cpu')
        self.assertIsNone(result['qperfsim']['available'])
        self.assertFalse(result['qperfsim']['checked'])
        self.assertTrue(Path(result['task_graph_path']).is_file())

    def test_fake_profile_is_server_owned_and_sealed(self):
        _, targets = self.request('/api/v1/hardware-targets')
        target = next(t for t in targets['items'] if t['id'] == 'fake-sc-36')
        snapshot = target['target_snapshot']
        request = {'source': CIRCUIT_SOURCE, 'target_snapshots': {'circuit_execution': {'parameters': {'qubits': 99}}},
                   'hardware_profile_digests': {'circuit_execution': snapshot['profile_sha256']}}
        status, result = self.request('/api/v1/projects/project-circuit-demo/compile', request)
        self.assertEqual(status, 200, result)
        saved = result['program']['target_snapshots']['circuit_execution']
        self.assertEqual(saved['parameters']['qubits'], 36)
        self.assertEqual(saved['logical_qubits'], 3)
        self.assertEqual(saved, result['plan']['stages'][0]['target_snapshot'])
        request['hardware_profile_digests']['circuit_execution'] = 'outdated'
        status, result = self.request('/api/v1/projects/project-circuit-demo/compile', request)
        self.assertEqual(status, 422)
        self.assertIn('参数已更新', str(result))

    def test_native_unavailable_does_not_disable_compile_or_preview(self):
        unavailable = {'available': False, 'reason': 'libfusion.so test unavailable', 'version': 'test'}
        request = {'task_id': 'quantum-circuit', 'source': CIRCUIT_SOURCE}
        with patch.object(server.QPerfSimClient, 'availability', return_value=unavailable):
            status, result = self.request('/api/v1/performance/run', request)
            self.assertEqual(status, 503)
            self.assertEqual(result['error'], 'qperfsim_unavailable')
            status, result = self.request('/api/v1/performance/preview', request)
            self.assertEqual(status, 200, result)
            self.assertNotIn('latency_seconds', result.get('result') or {})
            _, result = self.request('/api/v1/system/status')
            self.assertTrue(result['capabilities']['tasks']['quantum-circuit']['run']['available'])
            self.assertFalse(result['capabilities']['tasks']['quantum-circuit']['performance']['available'])

    def test_invalid_json_and_bad_source_are_errors(self):
        request = urllib.request.Request(self.base + '/api/v1/projects', data=b'not json', headers={'Content-Type': 'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()
        status, _ = self.request('/api/v1/projects/project-circuit-demo/compile', {'source': 'import os; os.system("false")'})
        self.assertEqual(status, 422)

    def test_malformed_nested_data_and_cross_origin_submissions(self):
        self.assertEqual(self.request('/api/v1/runs', {'task_id': 'h2o-hybrid-aimd'})[0], 422)
        self.assertEqual(self.request('/api/v1/projects/project-circuit-demo/compile', {'source': CIRCUIT_SOURCE, 'inputs': [1]})[0], 422)
        for headers, expected in [({'Content-Type': 'text/plain'}, 415),
                                  ({'Content-Type': 'application/json', 'Origin': 'https://unrelated.example'}, 403)]:
            req = urllib.request.Request(self.base + '/api/v1/projects', data=b'{}', headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req)
            self.assertEqual(caught.exception.code, expected)
            caught.exception.close()

    def test_prediction_survives_store_reload(self):
        saved = server.PREDICTIONS.save({'plan': {'task_id': 'h2o-hybrid-aimd'}, 'valid': True})
        status, data = self.request('/api/v1/performance/runs/' + saved['id'])
        self.assertEqual(status, 200)
        self.assertEqual(data['id'], saved['id'])

    def test_terminal_run_can_be_deleted_but_active_run_cannot(self):
        plan = WorkflowPlan('quantum-circuit', '1.0', {}, ())
        completed = Run('run-delete', 'quantum-circuit', 'SUCCEEDED', {}, plan)
        active = Run('run-active', 'quantum-circuit', 'RUNNING', {}, plan)
        server.RUNS[completed.id] = completed
        server.RUNS[active.id] = active
        server.write_history(server.HISTORY_FILE, server.RUNS)

        status, result = self.request('/api/v1/runs/run-delete', method='DELETE')
        self.assertEqual(status, 200, result)
        self.assertEqual(result['deleted'], 'run-delete')
        self.assertNotIn('run-delete', server.RUNS)

        status, result = self.request('/api/v1/runs/run-active', method='DELETE')
        self.assertEqual(status, 409)
        self.assertEqual(result['error'], 'run_active')
        self.assertEqual(self.request('/api/v1/runs/missing', method='DELETE')[0], 404)
        _, listed = self.request('/api/v1/runs')
        self.assertNotIn('run-delete', [item['id'] for item in listed['items']])

    def test_legacy_ray_result_is_enriched_from_original_output_directory(self):
        # Old histories have mode in result only and no stored output_root.
        run = Run('run-legacy', 'h2o-hybrid-aimd', 'SUCCEEDED', {},
                  WorkflowPlan('h2o-hybrid-aimd', '1.0', {'steps': 2}, ()),
                  result={'execution_mode': 'ray'})
        server.RUNS[run.id] = run
        legacy = self.root / 'fusion-platform/ray-outputs'
        folder = legacy / run.id
        (folder / 'aimd').mkdir(parents=True)
        (folder / f'{run.id}.aimd-result.json').write_text(json.dumps({
            'status': 'succeeded', 'metrics': {'aimd_elapsed_seconds': 1.5},
            'outputs': {'scientific_status': 'passed', 'execution': {'quantum_target': 'gpu'}},
        }))
        (folder / 'aimd/metrics.json').write_text(json.dumps({
            'quantum_execution': {'actual_device': 'gpu'},
        }))
        with patch('backend.results._DASHBOARD', self.root / 'dashboard'):
            status, data = self.request(f'/api/v1/runs/{run.id}/result')
        self.assertEqual(status, 200)
        self.assertEqual(data['result']['scientific_status'], 'passed')
        self.assertEqual(data['result']['quantum_execution']['actual_device'], 'gpu')
        self.assertEqual(data['result']['summary']['aimd_elapsed_seconds'], 1.5)


class LegacyPathTests(unittest.TestCase):
    def test_existing_data_is_used_without_moving_or_rotating(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            legacy, current = root / 'old', root / 'dashboard'
            (legacy / 'secrets').mkdir(parents=True)
            token = legacy / 'secrets/registration.token'
            token.write_text('preserved')
            with patch('backend.paths.LEGACY_ROOT', legacy), patch('backend.paths.DASHBOARD_ROOT', current):
                self.assertEqual(data_path('secrets/registration.token'), token)
                self.assertEqual(data_path('runtime-state/runs.json'), current / 'runtime-state/runs.json')
            self.assertEqual(token.read_text(), 'preserved')


if __name__ == '__main__':
    unittest.main()
