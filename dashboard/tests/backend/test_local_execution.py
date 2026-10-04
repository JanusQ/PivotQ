import json
from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from backend.local_execution import LocalCPUExecutor, TERMINAL, recover_interrupted_worker
from backend.local_worker import verify_job, prepare_environment
from backend.models import Run, StagePlan, WorkflowPlan
from backend.program import digest
from backend.circuit_parser import parse_quantum_circuit
from backend.hardware_profiles import target_snapshot


def circuit_run(identifier):
    source = 'from qhai.quantum import QuantumCircuit\ncircuit = QuantumCircuit(2)\ncircuit.h(0)\ncircuit.cx(0, 1)\ncircuit.measure([0, 1])\n'
    plan = WorkflowPlan('quantum-circuit', '1.0', {'shots': 100, 'seed': 7},
                        (StagePlan('circuit_execute', '电路执行', 'cpu', (), {'cpu': 1}, 'cpu-local'),))
    program = {'source': source, 'source_sha256': digest(source), 'circuit': parse_quantum_circuit(source),
               'task_id': plan.task_id, 'inputs': plan.normalized_inputs, 'hardware_targets': {'circuit_execute': 'cpu-local'}}
    program['execution_sha256'] = digest(json.dumps(program, sort_keys=True, ensure_ascii=True))
    return Run(identifier, plan.task_id, 'CREATED', {'program': program}, plan)


def wait_for(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError('Timed out waiting for task state')


class LocalExecutorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.executor = LocalCPUExecutor(self.root, poll_interval=0.02, cancel_timeout=0.15)
        self.actual_popen = subprocess.Popen
        self.starts = []
        self.patcher = patch('backend.local_execution.subprocess.Popen', side_effect=self.spawn_stub)
        self.patcher.start()

    def tearDown(self):
        self.executor.close()
        self.patcher.stop()
        self.directory.cleanup()

    def spawn_stub(self, args, **kwargs):
        directory = Path(args[-1]).parent
        self.starts.append(directory.name)
        # A real subprocess that only finishes when the test writes a release
        # marker. This exercises scheduling and signal handling without Ray.
        script = ('from pathlib import Path; import time; '
                  'p=Path(__import__("sys").argv[1]); '
                  'exec("while not (p / \'release\').exists(): time.sleep(0.02)")')
        return self.actual_popen([sys.executable, '-c', script, str(directory)], **kwargs)

    def test_fifo_single_slot_and_queued_cancel(self):
        first, second, third = (circuit_run(name) for name in ('first', 'second', 'third'))
        for run in (first, second, third):
            self.executor.start(run, lambda r: None)
        wait_for(lambda: self.starts == ['first'])
        self.assertEqual(second.status, 'QUEUED')
        self.assertTrue(self.executor.cancel(second))
        self.assertEqual(second.status, 'CANCELLED')
        (self.root / first.id / 'release').touch()
        wait_for(lambda: self.starts == ['first', 'third'])
        (self.root / third.id / 'release').touch()
        wait_for(lambda: third.status in TERMINAL)
        self.assertEqual(first.status, 'SUCCEEDED')
        self.assertEqual(third.status, 'SUCCEEDED')
        self.assertEqual(first.result['actual_device'], 'cpu')

    def test_running_cancel_waits_for_process_exit_and_close_is_idempotent(self):
        run = circuit_run('cancel')
        self.executor.start(run, lambda r: None)
        wait_for(lambda: run.worker_pid is not None)
        self.assertTrue(self.executor.cancel(run))
        self.assertEqual(run.status, 'CANCELLING')
        wait_for(lambda: run.status == 'CANCELLED')
        self.assertTrue(run.result['cleanup_succeeded'])
        import psutil
        self.assertFalse(psutil.pid_exists(run.worker_pid))
        self.executor.close()
        self.executor.close()

    def test_close_cancels_active_and_queued(self):
        active, queued = circuit_run('active'), circuit_run('queued')
        self.executor.start(active, lambda r: None)
        self.executor.start(queued, lambda r: None)
        wait_for(lambda: active.worker_pid is not None)
        self.executor.close()
        self.assertEqual((active.status, queued.status), ('CANCELLED', 'CANCELLED'))
        with self.assertRaisesRegex(RuntimeError, '关闭'):
            self.executor.start(circuit_run('late'), lambda r: None)

    def test_forced_cancel_cleans_only_owned_descendants(self):
        child_script = 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'
        worker_script = (
            'import signal,subprocess,sys,time; from pathlib import Path; '
            'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
            f'child=subprocess.Popen([sys.executable,"-c",{child_script!r}]); '
            'Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)'
        )
        def spawn(args, **kwargs):
            pidfile = Path(args[-1]).parent / 'child.pid'
            return self.actual_popen([sys.executable, '-c', worker_script, str(pidfile)], **kwargs)
        self.patcher.stop()
        self.patcher = patch('backend.local_execution.subprocess.Popen', side_effect=spawn)
        self.patcher.start()
        run = circuit_run('descendants')
        self.executor.start(run, lambda r: None)
        pidfile = self.root / run.id / 'child.pid'
        wait_for(pidfile.exists)
        child_pid = int(pidfile.read_text())
        time.sleep(0.1)  # Let the monitor observe the owned descendant identity.
        self.executor.cancel(run)
        wait_for(lambda: run.status in TERMINAL, seconds=10)
        self.assertEqual(run.status, 'CANCELLED')
        self.assertTrue(run.result['cleanup_succeeded'])
        import psutil
        self.assertTrue(not psutil.pid_exists(child_pid) or psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE)
        self.assertTrue(psutil.Process(os.getpid()).is_running())

    def test_missing_dependency_fails_without_demo_fallback(self):
        with patch('backend.local_execution.importlib.util.find_spec', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'uv sync'):
                self.executor.start(circuit_run('deps'), lambda r: None)
        self.assertFalse((self.root / 'deps').exists())

    def test_snapshot_input_tampering_rejected_before_launch(self):
        run = circuit_run('tampered')
        run.request['program']['source'] += '\ncircuit.x(0)'
        with self.assertRaisesRegex(ValueError, '快照'):
            self.executor.start(run, lambda r: None)
        self.assertEqual(self.starts, [])

    def test_recovery_does_not_kill_unrelated_pid(self):
        run = circuit_run('recover')
        import psutil
        run.execution_mode = 'local_cpu'
        run.output_root = str(self.root)
        run.worker_pid = os.getpid()
        run.worker_created_at = psutil.Process().create_time()
        self.assertEqual(recover_interrupted_worker(run), 'identity_mismatch')

    def test_worker_removes_inherited_cluster_and_qpu_bindings(self):
        run = circuit_run('environment')
        output = self.root / run.id
        output.mkdir()
        job = {'task_id': run.task_id, 'program': run.request['program'], 'output_dir': str(output)}
        with patch.dict(os.environ, {'RAY_ADDRESS': 'remote', 'QPU_DEVICE_URL': 'provider', 'CIRCUIT_PROGRAM_JSON': 'old'}):
            registration, _ = prepare_environment(job)
            self.assertNotIn('RAY_ADDRESS', os.environ)
            self.assertNotIn('QPU_DEVICE_URL', os.environ)
            self.assertEqual(os.environ['CUDA_VISIBLE_DEVICES'], '')
            self.assertTrue(registration.endswith(':register_cpu_components'))

    def test_virtual_target_snapshot_is_retained_and_tampering_rejected(self):
        run = circuit_run('virtual')
        stage = replace(run.plan.stages[0], device='qpu', target_id='fake-sc-36',
                        target_snapshot=target_snapshot('fake-sc-36', 2))
        run.plan = replace(run.plan, stages=(stage,))
        program = run.request['program']
        program['hardware_targets'] = {stage.id: stage.target_id}
        program['target_snapshots'] = {stage.id: stage.target_snapshot}
        program.pop('execution_sha256')
        program['execution_sha256'] = digest(json.dumps(program, sort_keys=True, ensure_ascii=True))
        output = self.executor._prepare(run)
        job = json.loads((output / 'job.json').read_text())
        self.assertEqual(job['hardware'][stage.id], 'qpu')
        self.assertEqual(job['program']['circuit']['qubits'], 2)
        self.assertEqual(job['target_snapshots'][stage.id]['parameters']['qubits'], 36)
        verify_job(job)
        changed = deepcopy(job)
        changed['target_snapshots'][stage.id]['parameters']['shot_rate'] = 1
        with self.assertRaisesRegex(ValueError, '目标参数快照'):
            verify_job(changed)
        changed = deepcopy(job)
        changed['hardware'][stage.id] = 'gpu'
        with self.assertRaisesRegex(ValueError, '硬件分配'):
            verify_job(changed)


class LogicalExecutionTests(unittest.TestCase):
    def framework(self):
        from pivotq._internal.executors import LocalExecutor
        from pivotq._internal.framework import ComponentRegistry, FusionFramework
        registry = ComponentRegistry()
        framework = FusionFramework(LocalExecutor(registry), simulation=True)
        self.addCleanup(registry.close)
        self.addCleanup(framework.close)
        return framework

    def test_circuit_qpu_and_gpu_targets_execute_same_two_qubit_cpu_state(self):
        from backend.circuit_runner import register_cpu_components
        import torch
        context = SimpleNamespace(get_node_id=lambda: 'local-test', get_accelerator_ids=lambda: {})
        results = []
        for target in ('cpu', 'gpu', 'qpu'):
            with self.subTest(target=target):
                framework = self.framework()
                with patch.dict(os.environ, {'CIRCUIT_LOGICAL_TARGET': target}):
                    register_cpu_components(framework)
                program = circuit_run('unit').request['program']
                with patch('ray.get_runtime_context', return_value=context), patch('torch.zeros', wraps=torch.zeros) as zeros:
                    result = framework.invoke('editor-circuit', 'execute', program, invocation_id='bell-' + target)
                self.assertTrue(result.succeeded, result.error)
                self.assertEqual(zeros.call_args.args[0], 4)
                self.assertEqual(result.value['actual_device'], 'cpu')
                self.assertEqual(set(result.value['probabilities']), {'00', '11'})
                self.assertAlmostEqual(result.value['probabilities']['00'], 0.5)
                selection = framework.resolve_execution('editor-circuit')
                self.assertEqual(selection.requested_devices, (target.upper(),))
                self.assertEqual(selection.actual_devices, ('CPU',))
                self.assertEqual(selection.effective_resources.num_gpus, 0)
                self.assertEqual(selection.effective_resources.custom_resources_dict(), {})
                results.append((result.value['probabilities'], result.value['counts']))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])

    def test_h2o_registration_matches_logical_cpu_and_reference_targets(self):
        from pivotq._internal.integrations.h2o.bridge import register_components
        root = Path(__file__).resolve().parents[3]
        application = root / 'applications/h2o-hybrid-aimd'
        job = {'task_id': 'h2o-hybrid-aimd',
               'inputs': {'steps': 2, 'temperature_K': 300, 'time_step_fs': 0.1, 'seed': 7},
               'config_path': str(application / 'configs/h2o_aimd.yaml'),
               'checkpoint_path': str(application / 'checkpoints/hybrid_model.pt')}
        for quantum, classical in (('cpu', 'cpu'), ('gpu', 'gpu'), ('qpu', 'cpu'), ('qpu', 'gpu')):
            with self.subTest(quantum=quantum, classical=classical), patch.dict(os.environ, {
                    'QPU_DEVICE_URL': 'https://must-never-be-used.invalid',
                    'AIMD_LOGICAL_HARDWARE_JSON': '{"quantum_features":"wrong"}',
            }):
                job['hardware'] = {'quantum_features': quantum, 'classical_predict': classical}
                prepare_environment(job)
                self.assertNotIn('QPU_DEVICE_URL', os.environ)
                self.assertEqual(os.environ['AIMD_QUANTUM_TARGET'], 'qpu' if quantum == 'qpu' else 'gpu')
                framework = self.framework()
                register_components(framework)
                classical_selection = framework.resolve_execution('h2o-classical-predict')
                self.assertEqual(classical_selection.requested_devices, (classical.upper(),))
                self.assertEqual(classical_selection.actual_devices, ('CPU',))
                self.assertEqual(classical_selection.requested_resources.num_gpus, 1 if classical == 'gpu' else 0)
                component = {'cpu': 'h2o-f2-quantum-features-cpu',
                             'gpu': 'h2o-f2-quantum-features-gpu', 'qpu': 'qpu-circuits'}[quantum]
                quantum_selection = framework.resolve_execution(component)
                self.assertEqual(quantum_selection.requested_devices, (quantum.upper(),))
                self.assertEqual(quantum_selection.actual_devices, ('CPU',))

    def test_h2o_logical_cpu_client_routes_frozen_requests_to_cpu_components(self):
        from pivotq._internal.integrations.h2o.bridge import register_components, _simulation_client
        from single_h20_aimd.execution import ActorRequest, ActorCallRequest, TaskRequest, ResourceRequest
        application = Path(__file__).resolve().parents[3] / 'applications/h2o-hybrid-aimd'
        hardware = {'quantum_features': 'cpu', 'classical_predict': 'cpu'}
        framework = self.framework()
        with patch.dict(os.environ, {
                'AIMD_CONFIG_PATH': str(application / 'configs/h2o_aimd.yaml'),
                'AIMD_CONFIG_OVERRIDES_JSON': '{}', 'AIMD_QUANTUM_TARGET': 'gpu',
                'AIMD_LOGICAL_HARDWARE_JSON': json.dumps(hardware)}):
            register_components(framework)
        client = _simulation_client(framework, hardware)
        example = application / 'single_h20_aimd/integration/fusion_framework/example_quantum_request.json'
        request = TaskRequest.from_dict(json.loads(example.read_text()))
        request.payload['backend'] = 'adapt_water_statevector_gpu'
        request.payload['quantum_request']['execution_spec']['device'] = 'cuda'
        request = replace(request, resources=ResourceRequest(cpu=1, gpu=1))
        original = deepcopy(request.to_dict())
        quantum_result = client.result(client.submit(request))
        self.assertEqual(quantum_result.status, 'succeeded', quantum_result.error)
        self.assertEqual(request.to_dict(), original)
        self.assertIsNotNone(framework.execution_selection('h2o-f2-quantum-features-cpu'))
        self.assertIsNone(framework.execution_selection('h2o-f2-quantum-features-gpu'))
        actor_request = ActorRequest(
            run_id='cpu-client', actor_id='classical', actor_type='classical_predict',
            payload={'checkpoint_path': str(application / 'checkpoints/hybrid_model.pt'),
                     'device': 'cuda', 'require_gpu': True}, resources=ResourceRequest(cpu=0.25, gpu=1),
        )
        actor = client.create_actor(actor_request)
        try:
            prediction = client.call_actor(actor, ActorCallRequest(
                run_id='cpu-client', task_id='predict', method='predict',
                payload={'request_id': 'predict', 'sample_ids': ['one'], 'features': [[0.0] * 14]},
            ))
            self.assertEqual(prediction.status, 'succeeded', prediction.error)
            self.assertEqual(prediction.outputs['inference_metrics']['actor_device'], 'cpu')
            self.assertEqual(actor_request.payload['device'], 'cuda')
        finally:
            self.assertTrue(client.terminate_actor(actor))
        self.assertTrue(all(row['requested_devices'] == row['actual_devices'] == ['CPU']
                            for row in framework.execution_report()['selections']))


if __name__ == '__main__':
    unittest.main()
