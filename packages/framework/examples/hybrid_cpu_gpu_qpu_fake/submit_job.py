"""Build and submit the bounded CPU/GPU/fake-QPU Ray Job."""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
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


REGISTRATION_TARGET = "examples.hybrid_cpu_gpu_qpu_fake.registration:register_components"
RUNNER_TARGET = "examples.hybrid_cpu_gpu_qpu_fake.runner:run_validation"


def build_job_spec(
    *,
    submission_id: str,
    working_dir: str,
    output_dir: str,
    python_command: str = "/opt/ray-quantum/venv/bin/python",
) -> RayJobSpec:
    root = Path(working_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("working_dir must be an existing project directory")
    if not PurePosixPath(output_dir).is_absolute():
        raise ValueError("output_dir must be an absolute Linux path")
    entrypoint = shlex.join(
        (
            "exec",
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
            "ray-quantum-hybrid-fake",
            "--output-dir",
            output_dir,
            "--trace-max-records",
            "3",
        )
    )
    return RayJobSpec(
        submission_id=submission_id,
        entrypoint=entrypoint,
        runtime_environment=RayJobRuntimeEnvironment(
            working_dir=str(root),
            env_vars={
                "PYTHONPATH": "src:.",
            },
        ),
        metadata={
            "application": "ray-quantum-hybrid-fake-validation",
            "fixed_count_fixture": "true",
            "qpu_hardware_used": "false",
            "validation_only": "true",
        },
        driver_resources=RayJobDriverResources(num_cpus=0.2),
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="http://127.0.0.1:8265")
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--working-dir", type=Path, required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--python-command", default="/opt/ray-quantum/venv/bin/python")
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    arguments = parser.parse_args(list(argv) if argv is not None else None)

    client = RayJobClient(arguments.address)
    handle = client.submit(
        build_job_spec(
            submission_id=arguments.submission_id,
            working_dir=str(arguments.working_dir),
            output_dir=arguments.output_dir,
            python_command=arguments.python_command,
        )
    )
    deadline = time.monotonic() + arguments.timeout_seconds
    while True:
        status = client.status(handle)
        print(f"JOB_STATUS={status.value}", flush=True)
        if status.is_terminal:
            break
        if time.monotonic() >= deadline:
            client.stop(handle)
            raise TimeoutError("validation job exceeded its bounded timeout")
        time.sleep(2.0)
    print(client.logs(handle), flush=True)
    return _terminal_exit_code(status)


def _terminal_exit_code(status: RayJobStatus) -> int:
    return 0 if status is RayJobStatus.SUCCEEDED else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_job_spec", "main"]
