"""Submit one complete AIMD run through the public Ray Jobs wrapper API."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import time
from typing import Any, Iterable

from .registration import AIMD_CONFIG_OVERRIDES_ENV, AIMD_CONFIG_PATH_ENV
from .runner import (
    AIMD_CHECKPOINT_PATH_ENV,
    AIMD_EXECUTION_MODE_ENV,
    AIMD_QUANTUM_TARGET_ENV,
    AIMD_TASK_ID_ENV,
)


REGISTRATION_TARGET = (
    "single_h20_aimd.integration.fusion_framework.registration:register_components"
)
RUNNER_TARGET = "single_h20_aimd.integration.fusion_framework.runner:run_aimd"
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MODULE_PATTERN = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
_IMPORT_TARGET_PATTERN = re.compile(
    r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$"
)


def build_job_spec(
    *,
    submission_id: str,
    working_dir: str,
    config_path: str,
    checkpoint_path: str,
    output_dir: str,
    execution_mode: str = "heterogeneous",
    quantum_target: str = "gpu",
    config_overrides: dict[str, Any] | None = None,
    namespace: str | None = None,
    python_command: str = "python",
    driver_num_cpus: float = 1.0,
    trace_max_records: int = 10_000,
    qos_helper_module: str | None = None,
    qos_data_tree_target: str | None = None,
) -> Any:
    """Build a framework-native ``RayJobSpec`` without contacting a cluster."""

    _require_run_id(submission_id)
    local_working_dir = Path(working_dir).expanduser().resolve()
    if not local_working_dir.is_dir():
        raise ValueError(f"working_dir must be a readable local directory: {local_working_dir}")
    for label, value in (
        ("config_path", config_path),
        ("checkpoint_path", checkpoint_path),
        ("output_dir", output_dir),
    ):
        if not isinstance(value, str) or not PurePosixPath(value).is_absolute():
            raise ValueError(f"{label} must be an absolute path on the Linux Ray cluster")
    if execution_mode not in {"heterogeneous", "colocated"}:
        raise ValueError("execution_mode must be heterogeneous or colocated")
    if quantum_target not in {"gpu", "qpu"}:
        raise ValueError("quantum_target must be gpu or qpu")
    if quantum_target == "qpu":
        qos_helper_module = _require_module_name(qos_helper_module)
        qos_data_tree_target = _require_import_target(qos_data_tree_target)
    if not isinstance(python_command, str) or not python_command.strip():
        raise ValueError("python_command must be a non-empty command")
    if driver_num_cpus <= 0.0:
        raise ValueError("driver_num_cpus must be positive")
    if trace_max_records < 0:
        raise ValueError("trace_max_records must be non-negative")
    overrides = dict(config_overrides or {})
    job_namespace = namespace or f"aimd-{submission_id}"

    entrypoint_parts = [
        python_command,
        "-m",
        "pivotq.jobs.driver",
        "--run-id",
        submission_id,
        "--registration",
        REGISTRATION_TARGET,
        "--runner",
        RUNNER_TARGET,
        "--namespace",
        job_namespace,
        "--output-dir",
        output_dir,
    ]
    if trace_max_records:
        entrypoint_parts.extend(("--trace-max-records", str(trace_max_records)))

    environment = {
        AIMD_CONFIG_PATH_ENV: config_path,
        AIMD_CHECKPOINT_PATH_ENV: checkpoint_path,
        AIMD_EXECUTION_MODE_ENV: execution_mode,
        AIMD_QUANTUM_TARGET_ENV: quantum_target,
        AIMD_TASK_ID_ENV: f"{submission_id}.aimd",
        AIMD_CONFIG_OVERRIDES_ENV: json.dumps(
            overrides, ensure_ascii=True, separators=(",", ":")
        ),
        "PYTHONPATH": ".",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if quantum_target == "qpu":
        try:
            from pivotq._internal.qpu_integration.registration import (
                QOS_DATA_TREE_TARGET_ENV,
                QOS_HELPER_MODULE_ENV,
            )
        except ImportError as error:
            raise RuntimeError(
                "pivotq._internal QPU registration is unavailable on the submitting machine."
            ) from error
        environment[QOS_HELPER_MODULE_ENV] = qos_helper_module
        environment[QOS_DATA_TREE_TARGET_ENV] = qos_data_tree_target
    jobs = _jobs_api()
    return jobs.RayJobSpec(
        submission_id=submission_id,
        entrypoint=shlex.join(entrypoint_parts),
        runtime_environment=jobs.RayJobRuntimeEnvironment(
            working_dir=str(local_working_dir),
            env_vars=environment,
        ),
        metadata={
            "application": "single-h20-aimd",
            "interface_version": "1",
            "scientific_scope": "h2o-f2-adapt-energy-force-nve-aimd",
        },
        driver_resources=jobs.RayJobDriverResources(num_cpus=float(driver_num_cpus)),
    )


def wait_for_terminal(
    client: Any,
    submission_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> Any:
    """Poll one submitted Job with a bounded client-side wait."""

    if timeout_seconds <= 0.0:
        raise ValueError("timeout_seconds must be positive")
    if poll_seconds <= 0.0:
        raise ValueError("poll_seconds must be positive")
    deadline = time.monotonic() + timeout_seconds
    status = client.status(submission_id)
    while not status.is_terminal and time.monotonic() < deadline:
        time.sleep(poll_seconds)
        status = client.status(submission_id)
    if not status.is_terminal:
        raise TimeoutError(
            "Ray Job did not reach a terminal state; reconcile or stop it by submission_id."
        )
    return status


def main(argv: Iterable[str] | None = None) -> int:
    parser = _argument_parser()
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    address = arguments.address or os.environ.get("RAY_JOBS_ADDRESS")
    if not address:
        parser.error("--address or RAY_JOBS_ADDRESS is required")

    overrides = _parse_overrides(arguments.config_overrides_json, parser)
    spec = build_job_spec(
        submission_id=arguments.submission_id,
        working_dir=str(arguments.working_dir),
        config_path=arguments.config_path,
        checkpoint_path=arguments.checkpoint_path,
        output_dir=arguments.output_dir,
        execution_mode=arguments.execution_mode,
        quantum_target=arguments.quantum_target,
        config_overrides=overrides,
        namespace=arguments.namespace,
        python_command=arguments.python_command,
        driver_num_cpus=arguments.driver_num_cpus,
        trace_max_records=arguments.trace_max_records,
        qos_helper_module=arguments.qos_helper_module,
        qos_data_tree_target=arguments.qos_data_tree_target,
    )
    jobs = _jobs_api()
    client = jobs.RayJobClient(address)

    # Exactly one submit call represents one complete logical AIMD run.
    handle = client.submit(spec)
    status = wait_for_terminal(
        client,
        handle.submission_id,
        timeout_seconds=arguments.wait_timeout,
        poll_seconds=arguments.poll_seconds,
    )
    print(f"AIMD_SUBMISSION_ID={handle.submission_id}")
    print(f"AIMD_JOB_STATUS={status.value}")
    if arguments.show_logs or status.value != "succeeded":
        print(client.logs(handle))
    if arguments.delete_terminal_metadata:
        client.delete(handle)
    return 0 if status.value == "succeeded" else 1


def _jobs_api() -> Any:
    try:
        from pivotq._internal import jobs
    except ImportError as error:
        raise RuntimeError(
            "pivotq._internal is not installed. Install the fusion framework library "
            "on the submitting machine before using this command."
        ) from error
    return jobs


def _require_run_id(value: object) -> str:
    if not isinstance(value, str) or _RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(
            "submission_id must be 1-128 characters, start with a letter or digit, "
            "and contain only letters, digits, '_', '-' or '.'."
        )
    return value


def _require_module_name(value: object) -> str:
    if not isinstance(value, str) or _MODULE_PATTERN.fullmatch(value) is None:
        raise ValueError(
            "qos_helper_module is required for QPU jobs and must be a Python module path"
        )
    return value


def _require_import_target(value: object) -> str:
    if not isinstance(value, str) or _IMPORT_TARGET_PATTERN.fullmatch(value) is None:
        raise ValueError(
            "qos_data_tree_target is required for QPU jobs and must use "
            "'package.module:callable' syntax"
        )
    return value


def _parse_overrides(text: str, parser: argparse.ArgumentParser) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        parser.error(f"--config-overrides-json is invalid JSON: {error}")
    if not isinstance(value, dict):
        parser.error("--config-overrides-json must be a JSON object")
    return value


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Submit one complete H2O AIMD run through pivotq._internal Ray Jobs."
    )
    parser.add_argument("--address")
    parser.add_argument("--submission-id", required=True)
    parser.add_argument(
        "--working-dir",
        required=True,
        type=Path,
        help="Local deployment directory containing the single_h20_aimd package.",
    )
    parser.add_argument("--config-path", required=True)
    parser.add_argument("--checkpoint-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--execution-mode", choices=("heterogeneous", "colocated"), default="heterogeneous"
    )
    parser.add_argument("--quantum-target", choices=("gpu", "qpu"), default="gpu")
    parser.add_argument(
        "--qos-helper-module",
        help="QOS helper Python 模块；--quantum-target=qpu 时必填。",
    )
    parser.add_argument(
        "--qos-data-tree-target",
        help="QOS DataTree 的 package.module:callable 目标；QPU 时必填。",
    )
    parser.add_argument("--config-overrides-json", default="{}")
    parser.add_argument("--namespace")
    parser.add_argument("--python-command", default="python")
    parser.add_argument("--driver-num-cpus", type=float, default=1.0)
    parser.add_argument("--trace-max-records", type=int, default=10_000)
    parser.add_argument("--wait-timeout", type=float, default=7200.0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--show-logs", action="store_true")
    parser.add_argument("--delete-terminal-metadata", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "REGISTRATION_TARGET",
    "RUNNER_TARGET",
    "build_job_spec",
    "main",
    "wait_for_terminal",
]
