from __future__ import annotations

import csv
import os
import json
from pathlib import Path
import sys
import threading
import time
import posixpath
import shlex
import hashlib
from dataclasses import replace
from typing import Any, Callable

from .models import Run, WorkflowPlan
from .hardware import HardwareRegistry


def _repository_paths() -> tuple[Path, Path, Path]:
    """Resolve framework and AIMD roots in the GitHub and legacy layouts."""
    repo_root = Path(__file__).resolve().parents[2]
    framework_root = repo_root / "packages" / "framework"
    if not framework_root.is_dir():
        framework_root = repo_root / "framework" / "src"
    aimd_root = repo_root / "applications" / "h2o-hybrid-aimd"
    if not aimd_root.is_dir():
        aimd_root = repo_root / "aimd"
    return repo_root, framework_root, aimd_root


class RayExecutionError(RuntimeError):
    pass


def read_aimd_progress(run: Run, output_root: str | Path) -> dict[str, Any]:
    """Read the flushed AIMD step log and convert it to run progress.

    ``md_log.csv`` is flushed after every ASE frame by the AIMD worker.  Reading
    its last completed ``step`` gives the backend an observable progress signal
    without inventing timing estimates or changing the browser contract.
    """

    total_steps = run.plan.normalized_inputs.get("steps", 0)
    if type(total_steps) is not int or total_steps <= 0:
        return {
            "progress": 5,
            "phase": "Ray 作业执行",
            "completed_steps": 0,
            "total_steps": None,
        }

    log_path = Path(output_root) / run.id / "aimd" / "md_log.csv"
    if not log_path.is_file():
        return {
            "progress": 5,
            "phase": "AIMD 初始化",
            "completed_steps": 0,
            "total_steps": total_steps,
        }

    completed_steps = 0
    try:
        with log_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    completed_steps = max(completed_steps, int(row["step"]))
                except (KeyError, TypeError, ValueError):
                    # A row can be observed while the worker is flushing it;
                    # retain the last complete row rather than failing polling.
                    continue
    except (OSError, UnicodeError):
        return {
            "progress": 5,
            "phase": "AIMD 初始化",
            "completed_steps": 0,
            "total_steps": total_steps,
        }

    completed_steps = min(total_steps, max(0, completed_steps))
    # Reserve the last 5% for scientific validation and artifact packaging.
    progress = min(95, round(95 * completed_steps / total_steps))
    return {
        "progress": progress,
        "phase": "AIMD 时间步迭代" if completed_steps < total_steps else "科学验收与输出打包",
        "completed_steps": completed_steps,
        "total_steps": total_steps,
    }


def enrich_result(run: Run, output_root):
    """Expose measured execution and scientific status separately on the result page."""
    circuit_path = Path(output_root) / run.id / f'{run.id}.circuit-result.json'
    if run.result and circuit_path.is_file():
        actual = json.loads(circuit_path.read_text(encoding='utf-8'))
        run.result.update(actual)
        device_name = actual.get('device_name') or actual.get('gpu_name') or '未记录'
        actual_device = actual.get('actual_device') or ('gpu' if actual.get('gpu_name') else None)
        compute_seconds = actual.get('compute_seconds', actual.get('seconds'))
        run.result.update(device_name=device_name, compute_seconds=compute_seconds)
        if actual_device:
            run.result['actual_device'] = actual_device
        run.result['summary'] = {'device_name': device_name,
                                 '门数': run.request['program']['circuit']['gate_count'],
                                 'compute_seconds': compute_seconds,
                                 '采样次数': sum(actual['counts'].values())}
        run.result['stage_results'] = [{'stage_id':s.id, 'title':s.title,
            'device':actual_device or s.device, 'status':'succeeded',
            'registered_target_id':s.target_id} for s in run.plan.stages]
        run.result['metrics'] = {'compute_seconds':compute_seconds,'worker_seconds':actual['worker_seconds']}
        if actual_device == 'gpu':
            run.result['metrics']['gpu_seconds'] = compute_seconds
        return
    path = Path(output_root) / run.id / f'{run.id}.aimd-result.json'
    if not run.result or not path.is_file():
        return
    actual = json.loads(path.read_text(encoding='utf-8'))
    outputs = actual.get('outputs', {})
    execution = outputs.get('execution', {})
    run.result['scientific_status'] = outputs.get('scientific_status', 'not_available')
    run.result['execution'] = execution
    run.result['summary'] = dict(actual.get('metrics', {})) | {'科学验收': outputs.get('scientific_status', '未完成')}
    # The execution target above is the requested stage target.  Merge the
    # worker-produced telemetry as well, so clients can distinguish a Ray
    # reservation from the device that actually ran the quantum worker.
    metrics_path = Path(output_root) / run.id / 'aimd' / 'metrics.json'
    if metrics_path.is_file():
        try:
            worker_metrics = json.loads(metrics_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            worker_metrics = {}
        if isinstance(worker_metrics, dict) and worker_metrics.get('quantum_execution'):
            run.result['quantum_execution'] = worker_metrics['quantum_execution']
    if actual.get('status') == 'succeeded':
        devices = {'quantum_features': execution.get('quantum_target'),
                   'classical_predict': execution.get('classical_actor_target')}
        run.result['stage_results'] = [{'stage_id': s.id, 'title': s.title, 'device': devices.get(s.id, 'cpu'),
            'status': 'succeeded', 'registered_target_id': s.target_id} for s in run.plan.stages]


class RayExecutionAdapter:
    """Submit H₂O as a real Ray Job through the existing framework contract.

    The Ray cluster, working directory, config and checkpoint are deployment
    settings. They are deliberately read from environment variables rather
    than accepted from the browser.
    """

    def __init__(self) -> None:
        self.address = os.environ.get("RAY_JOBS_ADDRESS", "http://127.0.0.1:8265")
        self.working_dir = self._required_path("FUSION_RAY_WORKING_DIR")
        self.config_path = self._required_remote_path("FUSION_RAY_CONFIG_PATH")
        self.checkpoint_path = self._required_remote_path("FUSION_RAY_CHECKPOINT_PATH")
        self.output_root = self._required_remote_path("FUSION_RAY_OUTPUT_ROOT")
        self.python_command = os.environ.get("FUSION_RAY_PYTHON", "python")
        self.hardware = HardwareRegistry.from_environment()
        self._clients: dict[str, Any] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _required_path(name: str) -> str:
        value = os.environ.get(name)
        if not value:
            raise RayExecutionError(f"{name} is required when FUSION_EXECUTOR=ray")
        path = Path(value).expanduser().resolve()
        if not path.is_dir():
            raise RayExecutionError(f"{name} must be an existing local directory: {path}")
        return str(path)

    @staticmethod
    def _required_remote_path(name: str) -> str:
        value = os.environ.get(name)
        if not value or not value.startswith("/"):
            raise RayExecutionError(f"{name} must be an absolute path visible to Ray workers")
        return value

    def _submit_job_spec(self, run: Run, hardware=None, qpu_configs=None):
        # The source package is intentionally imported only in real mode.
        repo_root, framework_root, aimd_root = _repository_paths()
        for path in (framework_root, aimd_root):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        try:
            from single_h20_aimd.integration.fusion_framework.submit_job import build_job_spec
            from pivotq._internal import jobs
        except ImportError as error:
            raise RayExecutionError(
                "real Ray mode requires the existing framework and AIMD packages on the backend"
            ) from error

        if run.task_id == 'quantum-circuit':
            return self._submit_circuit(run, hardware or self.hardware, jobs, repo_root)

        quantum = next(stage for stage in run.plan.stages if stage.id == "quantum_features")
        quantum_kind = "qpu" if quantum.device in {"qpu", "qpu_simulator"} else "gpu"
        if quantum.device == "qpu_simulator":
            raise RayExecutionError("qpu_simulator needs a simulator-specific runner; use gpu for the current H₂O Ray path")
        overrides = {
            "aimd": {
                "steps": run.plan.normalized_inputs.get("steps", 10),
                "temperature_K": run.plan.normalized_inputs.get("temperature_K", 300.0),
                "time_step_fs": run.plan.normalized_inputs.get("time_step_fs", 0.1),
                "seed": run.plan.normalized_inputs.get("seed", 20260919),
            },
            "project": {"seed": run.plan.normalized_inputs.get("seed", 20260919)},
        }
        checkpoint_id = str(run.plan.normalized_inputs.get("checkpoint_id", "")).strip()
        if checkpoint_id:
            if checkpoint_id in {".", ".."} or "/" in checkpoint_id or "\\" in checkpoint_id:
                raise RayExecutionError("checkpoint_id 只能是部署目录中的文件名")
            checkpoint_root = posixpath.dirname(self.checkpoint_path.rstrip("/"))
            selected_checkpoint = f"{checkpoint_root}/{checkpoint_id}"
        else:
            selected_checkpoint = self.checkpoint_path
        if run.request.get('program'):
            program = run.request['program']
            if hashlib.sha256(Path(selected_checkpoint).read_bytes()).hexdigest() != program['checkpoint_sha256']:
                raise RayExecutionError('模型已发生变化，请重新编译')
            # Freeze the checkpoint too: replacing a deployment file cannot change a queued job.
            snapshot_dir = Path(self.output_root) / run.id
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            snapshot = snapshot_dir / 'checkpoint.pt'
            snapshot.write_bytes(Path(selected_checkpoint).read_bytes())
            selected_checkpoint = str(snapshot)
        hardware = hardware or self.hardware
        quantum_target_spec = hardware.get(quantum.target_id) if quantum.target_id else None
        classical_stage = next(stage for stage in run.plan.stages if stage.id == "classical_predict")
        classical_target = hardware.get(classical_stage.target_id) if classical_stage.target_id else None
        if quantum_target_spec is not None:
            overrides.setdefault("scheduling", {}).setdefault("quantum_targets", {}).setdefault(quantum_kind, {}).setdefault("resources", {})["custom"] = dict(quantum_target_spec.ray_resources.get("resources", {}))
        if classical_target is not None:
            overrides.setdefault("scheduling", {}).setdefault("classical_actor", {}).setdefault("resources", {})["custom"] = dict(classical_target.ray_resources.get("resources", {}))
            actor = overrides["scheduling"]["classical_actor"]
            actor["device"] = "cuda" if classical_stage.device == "gpu" else "cpu"
            actor["require_gpu"] = classical_stage.device == "gpu"
            actor["resources"]["gpu"] = 1.0 if classical_stage.device == "gpu" else 0.0
        if quantum.device == "gpu" and classical_stage.device == "gpu" and quantum.target_id == classical_stage.target_id:
            overrides["scheduling"]["quantum_targets"]["gpu"]["resources"]["gpu"] = 0.5
            overrides["scheduling"]["classical_actor"]["resources"]["gpu"] = 0.5
        extra_env: dict[str, str] = {}
        extra_env["PYTHONPATH"] = os.pathsep.join((str(framework_root), str(aimd_root)))
        if quantum_target_spec is not None and quantum.device == "qpu":
            if qpu_configs and quantum.target_id in qpu_configs:
                extra_env['QPU_DEVICE_ID'] = quantum.target_id
                extra_env['QPU_DEVICE_CONFIG_FILE'] = qpu_configs[quantum.target_id]
                extra_env['QPU_JOB_JOURNAL_DIR'] = f'{self.output_root.rstrip("/")}/{run.id}/qpu-journal'
            extra_env["QPU_COMPONENT_ID"] = f"qpu-circuits-{quantum_target_spec.id}"
            extra_env["QPU_CUSTOM_RESOURCES_JSON"] = json.dumps(
                quantum_target_spec.ray_resources.get("resources", {}), separators=(",", ":")
            )
        submission_id = run.id
        output_dir = f"{self.output_root.rstrip('/')}/{submission_id}"
        spec = build_job_spec(
            submission_id=submission_id,
            working_dir=self.working_dir,
            config_path=self.config_path,
            checkpoint_path=selected_checkpoint,
            output_dir=output_dir,
            quantum_target=quantum_kind,
            config_overrides=overrides,
            python_command=self.python_command,
            trace_event_max_records=10_000,
            extra_env_vars=extra_env,
        )
        # This deployment already requires the absolute source/config paths on each
        # worker. Avoid uploading the AIMD training outputs as an unused workdir.
        spec = replace(spec, runtime_environment=replace(spec.runtime_environment, working_dir=None))
        coordinator = next(s for s in run.plan.stages if s.id == 'initialization')
        if coordinator.target_id:
            spec = replace(spec, driver_resources=jobs.RayJobDriverResources(num_cpus=1.0,
                custom_resources=hardware.get(coordinator.target_id).ray_resources.get('resources', {})))
        client = jobs.RayJobClient(self.address)
        handle = client.submit(spec)
        with self._lock:
            self._clients[run.id] = client
        return client, handle

    def _submit_circuit(self, run, hardware, jobs, repo_root):
        _, framework_root, aimd_root = _repository_paths()
        stage = run.plan.stages[0]
        target = hardware.get(stage.target_id)
        resources = target.ray_resources.get('resources', {})
        output_dir = f'{self.output_root.rstrip("/")}/{run.id}'
        spec = jobs.RayJobSpec(submission_id=run.id,
            entrypoint=shlex.join([self.python_command,'-m','pivotq.jobs.driver','--run-id',run.id,
                '--registration','backend.circuit_runner:register_components','--runner','backend.circuit_runner:run_circuit',
                '--namespace',run.id,'--output-dir',output_dir]),
            runtime_environment=jobs.RayJobRuntimeEnvironment(env_vars={
                'PYTHONPATH':os.pathsep.join([str(repo_root/'dashboard'),str(framework_root),str(aimd_root)]),
                'CIRCUIT_PROGRAM_JSON':json.dumps(run.request['program'],ensure_ascii=True),
                'CIRCUIT_NODE_RESOURCES':json.dumps(resources)}),
            driver_resources=jobs.RayJobDriverResources(num_cpus=1,custom_resources=resources))
        client = jobs.RayJobClient(self.address)
        handle = client.submit(spec)
        with self._lock:
            self._clients[run.id] = client
        return client, handle

    def start(self, run: Run, on_update: Callable[[Run], None], *, hardware=None, qpu_configs=None) -> None:
        client, handle = self._submit_job_spec(run, hardware, qpu_configs)
        run.status = "SUBMITTED"
        run.events.append({"type": "ray_job_submitted", "submission_id": handle.submission_id})
        on_update(run)
        threading.Thread(target=self._poll, args=(run, client, handle, on_update), daemon=True).start()

    def _poll(self, run: Run, client: Any, handle: Any, on_update: Callable[[Run], None]) -> None:
        terminal = {"succeeded": "SUCCEEDED", "failed": "FAILED", "stopped": "CANCELLED"}
        last_progress_event: tuple[Any, ...] | None = None
        while True:
            status = client.status(handle)
            value = getattr(status, "value", str(status)).lower()
            run.status = terminal.get(value, "RUNNING")
            run.events.append({"type": "ray_job_status", "status": run.status})
            progress = read_aimd_progress(run, self.output_root)
            if run.status not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                run.progress = max(run.progress, int(progress["progress"]))
            progress_event = (
                progress["progress"],
                progress["phase"],
                progress["completed_steps"],
                progress["total_steps"],
            )
            if progress_event != last_progress_event:
                run.events.append({"type": "progress", **progress})
                last_progress_event = progress_event
            if run.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                run.progress = 100 if run.status == "SUCCEEDED" else run.progress
                run.result = {"execution_mode": "ray", "submission_id": handle.submission_id, "logs": client.logs(handle).splitlines()}
                result_path = Path(self.output_root) / run.id / f"{run.id}.aimd-result.json"
                if result_path.is_file():
                    actual = json.loads(result_path.read_text(encoding="utf-8"))
                    run.result["metrics"] = actual.get("metrics", {})
                    run.result["summary"] = actual.get("metrics", {})
                    run.result["artifacts"] = [{"name": item["relative_path"], "type": item.get("media_type", "file"), "available": True} for item in actual.get("outputs", {}).get("artifact_manifest", [])]
                enrich_result(run, self.output_root)
                on_update(run)
                return
            on_update(run)
            # AIMD writes one flushed row per frame.  A half-second default
            # keeps short runs observable while remaining lightweight; deployers
            # can override it with FUSION_RAY_POLL_SECONDS.
            time.sleep(float(os.environ.get("FUSION_RAY_POLL_SECONDS", "0.5")))

    def cancel(self, run: Run) -> bool:
        with self._lock:
            client = self._clients.get(run.id)
        if client is None:
            return False
        client.stop(run.id)
        run.status = "CANCELLED"
        run.events.append({"type": "ray_job_cancel_requested"})
        return True
