"""Resolve deployment paths without creating files or importing compute libraries."""
from __future__ import annotations

import os
from pathlib import Path
import sys

DASHBOARD_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = DASHBOARD_ROOT.parent
LEGACY_ROOT = REPOSITORY_ROOT / "fusion-platform"
APPLICATION_ROOT = REPOSITORY_ROOT / "applications" / "h2o-hybrid-aimd"


def data_path(relative: str) -> Path:
    """Keep existing data in place; never rotate credentials during migration."""
    legacy = LEGACY_ROOT / relative
    return legacy if legacy.exists() else DASHBOARD_ROOT / relative


def configure_defaults() -> None:
    defaults = {
        "FUSION_EXECUTOR": "local_cpu",
        "FUSION_API_HOST": "127.0.0.1",
        "FUSION_API_PORT": "8787",
        "FUSION_RUN_HISTORY_FILE": data_path("runtime-state/runs.json"),
        "FUSION_DEVICE_STATE_FILE": data_path("runtime-state/devices.json"),
        "FUSION_REGISTRATION_TOKEN_FILE": data_path("secrets/registration.token"),
        "FUSION_RAY_OUTPUT_ROOT": data_path("ray-outputs"),
        "FUSION_PERF_OUTPUT_ROOT": data_path("performance-outputs"),
        "FUSION_RAY_WORKING_DIR": APPLICATION_ROOT,
        "FUSION_RAY_CONFIG_PATH": APPLICATION_ROOT / "configs/h2o_aimd.yaml",
        "FUSION_RAY_CHECKPOINT_PATH": APPLICATION_ROOT / "checkpoints/hybrid_model.pt",
        "FUSION_RAY_PYTHON": sys.executable,
        "RAY_JOBS_ADDRESS": "http://127.0.0.1:8265",
    }
    for name, value in defaults.items():
        os.environ.setdefault(name, str(value))
    runtime = data_path(".qperfsim-runtime")
    if (runtime / "usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2").is_file():
        os.environ.setdefault("FUSION_QPERFSIM_RUNTIME", str(runtime))


def execution_mode() -> str:
    raw = os.environ.get("FUSION_EXECUTOR", "local_cpu").lower()
    return {"local-cpu": "local_cpu", "demo": "dry_run"}.get(raw, raw)
