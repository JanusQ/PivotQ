"""Check the preserved Ray submission contract without submitting hardware work."""
import json
import os
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from backend.hardware import HardwareRegistry
from backend.models import Run, WorkflowPlan, StagePlan
from backend.ray_execution import RayExecutionAdapter, enrich_result


class RayMigrationTests(unittest.TestCase):
    def circuit_result(self, actual, device):
        plan = WorkflowPlan('quantum-circuit', '1.0', {'shots': 128, 'seed': 1}, (
            StagePlan('circuit_execution', '电路执行', device, (), {device: 1}, device + '-0'),))
        run = Run('run-circuit', 'quantum-circuit', 'SUCCEEDED',
                  {'program': {'circuit': {'gate_count': 4}}}, plan,
                  result={'execution_mode': 'ray'})
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / run.id
            directory.mkdir()
            (directory / (run.id + '.circuit-result.json')).write_text(json.dumps(actual))
            enrich_result(run, temp)
        return run.result

    def test_legacy_gpu_result_exposes_generic_metrics_and_preserves_gpu_alias(self):
        result = self.circuit_result({'gpu_name': 'Legacy GPU', 'seconds': 0.123456789,
                                      'worker_seconds': 0.9, 'counts': {'000': 64, '111': 64}}, 'gpu')
        self.assertEqual(result['summary']['device_name'], 'Legacy GPU')
        self.assertEqual(result['summary']['compute_seconds'], 0.123456789)
        self.assertEqual(result['summary']['采样次数'], 128)
        self.assertEqual(result['actual_device'], 'gpu')
        self.assertEqual(result['metrics'], {'compute_seconds': 0.123456789,
                                            'gpu_seconds': 0.123456789, 'worker_seconds': 0.9})
        self.assertEqual(result['stage_results'], [{'stage_id': 'circuit_execution', 'title': '电路执行',
                                                   'device': 'gpu', 'status': 'succeeded',
                                                   'registered_target_id': 'gpu-0'}])

    def test_generic_cpu_result_does_not_require_or_claim_gpu_telemetry(self):
        result = self.circuit_result({'device_name': 'CPU', 'actual_device': 'cpu',
                                      'compute_seconds': 0.2, 'worker_seconds': 0.8,
                                      'counts': {'000': 128}}, 'cpu')
        self.assertEqual(result['summary']['device_name'], 'CPU')
        self.assertEqual(result['compute_seconds'], 0.2)
        self.assertEqual(result['summary']['compute_seconds'], 0.2)
        self.assertEqual(result['metrics'], {'compute_seconds': 0.2, 'worker_seconds': 0.8})
        self.assertNotIn('GPU', result['summary'])
        self.assertEqual(result['stage_results'][0]['stage_id'], 'circuit_execution')
        self.assertEqual(result['stage_results'][0]['title'], '电路执行')
        self.assertEqual(result['stage_results'][0]['device'], 'cpu')

    def test_circuit_job_uses_dashboard_module_and_selected_gpu_resources(self):
        from pivotq._internal import jobs
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
            'FUSION_RAY_WORKING_DIR': temp,
            'FUSION_RAY_CONFIG_PATH': '/deployment/config.yaml',
            'FUSION_RAY_CHECKPOINT_PATH': '/deployment/model.pt',
            'FUSION_RAY_OUTPUT_ROOT': '/deployment/output',
            'RAY_JOBS_ADDRESS': 'http://example.invalid:8265',
        }):
            adapter = RayExecutionAdapter()
            plan = WorkflowPlan('quantum-circuit', '1.0', {'shots': 128, 'seed': 1}, (
                StagePlan('circuit_execution', '电路执行', 'gpu', (), {'gpu': 1}, 'gpu-0'),))
            run = Run('run-migration', 'quantum-circuit', 'QUEUED', {'program': {'source': 'snapshot'}}, plan)
            client = MagicMock()
            with patch.object(jobs, 'RayJobClient', return_value=client) as factory:
                adapter._submit_circuit(run, HardwareRegistry(), jobs, root)
            factory.assert_called_once_with('http://example.invalid:8265')
            spec = client.submit.call_args.args[0]
            command = shlex.split(spec.entrypoint)
            self.assertIn('backend.circuit_runner:run_circuit', command)
            self.assertIn('backend.circuit_runner:register_components', command)
            environment = dict(spec.runtime_environment.env_vars)
            self.assertIn(str(root / 'dashboard'), environment['PYTHONPATH'].split(os.pathsep))
            self.assertNotIn(str(root / 'fusion-platform'), environment['PYTHONPATH'].split(os.pathsep))
            self.assertEqual(dict(spec.driver_resources.custom_resources), {'qhai_gpu_0': 1})


if __name__ == '__main__':
    unittest.main()
