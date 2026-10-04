"""Safe, narrow wrapper around Ray 2.31.0 ``JobSubmissionClient``."""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit

from pivotq._internal.errors import SubmissionDisposition

from .errors import RayJobServiceError, RayJobStateError, RayJobSubmissionError
from .models import RayJobHandle, RayJobSpec, RayJobStatus


class JobSubmissionClientProtocol(Protocol):
    """Structural subset used by ``RayJobClient`` and unit-test stubs."""

    def submit_job(self, **kwargs: Any) -> str: ...

    def get_job_status(self, job_id: str) -> object: ...

    def get_job_logs(self, job_id: str) -> str: ...

    def stop_job(self, job_id: str) -> bool: ...

    def delete_job(self, job_id: str) -> bool: ...


ClientFactory = Callable[..., JobSubmissionClientProtocol]
_HTTP_FIELD_NAME_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_PRIVATE_ADDRESS_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "fc00::/7",
        "fe80::/10",
    )
)


class RayJobClient:
    """Submit and manage whole applications without starting a local Ray runtime.

    HTTP is accepted only for loopback/private addresses.  Public endpoints must
    use HTTPS with certificate verification.  Headers and cookies are passed to
    Ray's client but never exposed by this wrapper's representation or errors.
    """

    def __init__(
        self,
        address: str,
        *,
        headers: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        verify: bool | str = True,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._address = _require_safe_jobs_address(address)
        normalized_headers = _copy_string_mapping("headers", headers)
        normalized_cookies = _copy_string_mapping("cookies", cookies)
        normalized_verify = _require_tls_verification(verify)

        try:
            factory = client_factory or _load_job_submission_client()
            self._client = factory(
                self._address,
                headers=normalized_headers or None,
                cookies=normalized_cookies or None,
                verify=normalized_verify,
            )
        except RayJobServiceError:
            raise
        except Exception:
            raise RayJobServiceError(
                "Ray Jobs client initialization failed"
            ) from None

    def submit(self, spec: RayJobSpec) -> RayJobHandle:
        """Submit exactly one application and return its stable Job handle."""

        if not isinstance(spec, RayJobSpec):
            raise TypeError("spec must be a RayJobSpec")
        submit_arguments = {
            "entrypoint": spec.entrypoint,
            "submission_id": spec.submission_id,
            "runtime_env": spec.runtime_environment.as_ray_dict(),
            "metadata": spec.metadata_dict(),
        }
        submit_arguments.update(spec.driver_resources.as_submit_arguments())

        try:
            returned_id = self._client.submit_job(**submit_arguments)
        except Exception:
            raise RayJobSubmissionError(
                "Ray Job submission failed; reconcile the submission ID before retry",
                disposition=SubmissionDisposition.UNKNOWN,
            ) from None

        try:
            handle = RayJobHandle(returned_id)
        except (TypeError, ValueError):
            raise RayJobServiceError(
                "Ray Jobs service returned an invalid submission ID"
            ) from None
        if handle.submission_id != spec.submission_id:
            raise RayJobServiceError(
                "Ray Jobs service returned an unexpected submission ID"
            )
        return handle

    def status(self, job: RayJobHandle | str) -> RayJobStatus:
        submission_id = _submission_id(job)
        try:
            raw_status = self._client.get_job_status(submission_id)
        except Exception:
            raise RayJobServiceError("Ray Job status request failed") from None
        value = getattr(raw_status, "value", raw_status)
        if not isinstance(value, str):
            raise RayJobServiceError("Ray Jobs service returned an invalid status")
        try:
            return RayJobStatus(value.lower())
        except ValueError:
            raise RayJobServiceError("Ray Jobs service returned an unknown status") from None

    def logs(self, job: RayJobHandle | str) -> str:
        submission_id = _submission_id(job)
        try:
            logs = self._client.get_job_logs(submission_id)
        except Exception:
            raise RayJobServiceError("Ray Job logs request failed") from None
        if not isinstance(logs, str):
            raise RayJobServiceError("Ray Jobs service returned invalid logs")
        return logs

    def stop(self, job: RayJobHandle | str) -> bool:
        """Request Job-process termination; this is not QPU cancellation."""

        submission_id = _submission_id(job)
        try:
            stopped = self._client.stop_job(submission_id)
        except Exception:
            raise RayJobServiceError("Ray Job stop request failed") from None
        if not isinstance(stopped, bool):
            raise RayJobServiceError("Ray Jobs service returned an invalid stop result")
        return stopped

    def delete(self, job: RayJobHandle | str) -> bool:
        """Delete Jobs service metadata only after observing a terminal state."""

        submission_id = _submission_id(job)
        observed_status = self.status(submission_id)
        if not observed_status.is_terminal:
            raise RayJobStateError(
                "Ray Job metadata can be deleted only after a terminal state"
            )
        try:
            deleted = self._client.delete_job(submission_id)
        except Exception:
            raise RayJobServiceError("Ray Job delete request failed") from None
        if not isinstance(deleted, bool):
            raise RayJobServiceError("Ray Jobs service returned an invalid delete result")
        return deleted

    def __repr__(self) -> str:
        return f"RayJobClient(address={self._address!r})"


def _load_job_submission_client() -> ClientFactory:
    try:
        from ray.job_submission import JobSubmissionClient
    except (ImportError, ModuleNotFoundError):
        raise RayJobServiceError(
            "Ray Jobs client requires the pinned ray[default] dependency"
        ) from None
    return JobSubmissionClient


def _submission_id(job: RayJobHandle | str) -> str:
    if isinstance(job, RayJobHandle):
        return job.submission_id
    return RayJobHandle(job).submission_id


def _require_safe_jobs_address(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("address must be a string")
    if not value or value != value.strip():
        raise ValueError("address must be non-empty without surrounding whitespace")
    if any(character in value for character in ("\x00", "\r", "\n", "\t")):
        raise ValueError("address must not contain control characters")
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("address must use http or https")
    if parsed.hostname is None or parsed.path not in {"", "/"}:
        raise ValueError("address must contain only the Jobs service origin")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("address must not contain credentials")
    if "?" in value or "#" in value:
        raise ValueError("address must not contain query or fragment")
    try:
        parsed_port = parsed.port
    except ValueError:
        raise ValueError("address contains an invalid port") from None
    if parsed_port is None or parsed_port == 0:
        raise ValueError("address must include a non-zero Jobs service port")
    if scheme == "http" and not _is_loopback_or_private(parsed.hostname):
        raise ValueError(
            "public Ray Jobs endpoints must use HTTPS; use a private address "
            "or a loopback SSH/VPN tunnel for HTTP"
        )
    return value.rstrip("/")


def _is_loopback_or_private(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return address.is_loopback or any(
        address.version == network.version and address in network
        for network in _PRIVATE_ADDRESS_NETWORKS
    )


def _require_tls_verification(value: object) -> bool | str:
    if value is True:
        return True
    if (
        isinstance(value, str)
        and value
        and value == value.strip()
        and not any(character in value for character in ("\x00", "\r", "\n", "\t"))
    ):
        return value
    raise ValueError("verify must be True or a non-empty CA bundle path")


def _copy_string_mapping(
    name: str,
    values: Mapping[str, str] | None,
) -> dict[str, str]:
    if values is None:
        return {}
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    copied: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(key, str):
            raise TypeError(f"{name} keys must be strings")
        if _HTTP_FIELD_NAME_PATTERN.fullmatch(key) is None:
            raise ValueError(f"{name} keys must be valid HTTP field names")
        if not isinstance(value, str):
            raise TypeError(f"{name} values must be strings")
        if any(character in value for character in ("\x00", "\r", "\n")):
            raise ValueError(f"{name} values must not contain control characters")
        copied[key] = value
    return copied


__all__ = ["JobSubmissionClientProtocol", "RayJobClient"]
