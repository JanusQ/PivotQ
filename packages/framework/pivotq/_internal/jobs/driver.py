"""Cluster-side Driver bootstrap for one Ray Jobs application.

The bootstrap owns only the Ray connection it creates.  It constructs the
existing Registry -> RayExecutor -> FusionFramework stack, calls application-
provided registration and runner functions in the Driver process, and closes
owned resources in reverse order.  It does not contain application algorithms.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import signal
import sys
from threading import Event, current_thread, main_thread
from typing import Callable, Iterable, Protocol

from pivotq._internal.framework import ComponentRegistry, FusionFramework
from pivotq._internal.executors.cleanup import ExecutorCleanupError, ExecutorCleanupReport, error_type
from pivotq._internal.observability import TraceCollector, TraceEventJournalConfig


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_TARGET_PATTERN = re.compile(
    r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$"
)


class RayJobDriverStatus(str, Enum):
    """Terminal status written by the Driver, not the Ray Jobs state."""

    STARTING = "starting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOP_REQUESTED = "stop_requested"


@dataclass(frozen=True, slots=True, repr=False)
class RayJobDriverConfig:
    """Validated, non-business configuration for one cluster-side Driver."""

    run_id: str
    registration_target: str
    runner_target: str
    namespace: str
    output_dir: str | os.PathLike[str]
    ray_address: str = "auto"
    actor_close_timeout_seconds: float = 5.0
    log_to_driver: bool = False
    schema_version: int = 1
    trace_max_records: int | None = None
    trace_event_max_records: int | None = None
    simulation: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _require_identifier("run_id", self.run_id))
        object.__setattr__(
            self,
            "registration_target",
            _require_import_target("registration_target", self.registration_target),
        )
        object.__setattr__(
            self,
            "runner_target",
            _require_import_target("runner_target", self.runner_target),
        )
        object.__setattr__(self, "namespace", _require_identifier("namespace", self.namespace))
        object.__setattr__(self, "output_dir", _require_absolute_directory(self.output_dir))
        if self.ray_address != "auto":
            raise ValueError("P7.2 Driver ray_address must be 'auto'")
        object.__setattr__(
            self,
            "actor_close_timeout_seconds",
            _require_positive_number(
                "actor_close_timeout_seconds",
                self.actor_close_timeout_seconds,
            ),
        )
        object.__setattr__(
            self,
            "trace_max_records",
            _require_optional_positive_integer(
                "trace_max_records",
                self.trace_max_records,
            ),
        )
        object.__setattr__(
            self,
            "trace_event_max_records",
            _require_optional_positive_integer(
                "trace_event_max_records",
                self.trace_event_max_records,
            ),
        )
        if not isinstance(self.log_to_driver, bool):
            raise TypeError("log_to_driver must be a bool")
        if type(self.simulation) is not bool:
            raise TypeError("simulation must be a bool")
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int):
            raise TypeError("schema_version must be an integer")
        if self.schema_version != 1:
            raise ValueError("only schema_version 1 is supported")

    @property
    def manifest_path(self) -> Path:
        return Path(self.output_dir) / f"{self.run_id}.manifest.json"

    @property
    def trace_event_path(self) -> Path:
        return Path(self.output_dir) / f"{self.run_id}.trace-v2.jsonl"

    @property
    def trace_event_manifest_path(self) -> Path:
        return Path(self.output_dir) / f"{self.run_id}.trace-v2.manifest.json"

    def __repr__(self) -> str:
        return (
            "RayJobDriverConfig("
            f"run_id={self.run_id!r}, "
            f"namespace={self.namespace!r}, "
            f"output_dir={self.output_dir!r}, "
            "registration_target=<redacted>, "
            "runner_target=<redacted>, "
            f"ray_address={self.ray_address!r}, "
            f"actor_close_timeout_seconds={self.actor_close_timeout_seconds!r}, "
            f"trace_max_records={self.trace_max_records!r}, "
            f"trace_event_max_records={self.trace_event_max_records!r}, "
            f"log_to_driver={self.log_to_driver!r}, "
            f"simulation={self.simulation!r}, "
            f"schema_version={self.schema_version})"
        )


@dataclass(frozen=True, slots=True)
class RayJobDriverManifest:
    """Payload-free audit record for Driver outcome and owned-resource cleanup."""

    run_id: str
    status: RayJobDriverStatus
    exit_code: int | None
    started_at: str
    finished_at: str | None
    namespace: str
    process_id: int
    framework_closed: bool
    registry_closed: bool
    ray_disconnected: bool
    cleanup_succeeded: bool
    failure_type: str | None = None
    schema_version: int = 2
    ray_connection_owned: bool = False
    cleanup_outcome: str = "pending"
    actor_cleanup: ExecutorCleanupReport = field(default_factory=ExecutorCleanupReport)
    runtime_execution: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "status": self.status.value,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "namespace": self.namespace,
            "process_id": self.process_id,
            "cleanup": {
                "framework_closed": self.framework_closed,
                "registry_closed": self.registry_closed,
                "ray_connection_owned": self.ray_connection_owned,
                "ray_disconnected": self.ray_disconnected,
                "succeeded": self.cleanup_succeeded,
                "outcome": self.cleanup_outcome,
                "actor_cleanup": self.actor_cleanup.as_dict(),
            },
            "failure_type": self.failure_type,
            **({"runtime_execution": self.runtime_execution}
               if self.runtime_execution is not None else {}),
        }


class RayJobDriverContext:
    """Non-business context visible to the external runner."""

    __slots__ = ("_output_dir", "_run_id", "_stop_event", "_trace_collector")

    def __init__(
        self,
        run_id: str,
        output_dir: Path,
        trace_collector: TraceCollector | None = None,
    ) -> None:
        self._run_id = run_id
        self._output_dir = output_dir
        self._stop_event = Event()
        self._trace_collector = trace_collector

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    @property
    def trace_collector(self) -> TraceCollector | None:
        """Return the optional Driver-owned collector for runner audit output."""

        return self._trace_collector

    def raise_if_stop_requested(self) -> None:
        """Let cooperative runners stop promptly after a service stop request."""

        if self.stop_requested:
            raise _DriverStopRequested()

    def _request_stop(self) -> None:
        self._stop_event.set()


class _RayModule(Protocol):
    def is_initialized(self) -> bool: ...

    def init(self, **kwargs: object) -> object: ...

    def shutdown(self) -> None: ...

    def get_runtime_context(self) -> object: ...


class _DriverStopRequested(BaseException):
    pass


def run_driver(config: RayJobDriverConfig) -> RayJobDriverManifest:
    """Run one injected application and always attempt owned-resource cleanup."""

    if not isinstance(config, RayJobDriverConfig):
        raise TypeError("config must be a RayJobDriverConfig")

    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_collector = (
        None
        if config.trace_max_records is None
        else TraceCollector(max_records=config.trace_max_records)
    )
    trace_event_journal = (
        None
        if config.trace_event_max_records is None
        else TraceEventJournalConfig(
            run_id=config.run_id,
            event_path=config.trace_event_path,
            manifest_path=config.trace_event_manifest_path,
            max_records=config.trace_event_max_records,
        )
    )
    context = RayJobDriverContext(
        config.run_id,
        output_dir,
        trace_collector=trace_collector,
    )
    started_at = _utc_text()
    starting_manifest = _manifest(
        config,
        status=RayJobDriverStatus.STARTING,
        exit_code=None,
        started_at=started_at,
        cleanup_succeeded=False,
    )
    _write_initial_manifest(config.manifest_path, starting_manifest)

    ray_module: _RayModule | None = None
    registry: ComponentRegistry | None = None
    executor: object | None = None
    framework: FusionFramework | None = None
    owns_ray_connection = False
    framework_closed = False
    registry_closed = False
    ray_disconnected = False
    cleanup_succeeded = True
    actor_cleanup = ExecutorCleanupReport()
    failure_type: str | None = None
    status = RayJobDriverStatus.FAILED
    exit_code = 1
    begin_cleanup: Callable[[], None] = lambda: None

    # Restore the prior Ray/OS handlers only after cleanup and manifest publication.
    with ExitStack() as signal_scope:
        try:
            registration = _load_callable(config.registration_target, positional_count=1)
            runner = _load_callable(config.runner_target, positional_count=2)
            ray_module = _load_ray_module()
            if ray_module.is_initialized():
                _require_current_namespace(ray_module, config.namespace)
            else:
                ray_module.init(
                    address=config.ray_address,
                    namespace=config.namespace,
                    log_to_driver=config.log_to_driver,
                )
                owns_ray_connection = True
            begin_cleanup = _install_stop_signal_handlers(context, signal_scope)

            registry = ComponentRegistry()
            executor_type = _load_ray_executor()
            executor_options: dict[str, object] = {
                "actor_namespace": config.namespace,
                "actor_close_timeout_seconds": config.actor_close_timeout_seconds,
            }
            if trace_collector is not None:
                executor_options["trace_collector"] = trace_collector
            if trace_event_journal is not None:
                executor_options["trace_event_journal"] = trace_event_journal
            executor = executor_type(registry, **executor_options)
            framework = (FusionFramework(executor, simulation=True)
                         if config.simulation else FusionFramework(executor))
            context.raise_if_stop_requested()
            registration_result = registration(framework)
            if registration_result is not None:
                raise TypeError("registration callable must return None")
            context.raise_if_stop_requested()
            runner_result = runner(framework, context)
            if runner_result is not None:
                raise TypeError("runner callable must return None")
            context.raise_if_stop_requested()
            status = RayJobDriverStatus.SUCCEEDED
            exit_code = 0
        except _DriverStopRequested:
            status = RayJobDriverStatus.STOP_REQUESTED
            exit_code = 143
        except BaseException as error:
            failure_type = error_type(error)
            status = RayJobDriverStatus.FAILED
            exit_code = 1
        finally:
            begin_cleanup()
            if framework is not None:
                try:
                    framework.close()
                except ExecutorCleanupError as error:
                    # A timeout report may be an external-verification candidate;
                    # any other close failure remains an independent hard failure.
                    if error.cleanup_report.outcome != "fallback_pending_verification":
                        cleanup_succeeded = False
                        _report_cleanup_error("framework_close", error_type(error))
                except BaseException as error:
                    cleanup_succeeded = False
                    _report_cleanup_error("framework_close", error_type(error))
                finally:
                    framework_closed = framework.closed
            elif executor is not None:
                try:
                    getattr(executor, "close")()
                except BaseException as error:
                    cleanup_succeeded = False
                    _report_cleanup_error("executor_close", error_type(error))
            if executor is not None:
                candidate = getattr(executor, "cleanup_report", None)
                if isinstance(candidate, ExecutorCleanupReport):
                    actor_cleanup = candidate
                if not actor_cleanup.records_complete:
                    _report_cleanup_error("executor_report", "IncompleteCleanupReport")
            if registry is not None:
                try:
                    registry.close()
                except BaseException as error:
                    cleanup_succeeded = False
                    _report_cleanup_error("registry_close", error_type(error))
                finally:
                    registry_closed = registry.closed
            if owns_ray_connection and ray_module is not None:
                try:
                    ray_module.shutdown()
                    ray_disconnected = True
                except BaseException as error:
                    cleanup_succeeded = False
                    _report_cleanup_error("ray_shutdown", error_type(error))

        if context.stop_requested and status is RayJobDriverStatus.SUCCEEDED:
            status = RayJobDriverStatus.STOP_REQUESTED
            exit_code = 143

        cleanup_outcome = actor_cleanup.outcome
        if (
            not cleanup_succeeded
            or not framework_closed
            or not registry_closed
            or (owns_ray_connection and not ray_disconnected)
            or (cleanup_outcome == "fallback_pending_verification" and not owns_ray_connection)
        ):
            cleanup_outcome = "failed"
        cleanup_succeeded = cleanup_outcome == "clean"

        if not cleanup_succeeded and status is RayJobDriverStatus.SUCCEEDED:
            status = RayJobDriverStatus.FAILED
            exit_code = 1
            failure_type = "DriverCleanupError"

        manifest = _manifest(
            config,
            status=status,
            exit_code=exit_code,
            started_at=started_at,
            finished_at=_utc_text(),
            framework_closed=framework_closed,
            registry_closed=registry_closed,
            ray_disconnected=ray_disconnected,
            cleanup_succeeded=cleanup_succeeded,
            ray_connection_owned=owns_ray_connection,
            cleanup_outcome=cleanup_outcome,
            actor_cleanup=actor_cleanup,
            failure_type=failure_type,
            runtime_execution=(framework.execution_report()
                               if config.simulation and framework is not None else None),
        )
        _replace_manifest(config.manifest_path, manifest)
        return manifest


def main(argv: Iterable[str] | None = None) -> int:
    """CLI entrypoint used by a Ray Job command."""

    parser = _argument_parser()
    try:
        arguments = parser.parse_args(list(argv) if argv is not None else None)
        config = RayJobDriverConfig(
            run_id=arguments.run_id,
            registration_target=arguments.registration,
            runner_target=arguments.runner,
            namespace=arguments.namespace,
            output_dir=arguments.output_dir,
            actor_close_timeout_seconds=arguments.actor_close_timeout,
            trace_max_records=arguments.trace_max_records,
            trace_event_max_records=arguments.trace_event_max_records,
            log_to_driver=arguments.log_to_driver,
            simulation=arguments.simulation,
        )
        manifest = run_driver(config)
    except (TypeError, ValueError, OSError) as error:
        print(
            f"PivotQ Driver configuration failed: {type(error).__name__}",
            file=sys.stderr,
        )
        return 2
    print(f"RAY_QUANTUM_DRIVER_STATUS={manifest.status.value}")
    return manifest.exit_code or 0


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pivotq.jobs.driver",
        description="Run one externally provided application inside a Ray Job Driver.",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--runner", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--actor-close-timeout", type=float, default=5.0)
    parser.add_argument("--trace-max-records", type=int)
    parser.add_argument("--trace-event-max-records", type=int)
    parser.add_argument("--log-to-driver", action="store_true")
    parser.add_argument("--simulation", action="store_true",
                        help="Use registered CPU substitutes for unavailable hardware")
    return parser


def _load_callable(target: str, *, positional_count: int) -> Callable[..., object]:
    module_name, attribute_path = target.split(":", 1)
    value: object = importlib.import_module(module_name)
    for attribute in attribute_path.split("."):
        value = getattr(value, attribute)
    if not callable(value):
        raise TypeError("Driver import target must resolve to a callable")
    try:
        inspect.signature(value).bind(*([object()] * positional_count))
    except (TypeError, ValueError):
        raise TypeError(
            f"Driver callable must accept {positional_count} positional argument(s)"
        ) from None
    return value


def _load_ray_module() -> _RayModule:
    try:
        import ray
    except (ImportError, ModuleNotFoundError):
        raise RuntimeError("Ray Driver bootstrap requires ray[default]") from None
    return ray


def _load_ray_executor() -> type:
    from pivotq._internal.executors import RayExecutor

    return RayExecutor


def _require_current_namespace(ray_module: _RayModule, expected: str) -> None:
    try:
        current = getattr(ray_module.get_runtime_context(), "namespace")
    except BaseException:
        raise RuntimeError("cannot verify the existing Ray namespace") from None
    if current != expected:
        raise RuntimeError("existing Ray runtime uses a different namespace")


def _report_cleanup_error(phase: str, type_name: str) -> None:
    """Record fixed cleanup phases and bounded type names, never error payloads."""
    _write_driver_diagnostic(
        "CLEANUP_ERROR", {"phase": phase, "error_type": type_name},
    )


def _write_driver_diagnostic(kind: str, fields: dict[str, str | int]) -> None:
    diagnostic = json.dumps(fields, separators=(",", ":"))
    try:
        print(f"RAY_QUANTUM_DRIVER_{kind}={diagnostic}", file=sys.stderr)
    except (OSError, ValueError):
        pass  # A closed log stream must not interrupt the remaining cleanup.


def _install_stop_signal_handlers(
    context: RayJobDriverContext,
    signal_scope: ExitStack,
) -> Callable[[], None]:
    if current_thread() is not main_thread():
        return lambda: None
    previous: dict[int, object] = {}
    interruptible = True
    signal_seen = False
    received = 0
    during_cleanup = 0

    def request_stop(signum: int, frame: object) -> None:
        nonlocal signal_seen, received, during_cleanup
        del signum, frame
        received += 1
        if not interruptible:
            during_cleanup += 1
        # Set this before Event.set(), so a reentrant signal cannot interrupt
        # cleanup or reenter the Event's non-reentrant condition lock.
        if signal_seen:
            return
        signal_seen = True
        context._request_stop()
        if interruptible:
            raise _DriverStopRequested()

    def begin_cleanup() -> None:
        nonlocal interruptible
        interruptible = False

    def restore() -> None:
        for signal_number, handler in previous.items():
            signal.signal(signal_number, handler)
        if previous and received:
            _write_driver_diagnostic(
                "STOP_SIGNALS", {"received": received, "during_cleanup": during_cleanup},
            )
        previous.clear()

    # Register restoration before installing any callback: a signal can arrive
    # during installation or between this function returning and assignment.
    signal_scope.callback(restore)
    try:
        for signal_number in (signal.SIGTERM, signal.SIGINT):
            previous[signal_number] = signal.getsignal(signal_number)
            signal.signal(signal_number, request_stop)
    except BaseException:
        restore()
        raise

    return begin_cleanup


def _manifest(
    config: RayJobDriverConfig,
    *,
    status: RayJobDriverStatus,
    exit_code: int | None,
    started_at: str,
    finished_at: str | None = None,
    framework_closed: bool = False,
    registry_closed: bool = False,
    ray_disconnected: bool = False,
    cleanup_succeeded: bool = True,
    failure_type: str | None = None,
    ray_connection_owned: bool = False,
    cleanup_outcome: str = "pending",
    actor_cleanup: ExecutorCleanupReport | None = None,
    runtime_execution: dict[str, object] | None = None,
) -> RayJobDriverManifest:
    manifest = RayJobDriverManifest(
        run_id=config.run_id,
        status=status,
        exit_code=exit_code,
        started_at=started_at,
        finished_at=finished_at,
        namespace=config.namespace,
        process_id=os.getpid(),
        framework_closed=framework_closed,
        registry_closed=registry_closed,
        ray_disconnected=ray_disconnected,
        cleanup_succeeded=cleanup_succeeded,
        failure_type=failure_type,
        ray_connection_owned=ray_connection_owned,
        cleanup_outcome=cleanup_outcome,
        actor_cleanup=actor_cleanup or ExecutorCleanupReport(),
        runtime_execution=(runtime_execution or {"simulation_enabled": True, "selections": []}
                           if config.simulation else None),
    )
    if len(_manifest_bytes(manifest)) > 64 * 1024:
        manifest = replace(
            manifest,
            actor_cleanup=ExecutorCleanupReport(),
            runtime_execution=({"simulation_enabled": True, "selections": [], "truncated": True}
                               if config.simulation else None),
            cleanup_outcome="failed",
            cleanup_succeeded=False,
            status=(RayJobDriverStatus.FAILED if status is RayJobDriverStatus.SUCCEEDED else status),
            exit_code=(1 if status is RayJobDriverStatus.SUCCEEDED else exit_code),
            failure_type=("DriverCleanupError" if status is RayJobDriverStatus.SUCCEEDED else failure_type),
        )
    return manifest


def _manifest_bytes(manifest: RayJobDriverManifest) -> bytes:
    return (json.dumps(manifest.as_dict(), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write_initial_manifest(path: Path, manifest: RayJobDriverManifest) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.initial.tmp")
    created = False
    try:
        with temporary.open("xb") as stream:
            created = True
            stream.write(_manifest_bytes(manifest))
            stream.flush()
            os.fsync(stream.fileno())
        # An exclusive hard link publishes complete bytes and never overwrites
        # an existing run, unlike os.replace on the initial manifest.
        os.link(temporary, path)
    except FileExistsError:
        raise ValueError("Driver manifest already exists for this run ID") from None
    finally:
        if created:
            temporary.unlink(missing_ok=True)


def _replace_manifest(path: Path, manifest: RayJobDriverManifest) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    created = False
    try:
        with temporary.open("xb") as stream:
            created = True
            stream.write(_manifest_bytes(manifest))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            if created:
                temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _require_identifier(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a stable identifier of at most 128 characters")
    return value


def _require_import_target(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if len(value) > 512 or _TARGET_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must use the form 'package.module:callable'")
    return value


def _require_absolute_directory(value: object) -> str:
    try:
        path = Path(value)  # type: ignore[arg-type]
    except TypeError:
        raise TypeError("output_dir must be a path") from None
    if "\x00" in str(path):
        raise ValueError("output_dir must not contain NUL")
    if not path.is_absolute():
        raise ValueError("output_dir must be absolute persistent storage")
    return str(path.resolve(strict=False))


def _require_positive_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    normalized = float(value)
    if normalized <= 0 or normalized == float("inf") or normalized != normalized:
        raise ValueError(f"{name} must be finite and greater than zero")
    return normalized


def _require_optional_positive_integer(
    name: str,
    value: object,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer or None")
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _utc_text() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RayJobDriverConfig",
    "RayJobDriverContext",
    "RayJobDriverManifest",
    "RayJobDriverStatus",
    "main",
    "run_driver",
]
