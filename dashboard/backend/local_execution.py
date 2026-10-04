"""FIFO local execution with one owned Python/Ray process tree per task."""
from __future__ import annotations

from collections import deque
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from .models import Run
from .ray_execution import read_aimd_progress

TERMINAL = {'SUCCEEDED', 'FAILED', 'CANCELLED'}
LOGGER = logging.getLogger(__name__)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _log_tail(path):
    with path.open('rb') as log:
        log.seek(max(0, path.stat().st_size - 128 * 1024))
        return log.read().decode('utf-8', errors='replace').splitlines()[-500:]


def _remember_children(process, known):
    import psutil
    try:
        for child in process.children(recursive=True):
            known[child.pid] = child
    except psutil.Error:
        pass


def _live_processes(processes):
    import psutil
    result = []
    for process in processes:
        try:
            if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                result.append(process)
        except psutil.Error:
            pass
    return result


def _cleanup_children(processes, timeout=2.0):
    """psutil Process identities guard against PID reuse; never signal a group."""
    import psutil
    live = _live_processes(processes)
    for process in live:
        try:
            process.terminate()
        except psutil.Error:
            pass
    _, remaining = psutil.wait_procs(live, timeout=timeout)
    remaining = _live_processes(remaining)
    for process in remaining:
        try:
            process.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(remaining, timeout=timeout)
    return not _live_processes(remaining)


def recover_interrupted_worker(run, timeout=3.0):
    """Reconcile only a saved local worker whose PID, birth and job all match."""
    if run.execution_mode != 'local_cpu' or not run.worker_pid or not run.worker_created_at:
        return 'not_running'
    import psutil
    try:
        process = psutil.Process(run.worker_pid)
        if abs(process.create_time() - run.worker_created_at) > 0.001:
            return 'identity_mismatch'
        command = process.cmdline()
        job = str(Path(run.output_root) / run.id / 'job.json')
        if command[-4:] != ['-m', 'backend.local_worker', '--job', job]:
            return 'identity_mismatch'
        children = {}
        _remember_children(process, children)
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except psutil.TimeoutExpired:
            _remember_children(process, children)
            process.kill()
            process.wait(timeout=timeout)
        return 'cleaned' if _cleanup_children(list(children.values())) else 'cleanup_failed'
    except psutil.NoSuchProcess:
        return 'not_running'
    except (psutil.Error, TypeError):
        return 'cleanup_failed'


class LocalCPUExecutor:
    """The server enqueues sealed programs; the worker never evaluates source."""

    def __init__(self, output_root, *, config_path=None, checkpoint_path=None,
                 num_cpus=4, poll_interval=0.25, cancel_timeout=8.0):
        root = Path(__file__).resolve().parents[2]
        application = root / 'applications/h2o-hybrid-aimd'
        self.output_root = str(Path(output_root).expanduser().resolve())
        self.config_path = Path(config_path or os.environ.get('FUSION_RAY_CONFIG_PATH') or application / 'configs/h2o_aimd.yaml').expanduser().resolve()
        self.checkpoint_path = Path(checkpoint_path or os.environ.get('FUSION_RAY_CHECKPOINT_PATH') or application / 'checkpoints/hybrid_model.pt').expanduser().resolve()
        self.num_cpus = max(2, int(num_cpus))
        self.poll_interval = poll_interval
        self.cancel_timeout = cancel_timeout
        self._condition = threading.Condition(threading.RLock())
        self._queue = deque()
        self._entries = {}
        self._cancelled = set()
        self._closed = False
        self._thread = threading.Thread(target=self._consume, name='dashboard-local-queue', daemon=True)
        self._thread.start()

    def _notify(self, run, callback):
        try:
            callback(run)
        except Exception:
            LOGGER.exception('Cannot persist task %s update', run.id)

    def _prepare(self, run):
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', run.id) is None:
            raise ValueError('无效的任务 ID')
        if any(stage.device not in {'cpu', 'gpu', 'qpu'} for stage in run.plan.stages):
            raise ValueError('Simulation 模式仅支持 CPU、参考 GPU 和虚拟 QPU 目标')
        missing = [name for name in ('ray', 'torch', 'psutil', 'pivotq') if importlib.util.find_spec(name) is None]
        if run.task_id == 'h2o-hybrid-aimd':
            missing += [name for name in ('single_h20_aimd', 'ase', 'qiskit') if importlib.util.find_spec(name) is None]
        if missing:
            raise RuntimeError('缺少运行依赖: ' + ', '.join(missing) + '；请在项目根目录执行 uv sync --locked')
        program = run.request.get('program')
        if not isinstance(program, dict) or not program.get('execution_sha256'):
            raise ValueError('缺少已校验的程序快照，请重新编译')
        output = Path(self.output_root) / run.id
        output.mkdir(parents=True, exist_ok=False)
        job = {'run_id': run.id, 'task_id': run.task_id, 'program': program,
               'inputs': run.plan.normalized_inputs, 'num_cpus': self.num_cpus,
               'hardware': {s.id: s.device for s in run.plan.stages},
               'hardware_targets': {s.id: s.target_id for s in run.plan.stages},
               'target_snapshots': {s.id: s.target_snapshot for s in run.plan.stages if s.target_snapshot is not None},
               'output_dir': str(output)}
        if run.task_id == 'h2o-hybrid-aimd':
            name = run.plan.normalized_inputs['checkpoint_id']
            if not isinstance(name, str) or not name or Path(name).name != name or '\\' in name or name in {'.', '..'}:
                raise ValueError('checkpoint_id 必须是模型文件名')
            checkpoint = self.checkpoint_path.parent / name
            data = checkpoint.read_bytes()
            if hashlib.sha256(data).hexdigest() != program.get('checkpoint_sha256'):
                raise ValueError('模型已发生变化，请重新编译')
            snapshot = output / 'checkpoint.pt'
            snapshot.write_bytes(data)
            # Application load_config resolves scientific data paths against
            # its package root, so a queued task can freeze configuration too.
            frozen_config = output / 'config.yaml'
            frozen_config.write_bytes(self.config_path.read_bytes())
            job.update(config_path=str(frozen_config), checkpoint_path=str(snapshot))
        (output / 'job.json').write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
        from .local_worker import verify_job
        verify_job(job)
        return output

    def start(self, run: Run, on_update, **unused):
        with self._condition:
            if self._closed:
                raise RuntimeError('执行器已关闭')
            if run.id in self._entries:
                raise ValueError('任务已提交')
            self._prepare(run)
            run.output_root = self.output_root
            run.execution_mode = 'local_cpu'
            run.status = 'QUEUED'
            run.result = self._execution_metadata(run)
            run.events.append({'type': 'queued', 'phase': '等待 CPU 计算槽位'})
            self._entries[run.id] = (run, on_update)
            self._queue.append(run.id)
            self._notify(run, on_update)
            self._condition.notify_all()

    def cancel(self, run: Run):
        with self._condition:
            entry = self._entries.get(run.id)
            if entry is None or run.status in TERMINAL:
                return False
            self._cancelled.add(run.id)
            if run.id in self._queue:
                self._queue.remove(run.id)
                run.status = 'CANCELLED'
                run.events.append({'type': 'cancelled', 'phase': '排队任务已取消'})
            else:
                run.status = 'CANCELLING'
                run.events.append({'type': 'cancel_requested', 'phase': '正在停止任务'})
            self._notify(run, entry[1])
            self._condition.notify_all()
            return True

    def close(self):
        with self._condition:
            if not self._closed:
                self._closed = True
                for run, _ in list(self._entries.values()):
                    if run.status not in TERMINAL:
                        self.cancel(run)
                self._condition.notify_all()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=self.cancel_timeout + 15)

    def _consume(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._queue or self._closed)
                if not self._queue:
                    return
                run_id = self._queue.popleft()
                run, callback = self._entries[run_id]
                if run.status == 'CANCELLED':
                    continue
                run.status = 'RUNNING'
            try:
                self._execute(run, callback)
            except Exception as error:
                run.status = 'FAILED'
                run.result = (run.result or {}) | {'error': str(error)}
                run.events.append({'type': 'failed', 'message': str(error)})
                self._notify(run, callback)

    def _execute(self, run, callback):
        import psutil
        output = Path(self.output_root) / run.id
        env = dict(os.environ)
        root = Path(__file__).resolve().parents[2]
        paths = [root / 'dashboard', root / 'packages/framework', root / 'applications/h2o-hybrid-aimd']
        env['PYTHONPATH'] = os.pathsep.join([*(str(p) for p in paths), env.get('PYTHONPATH', '')])
        env['PYTHONUNBUFFERED'] = '1'
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        started = time.monotonic()
        children = {}
        stop_sent = None
        last_progress = None
        last_log_size = 0
        cleanup_ok = True
        with (output / 'worker.log').open('wb') as log:
            process = subprocess.Popen([sys.executable, '-m', 'backend.local_worker', '--job', str(output / 'job.json')],
                                       stdout=log, stderr=subprocess.STDOUT, cwd=str(root), env=env,
                                       start_new_session=True)
            identity = psutil.Process(process.pid)
            run.worker_pid = process.pid
            run.worker_created_at = identity.create_time()
            run.events.append({'type': 'worker_started', 'phase': 'CPU 计算初始化', 'pid': process.pid})
            self._notify(run, callback)
            try:
                while process.poll() is None:
                    _remember_children(identity, children)
                    if run.id in self._cancelled:
                        if stop_sent is None:
                            try:
                                process.terminate()
                            except ProcessLookupError:
                                pass
                            stop_sent = time.monotonic()
                        elif time.monotonic() - stop_sent >= self.cancel_timeout:
                            try:
                                process.kill()
                            except ProcessLookupError:
                                pass
                    elif run.task_id == 'h2o-hybrid-aimd':
                        progress = read_aimd_progress(run, self.output_root)
                        if progress != last_progress:
                            last_progress = progress
                            run.progress = progress['progress']
                            run.events.append({'type': 'progress', **progress})
                            self._notify(run, callback)
                    log_path = output / 'worker.log'
                    size = log_path.stat().st_size
                    if size != last_log_size:
                        last_log_size = size
                        run.result['logs'] = _log_tail(log_path)
                        self._notify(run, callback)
                    time.sleep(self.poll_interval)
                process.wait()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                cleanup_ok = _cleanup_children(list(children.values()))
        cancelled = run.id in self._cancelled
        terminal_status = ('CANCELLED' if cancelled else 'SUCCEEDED' if process.returncode == 0 else 'FAILED') if cleanup_ok else 'FAILED'
        # Publish terminal status only after its complete result is available.
        # Otherwise an HTTP poll can see SUCCEEDED and stop before metrics land.
        self._collect_result(run, time.monotonic() - started, process.returncode, cleanup_ok, terminal_status)
        run.progress = 100 if terminal_status == 'SUCCEEDED' else run.progress
        run.status = terminal_status
        run.events.append({'type': 'worker_finished', 'status': run.status, 'cleanup_succeeded': cleanup_ok})
        self._notify(run, callback)

    def _collect_result(self, run, elapsed, returncode, cleanup_ok, terminal_status):
        output = Path(self.output_root) / run.id
        log_path = output / 'worker.log'
        # Keep API/history bounded; the complete log remains downloadable.
        lines = _log_tail(log_path)
        result = {**self._execution_metadata(run),
                  'worker_seconds': elapsed, 'returncode': returncode, 'cleanup_succeeded': cleanup_ok,
                  'logs': lines, 'artifacts': []}
        error = _read_json(output / 'worker-error.json')
        if error:
            result['error'] = error['message']
        if not cleanup_ok:
            result['error'] = '计算已停止，但部分任务进程未能清理'
        manifest = _read_json(output / f'{run.id}.manifest.json')
        if manifest:
            result['driver_manifest'] = manifest
            if manifest.get('runtime_execution'):
                result['runtime_execution'] = manifest['runtime_execution']
        if run.task_id == 'quantum-circuit':
            actual = _read_json(output / f'{run.id}.circuit-result.json')
            if actual:
                result.update(actual)
                result['summary'] = {'设备': actual.get('device_name', 'CPU'),
                                     '计算时间 (s)': round(actual['seconds'], 6),
                                     '门数': run.request['program']['circuit']['gate_count'],
                                     '采样次数': sum(actual['counts'].values())}
                result['metrics'] = {'compute_seconds': actual['seconds'], 'worker_seconds': elapsed}
        else:
            actual = _read_json(output / f'{run.id}.aimd-result.json')
            outputs = actual.get('outputs', {})
            result['scientific_status'] = outputs.get('scientific_status', 'not_available')
            result['metrics'] = actual.get('metrics', {})
            if 'aimd_elapsed_seconds' in result['metrics']:
                result['compute_seconds'] = result['metrics']['aimd_elapsed_seconds']
                result['metrics']['compute_seconds'] = result['compute_seconds']
            result['summary'] = result['metrics'] | {'科学验收': result['scientific_status']}
            for name in ('execution', 'requested_execution', 'runtime_execution'):
                if name in outputs:
                    result[name] = outputs[name]
            if actual.get('error'):
                result['error'] = actual['error'].get('message', str(actual['error']))
            result['artifacts'] = [{'name': item['relative_path'], 'type': item.get('media_type', 'file'), 'available': True}
                                   for item in outputs.get('artifact_manifest', [])]
        if terminal_status == 'FAILED' and 'error' not in result:
            result['error'] = f"任务执行失败 ({manifest.get('failure_type') or returncode})；请查看日志"
        result['stage_results'] = [{'stage_id': s.id, 'title': s.title, 'device': 'cpu',
                                    'requested_device': s.device, 'actual_device': 'cpu',
                                    'actual_backend': 'cpu_numerical_simulation',
                                    'target_snapshot': s.target_snapshot,
                                    'status': 'succeeded' if terminal_status == 'SUCCEEDED' else 'not_available',
                                    'registered_target_id': s.target_id} for s in run.plan.stages]
        run.result = result

    @staticmethod
    def _execution_metadata(run):
        return {'execution_mode': 'local_cpu', 'device_name': 'CPU', 'actual_device': 'cpu',
                'actual_backend': 'cpu_numerical_simulation',
                'hardware': {s.id: s.device for s in run.plan.stages},
                'hardware_targets': {s.id: s.target_id for s in run.plan.stages},
                'target_snapshots': {s.id: s.target_snapshot for s in run.plan.stages if s.target_snapshot is not None}}
