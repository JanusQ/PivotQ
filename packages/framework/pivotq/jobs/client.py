"""Submit and manage complete Python applications through Ray Jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import shlex
import threading
from typing import Iterable, Mapping, Sequence
import uuid

from .._internal.jobs import (
    RayJobClient, RayJobDriverResources, RayJobRuntimeEnvironment, RayJobSpec,
    RayJobHandle, RayJobServiceError, RayJobStateError,
)
from .._internal.jobs.client import (
    _copy_string_mapping, _require_safe_jobs_address, _require_tls_verification,
)
from ..errors import SubmissionDisposition, SubmissionError


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (self.STOPPED, self.SUCCEEDED, self.FAILED)


class JobSubmissionError(SubmissionError):
    """Use ``framework_job_id`` to reconcile a possibly accepted submission."""

    code = "job_submission_failed"


# These errors carry no internal resource or scheduling types.
JobServiceError = RayJobServiceError
JobStateError = RayJobStateError


@dataclass(frozen=True, slots=True)
class JobHandle:
    submission_id: str

    def __post_init__(self) -> None:
        RayJobHandle(self.submission_id)


@dataclass(frozen=True, slots=True, repr=False)
class JobSpec:
    """One application. ``num_cpus`` reserves CPUs for the driver process only.

    ``entrypoint`` is an argument list, quoted as a command by the SDK. All
    workers must install the same PivotQ version as the driver. A working_dir
    may be a local directory or a Ray-supported remote archive.
    """

    entrypoint: Sequence[str] = field(repr=False)
    submission_id: str = field(default_factory=lambda: "pivotq-" + uuid.uuid4().hex)
    working_dir: str | None = None
    pip_packages: Iterable[str] = ()
    env_vars: Mapping[str, str] | Iterable[tuple[str, str]] = field(default=(), repr=False)
    num_cpus: float = 0
    metadata: Mapping[str, str] | Iterable[tuple[str, str]] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.entrypoint, (str, bytes)) or not isinstance(self.entrypoint, Sequence):
            raise TypeError("entrypoint must be a sequence of command arguments")
        arguments = tuple(self.entrypoint)
        if not arguments or not arguments[0] or any(not isinstance(a, str) for a in arguments):
            raise ValueError("entrypoint must contain a command and string arguments")
        environment = RayJobRuntimeEnvironment(self.working_dir, self.pip_packages, self.env_vars)
        resources = RayJobDriverResources(num_cpus=self.num_cpus)
        if resources.num_cpus is None:
            raise ValueError("num_cpus must be a non-negative number")
        spec = RayJobSpec(self.submission_id, shlex.join(arguments), environment,
                          self.metadata, resources)
        for key, value in (("entrypoint", arguments), ("working_dir", environment.working_dir),
                           ("pip_packages", environment.pip_packages), ("env_vars", environment.env_vars),
                           ("metadata", spec.metadata), ("num_cpus", resources.num_cpus)):
            object.__setattr__(self, key, value)

    def _as_internal(self) -> RayJobSpec:
        return RayJobSpec(
            self.submission_id, shlex.join(self.entrypoint),
            RayJobRuntimeEnvironment(self.working_dir, self.pip_packages, self.env_vars),
            self.metadata, RayJobDriverResources(num_cpus=self.num_cpus),
        )

    def __repr__(self) -> str:
        return (f"JobSpec(submission_id={self.submission_id!r}, entrypoint=<redacted>, "
                f"working_dir={self.working_dir!r}, num_cpus={self.num_cpus!r})")


class JobClient:
    """Lazy client; construction does not connect to Ray or start a cluster."""

    def __init__(self, address: str, *, headers: Mapping[str, str] | None = None,
                 cookies: Mapping[str, str] | None = None, verify: bool | str = True) -> None:
        self._address = _require_safe_jobs_address(address)
        self._headers = _copy_string_mapping("headers", headers)
        self._cookies = _copy_string_mapping("cookies", cookies)
        self._verify = _require_tls_verification(verify)
        self._client: RayJobClient | None = None
        self._lock = threading.Lock()

    def _connection(self) -> RayJobClient:
        with self._lock:
            if self._client is None:
                self._client = RayJobClient(self._address, headers=self._headers,
                                           cookies=self._cookies, verify=self._verify)
            return self._client

    def submit(self, spec: JobSpec) -> JobHandle:
        """Submit once. Submission failures retain the ID; never retry implicitly."""
        if not isinstance(spec, JobSpec):
            raise TypeError("spec must be a JobSpec")
        try:
            client = self._connection()
        except Exception:
            raise JobSubmissionError("Could not initialize the Jobs client",
                                     disposition=SubmissionDisposition.NOT_SUBMITTED,
                                     framework_job_id=spec.submission_id) from None
        try:
            handle = client.submit(spec._as_internal())
        except Exception:
            raise JobSubmissionError(
                "Job submission outcome is unknown; check status using framework_job_id",
                disposition=SubmissionDisposition.UNKNOWN,
                framework_job_id=spec.submission_id, backend_job_id=spec.submission_id,
            ) from None
        return JobHandle(handle.submission_id)

    def status(self, job: JobHandle | str) -> JobStatus:
        return JobStatus(self._connection().status(_job_id(job)).value)

    def logs(self, job: JobHandle | str) -> str:
        return self._connection().logs(_job_id(job))

    def stop(self, job: JobHandle | str) -> bool:
        """Stop the job process; this does not confirm cancellation at a QPU."""
        return self._connection().stop(_job_id(job))

    def delete(self, job: JobHandle | str) -> bool:
        """Delete the record of a terminal job."""
        return self._connection().delete(_job_id(job))

    def __repr__(self) -> str:
        return f"JobClient(address={self._address!r})"


def _job_id(job: JobHandle | str) -> str:
    return JobHandle(job.submission_id if isinstance(job, JobHandle) else job).submission_id


__all__ = ["JobClient", "JobSpec", "JobHandle", "JobStatus", "JobSubmissionError",
           "JobServiceError", "JobStateError"]
