"""Read recorded AIMD data and expose only bounded, run-local artifacts."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}
MAX_TRAJECTORY_FRAMES = 500
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_ARTIFACT_ID = re.compile(r"artifact-[0-9a-f]{24}\Z")
_DASHBOARD = Path(__file__).resolve().parents[1]
_KNOWN_FILES = (
    "aimd/md_log.csv", "aimd/positions.csv", "aimd/h2o_aimd.traj",
    "aimd/metrics.json", "aimd/run_summary.json", "aimd/ood_stop_geometry.json",
    "md_log.csv", "positions.csv", "h2o_aimd.traj", "trajectory.xyz",
    "metrics.json", "run_summary.json", "artifact_manifest.json",
    "stdout.log", "stderr.log", "worker.log", "run.log",
    "figures/h2o_aimd_summary.png", "figures/h2o_aimd_trajectory_3d.png",
    "figures/aimd_summary.png", "figures/aimd_trajectory_3d.png",
)


def _contained(root: Path, relative: str) -> Path:
    """Reject traversal, platform-specific separators, and escaping symlinks."""
    if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
        raise ValueError("invalid artifact path")
    parts = relative.split("/")
    if any(not part or part in {".", ".."} or part.startswith(".") or ":" in part for part in parts):
        raise ValueError("invalid artifact path")
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("artifact escapes run directory")
    return path


def run_directory(run: Any, output_root: str | Path | None = None) -> Path:
    """Resolve stored output location, then configured and migrated legacy roots."""
    if not isinstance(run.id, str) or not _RUN_ID.fullmatch(run.id):
        raise ValueError("invalid run id")
    stored = getattr(run, "output_root", None)
    if stored:
        return _contained(Path(stored).expanduser().resolve(), run.id)
    roots = [output_root]
    roots.extend(os.environ.get(name) for name in (
        "FUSION_OUTPUT_ROOT", "FUSION_LOCAL_OUTPUT_ROOT", "FUSION_RAY_OUTPUT_ROOT",
    ))
    roots.extend((_DASHBOARD / "outputs", _DASHBOARD / "local-outputs",
                  _DASHBOARD / "ray-outputs", _DASHBOARD.parent / "fusion-platform" / "ray-outputs"))
    candidates = [_contained(Path(root).expanduser().resolve(), run.id) for root in roots if root]
    return next((path for path in candidates if path.is_dir()), candidates[0])


def _data_file(root: Path, name: str) -> Path | None:
    for relative in ("aimd/" + name, name):
        try:
            path = _contained(root, relative)
        except (ValueError, OSError, RuntimeError):
            continue
        if path.is_file():
            return path
    return None


def _number(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite recorded value")
    return number


def _step_time(row: dict[str, Any]) -> tuple[int, float]:
    number = _number(row["step"])
    time_fs = _number(row["time_fs"])
    if number < 0 or not number.is_integer() or time_fs < 0:
        raise ValueError("invalid recorded step/time")
    return int(number), time_fs


def _value(value: Any) -> Any:
    if value is None or value == "":
        return None
    if value in ("True", "False"):
        return value == "True"
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return value


def _is_complete(run: Any, steps: list[int], invalid_rows: int = 0) -> bool:
    expected = run.plan.normalized_inputs.get("steps")
    return bool(run.status == "SUCCEEDED" and steps and steps[0] == 0
                and isinstance(expected, int) and steps[-1] >= expected and not invalid_rows)


def read_series(run: Any, output_root: str | Path | None = None) -> dict[str, Any]:
    """Read flushed numeric CSV rows; never generate physical values from a demo."""
    result: dict[str, Any] = {
        "items": [], "columns": [], "available": False, "complete": False,
        "units": {"time": "fs", "energy": "eV", "temperature": "K", "length": "Å"},
    }
    path = _data_file(run_directory(run, output_root), "md_log.csv")
    if path is None:
        return result | {"reason": "series_not_available"}
    invalid_rows = 0
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            result["columns"] = reader.fieldnames or []
            if not {"step", "time_fs"}.issubset(result["columns"]):
                return result | {"reason": "invalid_series_columns"}
            previous_step = -1
            previous_time = -1.0
            for row in reader:
                try:
                    step, time_fs = _step_time(row)
                    # A writer may be in the middle of its last line during polling.
                    if None in row or any(value is None for value in row.values()):
                        raise ValueError("incomplete CSV row")
                    if step <= previous_step or time_fs < previous_time:
                        raise ValueError("non-monotonic CSV row")
                    item = {key: _value(value) for key, value in row.items()}
                    item.update(step=step, time_fs=time_fs)
                except (ValueError, TypeError, KeyError):
                    invalid_rows += 1
                    continue
                result["items"].append(item)
                previous_step, previous_time = step, time_fs
    except (OSError, UnicodeError, csv.Error):
        return result | {"reason": "series_unreadable"}
    result.update(available=bool(result["items"]), invalid_rows=invalid_rows,
                  complete=_is_complete(run, [item["step"] for item in result["items"]], invalid_rows))
    return result


def read_trajectory(run: Any, output_root: str | Path | None = None, *,
                    start: int = 0, limit: int = MAX_TRAJECTORY_FRAMES) -> dict[str, Any]:
    """Page actual O/H/H positions after execution has terminated.

    start is a frame offset; frame.step and frame.time_fs retain the CSV values.
    complete describes the whole recorded run, independently of pagination.
    """
    if type(start) is not int or start < 0 or type(limit) is not int or limit < 1:
        raise ValueError("start must be non-negative and limit must be positive integers")
    limit = min(limit, MAX_TRAJECTORY_FRAMES)
    result: dict[str, Any] = {
        "symbols": ["O", "H", "H"], "frames": [], "total": 0,
        "start": start, "limit": limit, "complete": False, "available": False,
        "units": {"positions": "Å", "time": "fs"},
    }
    if run.status not in TERMINAL:
        return result | {"reason": "run_not_terminal"}
    path = _data_file(run_directory(run, output_root), "positions.csv")
    if path is None:
        return result | {"reason": "trajectory_not_available"}
    coordinate_columns = [f"{atom}_{axis}_A" for atom in ("O", "H1", "H2") for axis in "xyz"]
    invalid_rows = 0
    steps: list[int] = []
    previous_time = -1.0
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not {"step", "time_fs", *coordinate_columns}.issubset(reader.fieldnames or []):
                return result | {"reason": "invalid_trajectory_columns"}
            for row in reader:
                try:
                    step, time_fs = _step_time(row)
                    positions = [_number(row[column]) for column in coordinate_columns]
                    if None in row or (steps and step <= steps[-1]) or time_fs < previous_time:
                        raise ValueError("invalid trajectory row")
                except (ValueError, TypeError, KeyError):
                    invalid_rows += 1
                    continue
                if start <= len(steps) < start + limit:
                    result["frames"].append({"step": step, "time_fs": time_fs,
                                             "positions": [positions[i:i + 3] for i in (0, 3, 6)]})
                steps.append(step)
                previous_time = time_fs
    except (OSError, UnicodeError, csv.Error):
        return result | {"reason": "trajectory_unreadable"}
    result.update(total=len(steps), available=bool(steps), invalid_rows=invalid_rows,
                  complete=_is_complete(run, steps, invalid_rows))
    return result


def _allowed_artifact(relative: str) -> bool:
    path = PurePosixPath(relative)
    if path.suffix.lower() in {".csv", ".png", ".traj", ".xyz", ".log"}:
        return True
    return path.name in {"metrics.json", "run_summary.json", "artifact_manifest.json",
                         "ood_stop_geometry.json", "stdout.txt", "stderr.txt", "logs.txt"}


def _artifact_candidates(run: Any, root: Path) -> dict[str, str]:
    candidates = {name: name for name in _KNOWN_FILES if _data_exists(root, name)}
    entries: list[Any] = []
    try:
        manifest_path = _contained(root, "artifact_manifest.json")
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            entries.extend(manifest.get("artifacts", []) if isinstance(manifest, dict) else manifest)
    except (OSError, ValueError, TypeError, RuntimeError):
        pass
    result = run.result if isinstance(run.result, dict) else {}
    entries.extend(result.get("artifacts", []) or [])
    entries.extend(result.get("outputs", {}).get("artifact_manifest", []) or [])
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        relative = entry.get("relative_path") or entry.get("name")
        if not isinstance(relative, str) or not _allowed_artifact(relative):
            continue
        try:
            _contained(root, relative)
        except (ValueError, OSError, RuntimeError):
            continue
        candidates[relative] = relative
    return candidates


def _data_exists(root: Path, relative: str) -> bool:
    try:
        return _contained(root, relative).is_file()
    except (ValueError, OSError, RuntimeError):
        return False


def list_artifacts(run: Any, output_root: str | Path | None = None) -> list[dict[str, Any]]:
    root = run_directory(run, output_root)
    result = []
    for relative in sorted(_artifact_candidates(run, root)):
        artifact_id = "artifact-" + hashlib.sha256(relative.encode()).hexdigest()[:24]
        available = _data_exists(root, relative)
        entry = {"id": artifact_id, "name": relative, "available": available,
                 "type": mimetypes.guess_type(relative)[0] or "application/octet-stream"}
        if available:
            entry["download_url"] = f"/api/v1/runs/{run.id}/artifacts/{artifact_id}"
            entry["size_bytes"] = _contained(root, relative).stat().st_size
        result.append(entry)
    return result


def artifact_path(run: Any, artifact_id: str, output_root: str | Path | None = None) -> Path:
    if not isinstance(artifact_id, str) or not _ARTIFACT_ID.fullmatch(artifact_id):
        raise ValueError("invalid artifact id")
    root = run_directory(run, output_root)
    for entry in list_artifacts(run, output_root):
        if entry["id"] == artifact_id and entry["available"]:
            path = _contained(root, entry["name"])
            if path.is_file():
                return path
    raise FileNotFoundError("artifact not found")


def read_calculation_checks(run: Any, output_root: str | Path | None = None) -> list[dict[str, Any]]:
    """Explain recorded checks using that run's saved limits, never current defaults."""
    import yaml

    root = run_directory(run, output_root)
    def read_record(name: str, *, config: bool = False) -> dict[str, Any]:
        try:
            path = _data_file(root, name)
            if path is None or path.stat().st_size > 2_000_000:
                return {}
            text = path.read_text(encoding="utf-8-sig")
            value = yaml.safe_load(text) if config else json.loads(text)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError, RuntimeError, yaml.YAMLError):
            return {}

    metrics = read_record("metrics.json")
    summary = read_record("run_summary.json")
    acceptance = metrics.get("acceptance") or summary.get("acceptance") or {}
    if not isinstance(acceptance, dict) or not isinstance(acceptance.get("checks"), dict):
        return []
    simulation = metrics.get("simulation") or summary.get("simulation") or {}
    config = read_record("resolved_config.yaml", config=True).get("aimd", {})
    if not isinstance(simulation, dict): simulation = {}
    if not isinstance(config, dict): config = {}
    labels = {
        "trajectory_status_ok": ("轨迹完成状态", "轨迹状态为 ok"),
        "frame_count_matches": ("轨迹帧数", "帧数等于模拟步数 + 1"),
        "all_frames_finite": ("数值有效性", "所有轨迹帧数值有限"),
        "all_frames_in_training_domain": ("训练域范围", "所有构型在训练域内"),
        "ood_not_stopped": ("越域停止检查", "未因越出训练域而停止"),
    }
    limits = {
        "total_energy_drift_within_limit": ("总能量漂移", "total_energy_drift_eV", "max_total_energy_drift_eV", "eV"),
        "total_energy_range_within_limit": ("总能量变化范围", "total_energy_range_eV", "max_total_energy_range_eV", "eV"),
        "linear_energy_drift_within_limit": ("线性能量漂移", "linear_total_energy_drift_eV_per_ps", "max_linear_energy_drift_eV_per_ps", "eV/ps"),
        "center_of_mass_drift_within_limit": ("质心漂移", "center_of_mass_max_displacement_A", "max_center_of_mass_displacement_A", "Å"),
        "max_force_component_within_limit": ("最大受力分量", "max_force_component_eV_per_A", "max_force_component_eV_per_A", "eV/Å"),
        "adjacent_force_jump_within_limit": ("相邻步受力变化", "max_adjacent_force_jump_eV_per_A", "max_adjacent_force_jump_eV_per_A", "eV/Å"),
        "total_force_within_limit": ("总合力残差", "max_total_force_norm_eV_per_A", None, "eV/Å"),
        "total_torque_within_limit": ("总力矩残差", "max_total_torque_norm_eV", None, "eV"),
    }
    def finite(value: Any) -> bool:
        return type(value) in (int, float) and math.isfinite(value)

    result = []
    applicability = acceptance.get("metric_applicability", {})
    for name, passed in acceptance["checks"].items():
        if type(passed) is not bool:
            continue
        label, criterion = labels.get(name, (name, "此历史检查未记录判定标准"))
        observed = None
        if name in limits:
            label, field, limit_key, unit = limits[name]
            observed = simulation.get(field)
            # The two rigid-body residual gates are fixed at 1e-6 in run_aimd.py.
            threshold = config.get(limit_key) if limit_key else 1e-6
            criterion = f"绝对值 ≤ {threshold:g} {unit}" if finite(threshold) else "本次运行未保存阈值，请核对原始配置"
            observed = f"{abs(observed):g} {unit}" if finite(observed) else None
        if name == "linear_energy_drift_within_limit":
            detail = applicability.get("linear_energy_drift", {}) if isinstance(applicability, dict) else {}
            if isinstance(detail, dict) and detail.get("applicable_as_hard_gate") is False:
                criterion = f"本次仅供参考；至少 {detail.get('hard_gate_minimum_steps', '未记录')} 步才作为通过条件"
        if name == "finite_difference_step_refinement":
            label = "差分步长细化一致性"
            detail = metrics.get("force_consistency", {})
            if isinstance(detail, dict):
                threshold = detail.get("threshold_eV_per_A")
                value = detail.get("max_abs_error_eV_per_A")
                criterion = f"最大绝对误差 ≤ {threshold:g} eV/Å" if finite(threshold) else "本次运行未保存阈值"
                observed = f"{value:g} eV/Å" if finite(value) else None
        result.append({"id": name, "label": label, "passed": passed, "criterion": criterion, "observed": observed})
    return result
