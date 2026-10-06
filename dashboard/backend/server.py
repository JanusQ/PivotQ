from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import uuid
import secrets
import mimetypes
import shutil
from copy import deepcopy
from dataclasses import replace
from .program import source_request, seal_program
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse, parse_qs, unquote

from .execution import DryRunExecutor
from .hardware import ComputeTarget, HardwareRegistry
from .models import Run
from .registry import get_task, task_types, validate_and_plan
from .ray_execution import RayExecutionAdapter, enrich_result
from .qperfsim import QPerfSimClient, QPerfSimUnavailable
from .project_store import PROJECTS, create_project, get_project
from .compiler import compile_project
from .examples import all_examples
from .resource_discovery import discover, DiscoveryResult
from .device_registry import DeviceRegistry, ray_nodes
from .run_history import read_history, write_history
from .paths import DASHBOARD_ROOT, configure_defaults, execution_mode
from .capabilities import readiness
from . import results
from .predictions import PredictionStore


HARDWARE = None
NETWORK_DEVICES = False
DEVICES = None
EXECUTOR = None
EXECUTOR_ERROR = None
HISTORY_FILE = None
REGISTRATION_TOKEN = ''
RUNS: dict[str, Run] = {}
COMPILES: dict[str, dict[str, Any]] = {}
LOCK = threading.RLock()
PREDICTIONS = None


def registration_token():
    path = Path(os.environ.get('FUSION_REGISTRATION_TOKEN_FILE', str(Path(__file__).resolve().parents[1] / 'secrets' / 'registration.token')))
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        try:
            with path.open('x') as output:
                output.write(secrets.token_urlsafe(48))
            path.chmod(0o600)
        except FileExistsError:
            pass
    return path.read_text().strip()


def initialize():
    global HARDWARE, NETWORK_DEVICES, DEVICES, EXECUTOR, EXECUTOR_ERROR, HISTORY_FILE, RUNS, REGISTRATION_TOKEN, PREDICTIONS
    configure_defaults()
    mode = execution_mode()
    os.environ['FUSION_EXECUTOR'] = mode
    HARDWARE = HardwareRegistry.from_environment()
    NETWORK_DEVICES = os.environ.get('FUSION_DEVICE_REGISTRATION', '') == 'network'
    if NETWORK_DEVICES and mode != 'ray':
        raise ValueError('网络设备登记需要 Ray 执行模式')
    DEVICES = DeviceRegistry(ray_nodes, state_path=Path(os.environ['FUSION_DEVICE_STATE_FILE']))
    REGISTRATION_TOKEN = registration_token() if NETWORK_DEVICES else ''
    HISTORY_FILE = Path(os.environ['FUSION_RUN_HISTORY_FILE'])
    RUNS = read_history(HISTORY_FILE)
    if RUNS:
        write_history(HISTORY_FILE, RUNS)
    PREDICTIONS = PredictionStore(Path(os.environ['FUSION_PERF_OUTPUT_ROOT']) / 'records')
    EXECUTOR_ERROR = None
    try:
        if mode == 'local_cpu':
            from .local_execution import LocalCPUExecutor
            EXECUTOR = LocalCPUExecutor(os.environ['FUSION_RAY_OUTPUT_ROOT'],
                config_path=os.environ['FUSION_RAY_CONFIG_PATH'], checkpoint_path=os.environ['FUSION_RAY_CHECKPOINT_PATH'])
        elif mode == 'ray':
            EXECUTOR = RayExecutionAdapter()
        elif mode == 'dry_run':
            EXECUTOR = DryRunExecutor()
        else:
            raise ValueError(f'未知执行模式：{mode}')
    except (ValueError, RuntimeError, ImportError, OSError) as error:
        EXECUTOR = None
        EXECUTOR_ERROR = str(error)


def close():
    shutdown = getattr(EXECUTOR, 'close', None)
    if callable(shutdown):
        shutdown()


def output_root(run):
    return getattr(run, 'output_root', None) or os.environ['FUSION_RAY_OUTPUT_ROOT']


def active_hardware() -> tuple[HardwareRegistry, Any]:
    try:
        result = DEVICES.discover() if NETWORK_DEVICES else discover(HARDWARE)
    except Exception:
        result = DiscoveryResult(HardwareRegistry(tuple()), True, 'Ray resource discovery unavailable')
    return result.registry, result


def prediction_hardware() -> HardwareRegistry:
    """Server-owned profiles, independent of leases, Ray discovery and health."""
    from .hardware_profiles import PROFILES, target_snapshot
    targets = {target.id: replace(target, available=True) for target in HARDWARE.all()}
    if NETWORK_DEVICES and DEVICES is not None:
        # Registration records are already validated; do not call snapshot(),
        # which consults live Ray nodes. Credentials never enter the model.
        with DEVICES.lock:
            for item in DEVICES.entries.values():
                targets[item['device_id']] = ComputeTarget(
                    item['device_id'], item['kind'], item['title'], True, {},
                    'registered-offline-profile')
    for target_id, profile in PROFILES.items():
        existing = targets.get(target_id)
        if existing is None:
            targets[target_id] = ComputeTarget(target_id, profile['kind'], profile['title'],
                                                True, {}, 'prediction-profile', target_snapshot(target_id))
        elif existing.target_snapshot is None and existing.kind == profile['kind']:
            targets[target_id] = replace(existing, target_snapshot=target_snapshot(target_id))
    return HardwareRegistry(tuple(targets.values()))


def _normalize_request(body: dict[str, Any], *, prediction: bool = False) -> dict[str, Any]:
    """Convert UI target IDs to task-level device kinds before validation."""
    for key in ('inputs', 'hardware', 'hardware_profile_digests'):
        if body.get(key) is not None and not isinstance(body[key], dict):
            raise ValueError(f'{key} 必须是对象')
    if body.get('task_id') is not None and not isinstance(body['task_id'], str):
        raise ValueError('task_id 必须是字符串')
    request = source_request(body)
    request['task_id'] = request.get('task_id') or 'h2o-hybrid-aimd'
    hardware = dict(request.get("hardware") or {})
    target_ids: dict[str, str] = {}
    snapshots: dict[str, dict] = {}
    expected_digests = request.get('hardware_profile_digests') or {}
    if prediction:
        hardware_registry = prediction_hardware()
    else:
        hardware_registry, discovery = active_hardware()
        if discovery.live and discovery.error:
            raise ValueError(f"Ray 实际资源发现失败：{discovery.error}")
    task = get_task(str(request.get("task_id", "")), prediction=prediction)
    if task is None:
        return request
    stages = {stage["id"]: stage for stage in task["stages"]}
    if set(expected_digests) - set(stages):
        raise ValueError('硬件参数摘要包含未知阶段')
    for stage in stages.values():
        hardware.setdefault(stage['id'], stage['default_device'])
    for stage_id, value in hardware.items():
        stage = stages.get(stage_id)
        if stage is None:
            continue
        target = hardware_registry.resolve(str(value), tuple(stage["allowed_devices"]))
        if not prediction and os.environ.get("FUSION_EXECUTOR", "dry_run").lower() == "ray" and stage_id == "classical_predict" and target.kind != "gpu":
            raise ValueError("当前 H₂O Ray runner 的经典模型必须选择 GPU")
        if not prediction and os.environ.get('FUSION_EXECUTOR', 'dry_run').lower() == 'ray' and stage_id == 'trajectory_analysis' and target.kind != 'cpu':
            raise ValueError('当前 H₂O 轨迹分析在 CPU 协调器上执行')
        if (
            not prediction and os.environ.get("FUSION_EXECUTOR", "dry_run").lower() == "ray"
            and target.kind == "qpu_simulator"
        ):
            raise ValueError("当前真实 Ray H₂O runner 尚未接入 qpu_simulator，请选择 GPU 或真实 QPU")
        hardware[stage_id] = target.kind
        target_ids[stage_id] = target.id
        snapshot = deepcopy(target.target_snapshot)
        if stage_id in expected_digests and expected_digests[stage_id] != (snapshot or {}).get('profile_sha256'):
            raise ValueError('目标硬件参数已更新，请刷新设备列表后重新编译或提交')
        if snapshot is not None:
            if stage_id in ('quantum_features', 'circuit_execution'):
                width = 3 if stage_id == 'quantum_features' else request['program']['circuit']['qubits']
                if width > snapshot['parameters'].get('qubits', width):
                    raise ValueError('电路逻辑比特数超过所选芯片容量')
                snapshot['logical_qubits'] = width
            snapshots[stage_id] = snapshot
    request["hardware"] = hardware
    if NETWORK_DEVICES and not prediction:
        for stage_id in ('force_and_integration', 'trajectory_analysis'):
            if target_ids.get(stage_id) != target_ids.get('initialization'):
                raise ValueError('当前 H₂O 初始化、积分与轨迹分析必须使用同一个 CPU 协调节点')
    request["hardware_targets"] = target_ids
    # Never accept client-authored parameter snapshots, even for old drafts.
    request['target_snapshots'] = snapshots
    return request


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _submit_plan(body: dict[str, Any], plan) -> Run:
    if body.get('source') and not body.get('program', {}).get('execution_sha256'):
        body['program'] = seal_program(body, plan)
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    run = Run(run_id, plan.task_id, "QUEUED", body, plan)
    run.output_root = os.environ['FUSION_RAY_OUTPUT_ROOT']
    run.execution_mode = execution_mode()
    with LOCK:
        RUNS[run_id] = run
        write_history(HISTORY_FILE, RUNS)
    try:
        if NETWORK_DEVICES:
            hardware = DEVICES.reserve(run_id, [s.target_id for s in plan.stages if s.target_id])
            run.events.append({'type': 'devices_reserved', 'ids': [s.target_id for s in plan.stages if s.target_id]})
            qpu_configs = {s.target_id: DEVICES.qpu_config(s.target_id) for s in plan.stages if s.device == 'qpu'}
            EXECUTOR.start(run, Handler._updated, hardware=hardware, qpu_configs=qpu_configs)
        else:
            EXECUTOR.start(run, Handler._updated)
    except Exception as error:
        DEVICES.release(run_id)
        run.status = 'FAILED'
        run.result = {'execution_mode': execution_mode(), 'logs': ['无法提交任务：' + str(error)]}
        run.events.append({'type': 'submission_failed', 'message': str(error) if isinstance(error, ValueError) else type(error).__name__})
        Handler._updated(run)
    return run


class Handler(BaseHTTPRequestHandler):
    server_version = "HybridFusion/0.1"

    def _send(self, status: int, body: Any) -> None:
        payload = json_bytes(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if status != 204:
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _file(self, path: Path, *, download=False):
        try:
            handle = path.open('rb')
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            return self._send(404, {'error': 'file_not_found'})
        with handle:
            self.send_response(200)
            self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            self.send_header('Content-Length', str(os.fstat(handle.fileno()).st_size))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-cache')
            if download:
                from urllib.parse import quote
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(path.name))
            self.end_headers()
            try:
                shutil.copyfileobj(handle, self.wfile)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _static(self, raw_path):
        root = (DASHBOARD_ROOT / 'frontend/dist').resolve()
        path = unquote(raw_path)
        if '\\' in path or any(part in ('.', '..') for part in path.split('/')):
            return self._send(404, {'error': 'not_found'})
        candidate = (root / ('index.html' if path in ('/', '/index.html') else path.lstrip('/'))).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return self._send(404, {'error': 'not_found'})
        return self._file(candidate)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 1048576:
            raise ValueError('invalid request size')
        body = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(body, dict):
            raise ValueError('request must be a JSON object')
        return body

    def do_OPTIONS(self) -> None:
        self._send(204, {})

    def do_GET(self) -> None:
        try:
            self._get()
        except (ValueError, TypeError, KeyError) as error:
            self._send(400, {'error': 'invalid_request', 'message': str(error)})
        except (OSError, RuntimeError) as error:
            self._send(503, {'error': 'service_unavailable', 'message': str(error)})

    def _get(self) -> None:
        path = urlparse(self.path).path
        if not path.startswith('/api/'):
            return self._static(path)
        if path.startswith('/api/v1/performance/runs/') and len(path.split('/')) == 6:
            prediction = PREDICTIONS.get(path.rsplit('/', 1)[-1])
            return self._send(200, prediction) if prediction else self._send(404, {'error': 'prediction_not_found'})
        if path == "/api/v1/task-types":
            return self._send(200, {"items": task_types()})
        if path == "/api/v1/examples":
            return self._send(200, {"items": all_examples()})
        if path.startswith("/api/v1/task-types/") and len(path.split('/')) == 5:
            task = get_task(path.rsplit("/", 1)[-1])
            return self._send(200, task) if task else self._send(404, {"error": "task_not_found"})
        if path == "/api/v1/hardware-targets":
            if NETWORK_DEVICES:
                try:
                    return self._send(200, {'items': DEVICES.snapshot(), 'live': True, 'source': 'network', 'error': None})
                except Exception:
                    return self._send(503, {'items': [], 'live': True, 'error': 'Ray resource discovery unavailable'})
            hardware, discovery = active_hardware()
            return self._send(200, {"items": [target.as_dict() | {"registered": True, "source": "ray" if discovery.live else "backend"} for target in hardware.all()], "live": discovery.live, "error": discovery.error})
        if path == "/api/v1/system/status":
            executor = os.environ.get("FUSION_EXECUTOR", "dry_run").lower()
            qperfsim = QPerfSimClient().availability()
            hardware, discovery = active_hardware()
            targets = hardware.all()
            return self._send(200, {
                "executor": executor,
                "executor_label": {'ray': 'Ray 实时执行', 'local_cpu': 'Simulation · CPU 数值计算', 'dry_run': '演示模式'}[executor],
                "mode": executor,
                "capabilities": self._capabilities(qperfsim),
                "qperfsim": qperfsim,
                "hardware": {
                    "total": len(targets),
                    "available": sum(1 for target in targets if target.available),
                    "by_kind": {kind: sum(1 for target in targets if target.kind == kind) for kind in sorted({target.kind for target in targets})},
                },
                "resource_discovery": {"live": discovery.live, "error": discovery.error, "ray_resources": discovery.ray_resources},
            })
        if path == "/api/v1/projects":
            with LOCK:
                return self._send(200, {"items": [project.as_dict(False) for project in PROJECTS.values()]})
        if path.startswith("/api/v1/projects/"):
            parts = path.split("/")
            project = get_project(parts[4]) if len(parts) > 4 else None
            if not project:
                return self._send(404, {"error": "project_not_found"})
            if len(parts) == 5:
                return self._send(200, project.as_dict())
            if len(parts) == 6 and parts[5] == "files":
                return self._send(200, {"items": project.as_dict()["files"]})
            if len(parts) == 6 and parts[5] == "compiles":
                items = [item for item in COMPILES.values() if item["project_id"] == project.id]
                return self._send(200, {"items": items})
        if path == "/api/v1/runs":
            with LOCK:
                return self._send(200, {"items": [run.as_dict() for run in RUNS.values()]})
        if path.startswith("/api/v1/runs/"):
            parts = path.split("/")
            run_id = parts[4] if len(parts) > 4 else ""
            with LOCK:
                run = RUNS.get(run_id)
            if not run:
                return self._send(404, {"error": "run_not_found"})
            run_mode = getattr(run, 'execution_mode', None) or (run.result or {}).get('execution_mode')
            if run.status in {'SUCCEEDED', 'FAILED', 'CANCELLED'} and run_mode == 'ray':
                enrich_result(run, results.run_directory(run, output_root(run)).parent)
            if len(parts) == 6 and parts[5] == 'series':
                return self._send(200, results.read_series(run, output_root(run)))
            if len(parts) == 6 and parts[5] == 'trajectory':
                query = parse_qs(urlparse(self.path).query)
                return self._send(200, results.read_trajectory(run, output_root(run), start=int(query.get('start', ['0'])[0]), limit=int(query.get('limit', ['500'])[0])))
            if len(parts) == 7 and parts[5] == 'artifacts':
                try:
                    artifact = results.artifact_path(run, parts[6], output_root(run))
                except FileNotFoundError:
                    return self._send(404, {'error': 'artifact_not_found'})
                return self._file(artifact, download=True)
            if len(parts) == 6 and parts[5] == "result":
                result = dict(run.result) if run.result is not None else None
                if result is not None:
                    result['artifacts'] = results.list_artifacts(run, output_root(run))
                    result['calculation_checks'] = results.read_calculation_checks(run, output_root(run))
                return self._send(200, {"run_id": run.id, "status": run.status, "result": result, "events": run.events})
            if len(parts) == 5:
                return self._send(200, run.as_dict())
        return self._send(404, {"error": "not_found"})

    def do_DELETE(self) -> None:
        try:
            self._delete()
        except (ValueError, TypeError, KeyError) as error:
            self._send(400, {'error': 'invalid_request', 'message': str(error)})
        except (OSError, RuntimeError) as error:
            self._send(503, {'error': 'service_unavailable', 'message': str(error)})

    def _delete(self) -> None:
        path = urlparse(self.path).path
        origin = self.headers.get('Origin')
        if origin:
            parsed_origin = urlparse(origin)
            if parsed_origin.scheme not in ('http', 'https') or parsed_origin.netloc != self.headers.get('Host'):
                return self._send(403, {'error': 'origin_not_allowed'})
        parts = path.split('/')
        if not (path.startswith('/api/v1/runs/') and len(parts) == 5 and parts[4]):
            return self._send(404, {'error': 'not_found'})
        run_id = parts[4]
        with LOCK:
            run = RUNS.get(run_id)
            if not run:
                return self._send(404, {'error': 'run_not_found'})
            if run.status not in {'SUCCEEDED', 'FAILED', 'CANCELLED', 'INTERRUPTED'}:
                return self._send(409, {
                    'error': 'run_active',
                    'message': '运行中的任务不能删除，请先取消任务并等待结束',
                })
            del RUNS[run_id]
            write_history(HISTORY_FILE, RUNS)
        return self._send(200, {'deleted': run_id})

    @staticmethod
    def _capabilities(qperfsim=None):
        caps = readiness(EXECUTOR_ERROR)
        if qperfsim is not None and not qperfsim['available']:
            for task in caps['tasks'].values():
                if task['performance']['available']:
                    task['performance'] = {'available': False, 'reason': '性能模拟器未就绪：' + str(qperfsim.get('reason') or '')}
            caps['performance'] = caps['tasks']['h2o-hybrid-aimd']['performance']
        return caps

    def do_POST(self) -> None:
        try:
            self._post()
        except (ValueError, TypeError, KeyError) as error:
            self._send(400, {'error': 'invalid_request', 'message': str(error)})
        except (OSError, RuntimeError) as error:
            self._send(503, {'error': 'service_unavailable', 'message': str(error)})

    def _post(self) -> None:
        path = urlparse(self.path).path
        if self.headers.get_content_type() != 'application/json':
            return self._send(415, {'error': 'json_required', 'message': '请求必须使用 application/json'})
        origin = self.headers.get('Origin')
        if origin:
            parsed_origin = urlparse(origin)
            if parsed_origin.scheme not in ('http', 'https') or parsed_origin.netloc != self.headers.get('Host'):
                return self._send(403, {'error': 'origin_not_allowed'})
        if path.startswith('/api/v1/devices/'):
            if not NETWORK_DEVICES:
                return self._send(404, {'error': 'network_registration_disabled'})
            if not secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + REGISTRATION_TOKEN):
                return self._send(401, {'error': 'invalid_registration_token'})
        try:
            body = self._body()
        except (ValueError, UnicodeDecodeError):
            return self._send(400, {"error": "invalid_json"})

        if path.startswith('/api/v1/devices/'):
            try:
                if path == '/api/v1/devices/register':
                    return self._send(201, DEVICES.register(body))
                if path.endswith('/heartbeat'):
                    DEVICES.heartbeat(path.split('/')[-2], body.get('lease'), body.get('healthy'))
                    return self._send(200, {'ok': True})
                if path.endswith('/reconcile') and body.get('device_idle_confirmed') is True:
                    DEVICES.reconcile(path.split('/')[-2])
                    return self._send(200, {'ok': True})
            except (ValueError, TypeError, KeyError) as error:
                return self._send(422, {'error': 'registration_rejected', 'message': str(error)})
            return self._send(404, {'error': 'not_found'})

        if path in {"/api/v1/performance/preview", "/api/v1/performance/run"}:
            try:
                body = _normalize_request(body, prediction=True)
            except ValueError as error:
                return self._send(422, {"valid": False, "errors": [{"path": "hardware", "message": str(error)}]})
            errors, plan = validate_and_plan(body, prediction=True)
            if errors or plan is None:
                return self._send(422, {"valid": False, "errors": errors})
            reason = QPerfSimClient.prediction_reason(plan)
            if reason:
                return self._send(422, {'error': 'unsupported_configuration', 'message': reason})
            if body.get('program'):
                body['program'] = seal_program(body, plan)
            client = QPerfSimClient()
            preview = path.endswith("/preview")
            availability = ({"available": None, "checked": False, "reason": "preview 未探测原生引擎",
                             "version": None, "interface": "c_api", "executable": None,
                             "library": str(client.library)} if preview else client.availability())
            if not preview and not availability["available"]:
                return self._send(503, {
                    "error": "qperfsim_unavailable",
                    "message": availability["reason"],
                    "qperfsim": availability,
                })
            output_root = Path(os.environ.get("FUSION_PERF_OUTPUT_ROOT", tempfile.gettempdir()))
            output_dir = output_root / f"qperfsim-{uuid.uuid4().hex[:12]}"
            output_dir.mkdir(parents=True, exist_ok=True)
            try:
                prediction = client.predict(plan, output_dir, preview=preview, program=body.get('program'))
            except QPerfSimUnavailable as error:
                return self._send(502, {"error": "qperfsim_failed", "message": str(error), "output_dir": str(output_dir)})
            return self._send(200, PREDICTIONS.save({
                "valid": True,
                "plan": plan.as_dict(),
                "program": body.get('program'),
                "qperfsim": availability,
                **prediction,
            }))

        if path == "/api/v1/projects":
            name = str(body.get("name", "未命名项目")).strip() or "未命名项目"
            task_id = str(body.get("task_id", "h2o-hybrid-aimd"))
            raw_files = body.get("files") or {}
            if not isinstance(raw_files, dict):
                return self._send(422, {"error": "files_must_be_object"})
            project = create_project(name, task_id, {str(key): str(value) for key, value in raw_files.items()})
            return self._send(201, project.as_dict())

        if path.startswith("/api/v1/projects/"):
            parts = path.split("/")
            project = get_project(parts[4]) if len(parts) > 4 else None
            if not project:
                return self._send(404, {"error": "project_not_found"})
            request = dict(body)
            request["task_id"] = project.task_id
            if len(parts) == 6 and parts[5] == "files":
                file_path = str(body.get("path", "")).strip().replace("\\", "/")
                content = body.get("content")
                if not file_path or not isinstance(content, str) or file_path.startswith("/") or ".." in file_path.split("/"):
                    return self._send(422, {"error": "invalid_file"})
                project.files[file_path] = content
                return self._send(200, project.as_dict())
            if len(parts) == 6 and parts[5] in {"check", "compile", "run"}:
                capability = self._capabilities()['tasks'].get(project.task_id, {}).get('run' if parts[5] == 'run' else 'compile', {'available': True})
                if not capability['available']:
                    return self._send(503, {'error': 'capability_unavailable', 'message': capability['reason']})
                source = body.get('source', project.files.get('main.py',''))
                request['source'] = source
                # Per-request immutable copy: another tab's save cannot alter this submission.
                project = replace(project, files={**project.files, 'main.py':source})
                try:
                    request = _normalize_request(request)
                except ValueError as error:
                    return self._send(422, {"valid": False, "errors": [{"path": "hardware", "message": str(error)}]})
                errors, plan = validate_and_plan(request)
                if errors or plan is None:
                    return self._send(422, {"valid": False, "errors": errors})
                result = compile_project(project, plan)
                compile_id = f"compile-{uuid.uuid4().hex[:12]}"
                COMPILES[compile_id] = {"id": compile_id, "project_id": project.id, **result}
                if parts[5] == "check":
                    return self._send(200, {"compile_id": compile_id, "plan": plan.as_dict(), **result})
                if not result["valid"]:
                    return self._send(422, {"compile_id": compile_id, "plan": plan.as_dict(), **result})
                request['program'] = result['program']
                if parts[5] == "compile":
                    return self._send(200, {"compile_id": compile_id, "plan": plan.as_dict(), **result})
                run = _submit_plan(request, plan)
                return self._send(202, {"compile_id": compile_id, "run": run.as_dict(), **result})

        if path == "/api/v1/runs/validate":
            try:
                body = _normalize_request(body)
            except ValueError as error:
                return self._send(422, {"valid": False, "errors": [{"path": "hardware", "message": str(error)}]})
            errors, plan = validate_and_plan(body)
            response = {"valid": not errors, "errors": errors, "plan": plan.as_dict() if plan else None}
            return self._send(200, response)
        if path == "/api/v1/runs":
            if not body.get('source'):
                return self._send(422, {'error': 'source_required', 'message': '运行任务必须提交程序源码'})
            try:
                body = _normalize_request(body)
            except ValueError as error:
                return self._send(422, {"valid": False, "errors": [{"path": "hardware", "message": str(error)}]})
            errors, plan = validate_and_plan(body)
            if errors:
                return self._send(422, {"valid": False, "errors": errors})
            capability = self._capabilities()['tasks'].get(plan.task_id, {}).get('run', {'available': True})
            if not capability['available']:
                return self._send(503, {'error': 'capability_unavailable', 'message': capability['reason']})
            run = _submit_plan(body, plan)
            return self._send(202, run.as_dict())
        if path.startswith("/api/v1/runs/") and path.endswith("/cancel") and len(path.split('/')) == 6:
            run_id = path.split("/")[-2]
            with LOCK:
                run = RUNS.get(run_id)
                if not run:
                    return self._send(404, {"error": "run_not_found"})
            cancel = getattr(EXECUTOR, "cancel", None)
            if callable(cancel) and run.status not in {'SUCCEEDED', 'FAILED', 'CANCELLED'}:
                cancel(run)
                Handler._updated(run)
            return self._send(200, run.as_dict())
        return self._send(404, {"error": "not_found"})

    @staticmethod
    def _updated(run: Run) -> None:
        if run.status in {'SUCCEEDED', 'FAILED', 'CANCELLED'}:
            if run.status != 'SUCCEEDED' and any(e.get('type') == 'devices_reserved' for e in run.events):
                DEVICES.quarantine([s.target_id for s in run.plan.stages if s.device == 'qpu' and s.target_id])
            DEVICES.release(run.id)
        with LOCK:
            RUNS[run.id] = run
            write_history(HISTORY_FILE, RUNS)

    def log_message(self, *_args) -> None:
        return


def main() -> None:
    from serve import main as serve_main
    raise SystemExit(serve_main())


if __name__ == "__main__":
    main()
