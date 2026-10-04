"""Build and optionally submit an AIMD application using QPUCircuitService."""

from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import time
from typing import Iterable

from pivotq._internal.jobs import (
    RayJobClient,
    RayJobDriverResources,
    RayJobRuntimeEnvironment,
    RayJobSpec,
    RayJobStatus,
)

QPU_REGISTRATION_TARGET = "pivotq._internal.qpu_integration.registration:register_components"
DEFAULT_AIMD_RUNNER_TARGET = "aimd.runner:run_aimd"
_IMPORT_TARGET_PATTERN = re.compile(
    r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$"
)
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,114}$")


def build_job_spec(
    *,
    submission_id: str,
    working_dir: str,
    output_dir: str,
    runner_target: str = DEFAULT_AIMD_RUNNER_TARGET,
    namespace: str = "aimd-qpu",
    python_command: str = "python",
    trace_max_records: int = 10_000,
    trace_event_max_records: int | None = None,
) -> RayJobSpec:
    """Build one application submission without connecting to Ray Jobs."""

    if (
        not isinstance(submission_id, str)
        or _RUN_ID_PATTERN.fullmatch(submission_id) is None
    ):
        raise ValueError(
            "submission_id must be a QPU-run-safe ID of at most 115 characters"
        )
    if not isinstance(output_dir, str) or not PurePosixPath(output_dir).is_absolute():
        raise ValueError("output_dir must be an absolute path on the Linux cluster")
    runner_target = _require_import_target("runner_target", runner_target)
    python_command = _require_text("python_command", python_command)
    if isinstance(trace_max_records, bool) or not isinstance(trace_max_records, int):
        raise TypeError("trace_max_records must be an integer")
    if trace_max_records <= 0:
        raise ValueError("trace_max_records must be greater than zero")
    if trace_event_max_records is not None:
        if isinstance(trace_event_max_records, bool) or not isinstance(
            trace_event_max_records,
            int,
        ):
            raise TypeError("trace_event_max_records must be an integer or None")
        if trace_event_max_records <= 0:
            raise ValueError("trace_event_max_records must be greater than zero")

    entrypoint_parts = [
        python_command,
        "-m",
        "pivotq.jobs.driver",
        "--run-id",
        submission_id,
        "--registration",
        QPU_REGISTRATION_TARGET,
        "--runner",
        runner_target,
        "--namespace",
        namespace,
        "--output-dir",
        output_dir,
        "--trace-max-records",
        str(trace_max_records),
    ]
    if trace_event_max_records is not None:
        entrypoint_parts.extend(
            ("--trace-event-max-records", str(trace_event_max_records))
        )
    entrypoint = shlex.join(entrypoint_parts)
    return RayJobSpec(
        submission_id=submission_id,
        entrypoint=entrypoint,
        runtime_environment=RayJobRuntimeEnvironment(
            working_dir=working_dir,
            env_vars={"PYTHONPATH": "src:."},
        ),
        metadata={
            "application": "aimd-qpu-integration",
            "qpu_contract": "qasm3-full-3q-v1",
            "device_protocol": "not_configured",
            "scientific_result": "false",
        },
        driver_resources=RayJobDriverResources(num_cpus=0.2),
    )


def wait_for_terminal(
    client: RayJobClient,
    submission_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> RayJobStatus:
    """Wait for one Ray Job with an explicit upper bound."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    deadline = time.monotonic() + timeout_seconds
    status = client.status(submission_id)
    while not status.is_terminal and time.monotonic() < deadline:
        time.sleep(poll_seconds)
        status = client.status(submission_id)
    if not status.is_terminal:
        raise TimeoutError(
            "Ray Job did not reach a terminal state; reconcile it by submission ID"
        )
    return status


def main(argv: Iterable[str] | None = None) -> int:
    parser = _argument_parser()
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    address = arguments.address or os.environ.get("RAY_JOBS_ADDRESS")
    if not address:
        parser.error("--address or RAY_JOBS_ADDRESS is required")
    if arguments.wait_timeout <= 0:
        parser.error("--wait-timeout must be positive")
    if arguments.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")

    spec = build_job_spec(
        submission_id=arguments.submission_id,
        working_dir=str(arguments.working_dir.expanduser().resolve()),
        output_dir=arguments.output_dir,
        runner_target=arguments.runner,
        namespace=arguments.namespace,
        python_command=arguments.python_command,
        trace_max_records=arguments.trace_max_records,
        trace_event_max_records=arguments.trace_event_max_records,
    )
    client = RayJobClient(address)
    handle = client.submit(spec)
    status = wait_for_terminal(
        client,
        handle.submission_id,
        timeout_seconds=arguments.wait_timeout,
        poll_seconds=arguments.poll_seconds,
    )
    print(f"AIMD_QPU_SUBMISSION_ID={handle.submission_id}")
    print(f"AIMD_QPU_JOB_STATUS={status.value}")
    if arguments.show_logs:
        print(client.logs(handle))
    if arguments.delete_terminal_metadata:
        client.delete(handle)
    return 0 if status is RayJobStatus.SUCCEEDED else 1


def _argument_parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(
        description="Submit one AIMD application with the isolated QPU integration."
    )
    parser.add_argument("--address")
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--working-dir", type=Path, default=project_root)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--runner", default=DEFAULT_AIMD_RUNNER_TARGET)
    parser.add_argument("--namespace", default="aimd-qpu")
    parser.add_argument("--python-command", default="python")
    parser.add_argument("--trace-max-records", type=int, default=10_000)
    parser.add_argument(
        "--trace-event-max-records",
        type=int,
        help="Enable bounded Trace v2 JSONL lifecycle events when provided.",
    )
    parser.add_argument("--wait-timeout", type=float, default=900.0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--show-logs", action="store_true")
    parser.add_argument("--delete-terminal-metadata", action="store_true")
    return parser


def _require_import_target(name: str, value: object) -> str:
    value = _require_text(name, value)
    if _IMPORT_TARGET_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must use 'package.module:callable' syntax")
    return value


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty without surrounding whitespace")
    return value


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_AIMD_RUNNER_TARGET",
    "QPU_REGISTRATION_TARGET",
    "build_job_spec",
    "main",
    "wait_for_terminal",
]
