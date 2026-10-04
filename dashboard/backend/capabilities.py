"""Cheap readiness checks; importing the API never starts a Ray cluster."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from .paths import execution_mode


def readiness(executor_error: str | None = None) -> dict:
    mode = execution_mode()
    missing = [name for name in ("torch", "ray", "numpy", "psutil", "pivotq") if importlib.util.find_spec(name) is None]
    compute_reason = executor_error or ("缺少 Python 依赖：" + ", ".join(missing) if missing else None)
    h2o_missing = [name for name in ("yaml", "qiskit", "ase", "single_h20_aimd") if importlib.util.find_spec(name) is None]
    model_reason = ("缺少 Python 依赖：" + ", ".join(h2o_missing)) if h2o_missing else None
    for name, label in (("FUSION_RAY_CONFIG_PATH", "AIMD 配置"), ("FUSION_RAY_CHECKPOINT_PATH", "模型文件")):
        if not Path(os.environ.get(name, "")).is_file():
            model_reason = f"未找到{label}，请检查 {name}"
            break
    def capability(reason):
        return {"available": reason is None, "reason": reason}
    circuit = {"compile": capability(None), "run": capability(None if mode == "dry_run" else compute_reason),
               "performance": capability(None)}
    h2o_compile_reason = model_reason or (compute_reason if missing else None)
    h2o = {"compile": capability(h2o_compile_reason),
           "run": capability(h2o_compile_reason or (None if mode == "dry_run" else compute_reason)),
           "performance": capability(None)}
    return {**h2o, "tasks": {"h2o-hybrid-aimd": h2o, "quantum-circuit": circuit}}
