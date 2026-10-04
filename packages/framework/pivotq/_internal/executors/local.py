"""Bounded, no-Ray executor for validating framework call semantics."""

from __future__ import annotations

import time
import socket
from concurrent.futures import (
    CancelledError as FutureCancelledError,
    Future,
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
    wait as wait_futures,
    FIRST_COMPLETED,
)
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import BoundedSemaphore, Event, RLock
from types import TracebackType
from typing import Any
from .base import validate_wait

from pivotq._internal.errors import (
    CancellationError,
    ExecutionError,
    RayQuantumError,
    ResultUnknownError,
    TimeoutError as FrameworkTimeoutError,
    UnavailableError,
    ValidationError,
)
from pivotq._internal.framework.component import (
    validate_component_instance,
    validate_invocation,
)
from pivotq._internal.framework.graph import resolve_result_references
from pivotq._internal.framework.models import (
    ExecutionMode,
    InvocationHandle,
    InvocationResult,
    InvocationSpec,
    InvocationStatus,
)
from pivotq._internal.framework.registry import (
    ComponentRegistration,
    ComponentRegistry,
)
from pivotq._internal.observability.trace import (
    TraceCollector,
    build_trace_record,
    serialized_size,
    utc_now,
)


@dataclass(frozen=True, slots=True)
class _LocalExecutionOutcome:
    result: InvocationResult
    scheduled_at: datetime
    started_at: datetime
    finished_at: datetime
    output_size_bytes: int


@dataclass(slots=True)
class _InvocationEntry:
    invocation: InvocationSpec
    registration: ComponentRegistration
    cancel_requested: Event
    future: Future[_LocalExecutionOutcome] | None = None
    expires_at_monotonic: float | None = None
    result: InvocationResult | None = None
    work_done: bool = False
    capacity_released: bool = False
    submitted_at: datetime | None = None
    input_size_bytes: int = 0
    trace_recorded: bool = False


class LocalExecutor:
    """Execute external Python components in one process.

    A bounded thread pool provides local asynchronous handles without importing
    Ray.  Actor registrations reuse one component instance.  Task registrations
    create, validate, invoke, and close one instance per call.

    Python threads cannot safely terminate an already-running external method.
    A timeout therefore fixes the framework result as ``TIMED_OUT`` and asks
    queued work not to start; already-running code must return before
    ``close()`` can finish.
    """

    def __init__(
        self,
        registry: ComponentRegistry,
        *,
        max_workers: int = 4,
        max_pending: int = 128,
        trace_collector: TraceCollector | None = None,
    ) -> None:
        if not isinstance(registry, ComponentRegistry):
            raise TypeError("registry must be a ComponentRegistry")
        self._registry = registry
        self._max_workers = _require_positive_int(
            "max_workers",
            max_workers,
        )
        self._max_pending = _require_positive_int(
            "max_pending",
            max_pending,
        )
        if trace_collector is not None and not isinstance(
            trace_collector,
            TraceCollector,
        ):
            raise TypeError("trace_collector must be a TraceCollector or None")
        self._trace_collector = trace_collector
        self._pool = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="ray-quantum-local",
        )
        self._pending_capacity = BoundedSemaphore(self._max_pending)
        self._entries: dict[str, _InvocationEntry] = {}
        self._reserved_ids: set[str] = set()
        self._actor_instances: dict[str, object] = {}
        self._component_semaphores: dict[str, BoundedSemaphore] = {}
        self._lock = RLock()
        self._lifecycle_lock = RLock()
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def registry(self) -> ComponentRegistry:
        return self._registry

    def resource_capacities(self) -> tuple[dict[str, float], ...]:
        """LocalExecutor offers CPU threads; it does not allocate accelerators."""
        return ({"CPU": float(self._max_workers)},)

    def submit(self, invocation: InvocationSpec) -> InvocationHandle:
        """Submit an allowed call after all declared dependencies succeed."""

        if not isinstance(invocation, InvocationSpec):
            raise TypeError("invocation must be an InvocationSpec")
        self._ensure_open()
        registration = self._registry.get(invocation.component_id)
        try:
            validate_invocation(registration.spec, invocation)
        except (TypeError, ValueError) as error:
            raise ValidationError(
                str(error),
                framework_job_id=invocation.invocation_id,
            ) from None
        submitted_at = (
            utc_now() if self._trace_collector is not None else None
        )
        input_size_bytes = (
            serialized_size((invocation.args, invocation.kwargs))
            if submitted_at is not None
            else 0
        )

        if not self._pending_capacity.acquire(blocking=False):
            raise UnavailableError(
                "local executor pending capacity is exhausted",
                framework_job_id=invocation.invocation_id,
            )

        stored = False
        try:
            dependencies = self._reserve_invocation(invocation)
            dependency_results, dependency_failure = (
                self._wait_for_dependencies(
                    invocation,
                    dependencies,
                )
            )
            if dependency_failure is not None:
                entry = _InvocationEntry(
                    invocation=invocation,
                    registration=registration,
                    cancel_requested=Event(),
                    result=dependency_failure,
                    work_done=True,
                    capacity_released=True,
                    submitted_at=submitted_at,
                    input_size_bytes=input_size_bytes,
                )
                self._store_entry(invocation.invocation_id, entry)
                stored = True
                self._pending_capacity.release()
                self._record_trace(
                    entry,
                    dependency_failure,
                    finished_at=utc_now(),
                )
                return _handle_for(invocation)

            expires_at = self._calculate_expiration(
                invocation,
                registration,
            )
            if expires_at is not None and expires_at <= time.monotonic():
                entry = _InvocationEntry(
                    invocation=invocation,
                    registration=registration,
                    cancel_requested=Event(),
                    expires_at_monotonic=expires_at,
                    result=_timeout_result(invocation),
                    work_done=True,
                    capacity_released=True,
                    submitted_at=submitted_at,
                    input_size_bytes=input_size_bytes,
                )
                self._store_entry(invocation.invocation_id, entry)
                stored = True
                self._pending_capacity.release()
                self._record_trace(
                    entry,
                    entry.result,
                    finished_at=utc_now(),
                )
                return _handle_for(invocation)

            cancel_requested = Event()
            future = self._pool.submit(
                self._run_invocation,
                registration,
                invocation,
                cancel_requested,
                dependency_results,
            )
            entry = _InvocationEntry(
                invocation=invocation,
                registration=registration,
                cancel_requested=cancel_requested,
                future=future,
                expires_at_monotonic=expires_at,
                submitted_at=submitted_at,
                input_size_bytes=input_size_bytes,
            )
            self._store_entry(invocation.invocation_id, entry)
            stored = True
            future.add_done_callback(
                lambda completed, invocation_id=invocation.invocation_id: (
                    self._complete_future(invocation_id, completed)
                )
            )
            return _handle_for(invocation)
        except RuntimeError:
            raise UnavailableError(
                "local executor is closed",
                framework_job_id=invocation.invocation_id,
            ) from None
        finally:
            with self._lock:
                self._reserved_ids.discard(invocation.invocation_id)
            if not stored:
                self._pending_capacity.release()

    def result(self, handle: InvocationHandle) -> InvocationResult:
        """Resolve a handle, enforcing its invocation deadline/timeout."""

        entry = self._get_entry(handle)
        with self._lock:
            if entry.result is not None:
                return entry.result
            future = entry.future
            expires_at = entry.expires_at_monotonic
        if future is None:
            raise ExecutionError(
                "local invocation has no result or execution future",
                framework_job_id=entry.invocation.invocation_id,
            )

        if future.done():
            self._complete_future(entry.invocation.invocation_id, future)
        else:
            remaining = (
                None
                if expires_at is None
                else max(0.0, expires_at - time.monotonic())
            )
            if remaining == 0.0:
                return self._mark_timed_out(entry, future)
            try:
                future.result(timeout=remaining)
            except FutureTimeoutError:
                return self._mark_timed_out(entry, future)
            except Exception:
                pass
            self._complete_future(entry.invocation.invocation_id, future)

        with self._lock:
            if entry.result is None:
                raise ExecutionError(
                    "local invocation completed without a terminal result",
                    framework_job_id=entry.invocation.invocation_id,
                )
            return entry.result

    def poll(self, handle: InvocationHandle) -> InvocationResult | None:
        """Inspect completion without waiting or cancelling due to a wait timeout."""
        entry = self._get_entry(handle)
        with self._lock:
            if entry.result is not None:
                return entry.result
            future, expiration = entry.future, entry.expires_at_monotonic
        if future is not None and (future.done() or (
                expiration is not None and expiration <= time.monotonic())):
            return self.result(handle)
        return None

    def wait(self, handles: tuple[InvocationHandle, ...], *, num_returns: int = 1,
             timeout: float | None = None) -> tuple[tuple[InvocationHandle, ...], tuple[InvocationHandle, ...]]:
        validate_wait(handles, num_returns, timeout)
        entries = {handle.invocation_id: self._get_entry(handle) for handle in handles}
        deadline = None if timeout is None else time.monotonic() + timeout
        while handles:
            ready = tuple(handle for handle in handles if self.poll(handle) is not None)
            ready_ids = {handle.invocation_id for handle in ready}
            pending = tuple(handle for handle in handles if handle.invocation_id not in ready_ids)
            if len(ready) >= num_returns or not pending:
                return ready, pending
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            if remaining == 0:
                return ready, pending
            expirations = [entries[handle.invocation_id].expires_at_monotonic for handle in pending]
            limits = [max(0.0, expiry - time.monotonic()) for expiry in expirations if expiry is not None]
            if remaining is not None:
                limits.append(remaining)
            futures = [entries[handle.invocation_id].future for handle in pending]
            wait_futures([future for future in futures if future is not None],
                         timeout=min(limits) if limits else None, return_when=FIRST_COMPLETED)
        return (), ()

    def flush_traces(self) -> None:
        """Local workers record their traces on completion."""

    def invoke(self, invocation: InvocationSpec) -> InvocationResult:
        """Submit and synchronously resolve one invocation."""

        return self.result(self.submit(invocation))

    def release(self, handle: InvocationHandle) -> None:
        """Remove a completed result so opaque payload memory can be reclaimed."""

        entry = self._get_entry(handle)
        with self._lock:
            if not entry.work_done:
                raise ValidationError(
                    "cannot release an invocation while work is still running",
                    framework_job_id=entry.invocation.invocation_id,
                )
            self._entries.pop(entry.invocation.invocation_id, None)

    def close(self) -> None:
        """Drain workers, then close all executor-owned Actor instances."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._pool.shutdown(wait=True, cancel_futures=True)

        with self._lifecycle_lock:
            actor_instances = tuple(self._actor_instances.values())
            self._actor_instances.clear()
            self._component_semaphores.clear()

        close_failed = False
        for instance in actor_instances:
            try:
                _close_component(instance)
            except Exception:
                close_failed = True
        if close_failed:
            raise ExecutionError(
                "one or more local Actor components failed to close"
            )

    def __enter__(self) -> LocalExecutor:
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _ensure_open(self) -> None:
        with self._lock:
            if self._closed:
                raise UnavailableError("local executor is closed")

    def _reserve_invocation(
        self,
        invocation: InvocationSpec,
    ) -> tuple[_InvocationEntry, ...]:
        with self._lock:
            if self._closed:
                raise UnavailableError(
                    "local executor is closed",
                    framework_job_id=invocation.invocation_id,
                )
            if (
                invocation.invocation_id in self._entries
                or invocation.invocation_id in self._reserved_ids
            ):
                raise ValidationError(
                    f"invocation {invocation.invocation_id!r} already exists",
                    framework_job_id=invocation.invocation_id,
                )

            dependencies: list[_InvocationEntry] = []
            for dependency_id in invocation.dependencies:
                dependency = self._entries.get(dependency_id)
                if dependency is None:
                    raise ValidationError(
                        f"dependency {dependency_id!r} is not available",
                        framework_job_id=invocation.invocation_id,
                    )
                dependencies.append(dependency)
            self._reserved_ids.add(invocation.invocation_id)
            return tuple(dependencies)

    def _wait_for_dependencies(
        self,
        invocation: InvocationSpec,
        dependencies: tuple[_InvocationEntry, ...],
    ) -> tuple[tuple[InvocationResult, ...], InvocationResult | None]:
        completed: list[InvocationResult] = []
        for dependency in dependencies:
            dependency_result = self.result(
                _handle_for(dependency.invocation)
            )
            if not dependency_result.succeeded:
                return (
                    tuple(completed),
                    InvocationResult(
                        invocation_id=invocation.invocation_id,
                        component_id=invocation.component_id,
                        status=InvocationStatus.FAILED,
                        # Keep the original request/job identity available to
                        # callers who only get the final downstream result.
                        error=dependency_result.error if isinstance(
                            dependency_result.error, ResultUnknownError
                        ) else ExecutionError(
                            "a required dependency did not succeed",
                            framework_job_id=invocation.invocation_id,
                        ),
                    ),
                )
            completed.append(dependency_result)
        return tuple(completed), None

    def _store_entry(
        self,
        invocation_id: str,
        entry: _InvocationEntry,
    ) -> None:
        with self._lock:
            if self._closed:
                if entry.future is not None:
                    entry.cancel_requested.set()
                    entry.future.cancel()
                raise UnavailableError(
                    "local executor is closed",
                    framework_job_id=invocation_id,
                )
            self._entries[invocation_id] = entry

    def _calculate_expiration(
        self,
        invocation: InvocationSpec,
        registration: ComponentRegistration,
    ) -> float | None:
        now_monotonic = time.monotonic()
        candidates: list[float] = []
        if registration.spec.timeout_seconds is not None:
            candidates.append(
                now_monotonic + registration.spec.timeout_seconds
            )
        if invocation.deadline is not None:
            remaining = (
                invocation.deadline - datetime.now(timezone.utc)
            ).total_seconds()
            candidates.append(now_monotonic + max(0.0, remaining))
        return min(candidates) if candidates else None

    def _run_invocation(
        self,
        registration: ComponentRegistration,
        invocation: InvocationSpec,
        cancel_requested: Event,
        dependency_results: tuple[InvocationResult, ...],
    ) -> _LocalExecutionOutcome:
        scheduled_at = utc_now()
        semaphore = self._component_semaphore(registration)
        semaphore.acquire()
        started_at = utc_now()
        instance: object | None = None
        task_instance = registration.spec.execution is ExecutionMode.TASK
        value: Any = None
        failure: RayQuantumError | None = None
        try:
            if cancel_requested.is_set():
                result = _timeout_result(invocation)
                return _local_outcome(
                    result,
                    scheduled_at=scheduled_at,
                    started_at=started_at,
                )
            instance = self._component_instance(registration)
            if cancel_requested.is_set():
                result = _timeout_result(invocation)
                return _local_outcome(
                    result,
                    scheduled_at=scheduled_at,
                    started_at=started_at,
                )
            method = getattr(instance, invocation.method)
            args = resolve_result_references(
                invocation.args,
                dependency_results,
            )
            kwargs = resolve_result_references(
                invocation.kwargs_dict(),
                dependency_results,
            )
            value = method(*args, **kwargs)
        except RayQuantumError as error:
            failure = error
        except Exception as error:
            failure = ExecutionError(
                f"external component raised {type(error).__name__}",
                framework_job_id=invocation.invocation_id,
            )
        finally:
            if task_instance and instance is not None:
                try:
                    _close_component(instance)
                except Exception as error:
                    if failure is None:
                        failure = ExecutionError(
                            f"external component close raised "
                            f"{type(error).__name__}",
                            framework_job_id=invocation.invocation_id,
                        )
            semaphore.release()

        if failure is not None:
            return _local_outcome(
                _failure_result(invocation, failure),
                scheduled_at=scheduled_at,
                started_at=started_at,
            )
        try:
            result = InvocationResult(
                invocation_id=invocation.invocation_id,
                component_id=invocation.component_id,
                status=InvocationStatus.SUCCEEDED,
                value=value,
            )
        except (TypeError, ValueError):
            result = InvocationResult(
                invocation_id=invocation.invocation_id,
                component_id=invocation.component_id,
                status=InvocationStatus.FAILED,
                error=ExecutionError(
                    "external component returned a non-serializable value",
                    framework_job_id=invocation.invocation_id,
                ),
            )
        return _local_outcome(
            result,
            scheduled_at=scheduled_at,
            started_at=started_at,
        )

    def _component_instance(
        self,
        registration: ComponentRegistration,
    ) -> object:
        if registration.spec.execution is ExecutionMode.TASK:
            return _construct_component(registration)

        component_id = registration.spec.component_id
        with self._lifecycle_lock:
            instance = self._actor_instances.get(component_id)
            if instance is None:
                instance = _construct_component(registration)
                self._actor_instances[component_id] = instance
            return instance

    def _component_semaphore(
        self,
        registration: ComponentRegistration,
    ) -> BoundedSemaphore:
        component_id = registration.spec.component_id
        with self._lifecycle_lock:
            semaphore = self._component_semaphores.get(component_id)
            if semaphore is None:
                semaphore = BoundedSemaphore(
                    registration.spec.max_concurrency
                )
                self._component_semaphores[component_id] = semaphore
            return semaphore

    def _get_entry(self, handle: InvocationHandle) -> _InvocationEntry:
        if not isinstance(handle, InvocationHandle):
            raise TypeError("handle must be an InvocationHandle")
        with self._lock:
            entry = self._entries.get(handle.invocation_id)
            if (
                entry is None
                or handle.component_id != entry.invocation.component_id
                or handle.reference != handle.invocation_id
            ):
                raise ValidationError(
                    "invocation handle is not owned by this executor",
                    framework_job_id=handle.invocation_id,
                )
            return entry

    def _mark_timed_out(
        self,
        entry: _InvocationEntry,
        future: Future[InvocationResult],
    ) -> InvocationResult:
        with self._lock:
            if entry.result is None:
                entry.result = _timeout_result(entry.invocation)
                entry.cancel_requested.set()
            result = entry.result
            # Publish the terminal Trace before another result() caller can
            # observe and return the cached result.
            self._record_trace(entry, result, finished_at=utc_now())
        future.cancel()
        return result

    def _complete_future(
        self,
        invocation_id: str,
        future: Future[_LocalExecutionOutcome],
    ) -> None:
        outcome: _LocalExecutionOutcome | None = None
        try:
            outcome = future.result()
            completed_result = outcome.result
        except FutureCancelledError:
            with self._lock:
                entry = self._entries.get(invocation_id)
            if entry is None:
                return
            completed_result = InvocationResult(
                invocation_id=entry.invocation.invocation_id,
                component_id=entry.invocation.component_id,
                status=InvocationStatus.CANCELLED,
                error=CancellationError(
                    "local invocation was cancelled before execution",
                    framework_job_id=entry.invocation.invocation_id,
                ),
            )
        except Exception as error:
            with self._lock:
                entry = self._entries.get(invocation_id)
            if entry is None:
                return
            completed_result = InvocationResult(
                invocation_id=entry.invocation.invocation_id,
                component_id=entry.invocation.component_id,
                status=InvocationStatus.FAILED,
                error=ExecutionError(
                    f"local executor raised {type(error).__name__}",
                    framework_job_id=entry.invocation.invocation_id,
                ),
            )

        release_capacity = False
        final_result: InvocationResult | None = None
        with self._lock:
            entry = self._entries.get(invocation_id)
            if entry is None:
                return
            if entry.result is None:
                entry.result = completed_result
            entry.work_done = True
            if not entry.capacity_released:
                entry.capacity_released = True
                release_capacity = True
            final_result = entry.result
            # Keep result publication and terminal Trace observation ordered.
            # RLock makes the nested _record_trace() lock acquisition safe.
            if final_result is not None:
                if outcome is None:
                    self._record_trace(
                        entry,
                        final_result,
                        finished_at=utc_now(),
                    )
                else:
                    self._record_trace(
                        entry,
                        final_result,
                        scheduled_at=outcome.scheduled_at,
                        started_at=outcome.started_at,
                        finished_at=outcome.finished_at,
                        output_size_bytes=outcome.output_size_bytes,
                    )
        if release_capacity:
            self._pending_capacity.release()

    def _record_trace(
        self,
        entry: _InvocationEntry,
        result: InvocationResult,
        *,
        scheduled_at: datetime | None = None,
        started_at: datetime | None = None,
        finished_at: datetime,
        output_size_bytes: int | None = None,
    ) -> None:
        collector = self._trace_collector
        submitted_at = entry.submitted_at
        if collector is None or submitted_at is None:
            return
        with self._lock:
            if entry.trace_recorded:
                return
            entry.trace_recorded = True
        try:
            collector.record(
                build_trace_record(
                    entry.invocation,
                    entry.registration.spec,
                    result,
                    backend="local",
                    submitted_at=submitted_at,
                    scheduled_at=scheduled_at,
                    started_at=started_at,
                    finished_at=finished_at,
                    result_observed_at=utc_now(),
                    node_id=socket.gethostname(),
                    input_size_bytes=entry.input_size_bytes,
                    output_size_bytes=output_size_bytes,
                )
            )
        except Exception:
            # Observability is fail-open and must not change invocation results.
            pass


def _handle_for(invocation: InvocationSpec) -> InvocationHandle:
    return InvocationHandle(
        invocation_id=invocation.invocation_id,
        component_id=invocation.component_id,
        reference=invocation.invocation_id,
    )


def _local_outcome(
    result: InvocationResult,
    *,
    scheduled_at: datetime,
    started_at: datetime,
) -> _LocalExecutionOutcome:
    return _LocalExecutionOutcome(
        result=result,
        scheduled_at=scheduled_at,
        started_at=started_at,
        finished_at=utc_now(),
        output_size_bytes=(
            serialized_size(result.value) if result.succeeded else 0
        ),
    )


def _timeout_result(invocation: InvocationSpec) -> InvocationResult:
    return InvocationResult(
        invocation_id=invocation.invocation_id,
        component_id=invocation.component_id,
        status=InvocationStatus.TIMED_OUT,
        error=FrameworkTimeoutError(
            "local invocation exceeded its deadline or timeout",
            framework_job_id=invocation.invocation_id,
        ),
    )


def _failure_result(
    invocation: InvocationSpec,
    error: RayQuantumError,
) -> InvocationResult:
    if isinstance(error, FrameworkTimeoutError):
        status = InvocationStatus.TIMED_OUT
    elif isinstance(error, CancellationError):
        status = InvocationStatus.CANCELLED
    else:
        status = InvocationStatus.FAILED
    return InvocationResult(
        invocation_id=invocation.invocation_id,
        component_id=invocation.component_id,
        status=status,
        error=error,
    )


def _close_component(instance: object) -> None:
    close = getattr(instance, "close", None)
    if callable(close):
        close()


def _construct_component(
    registration: ComponentRegistration,
) -> object:
    instance = registration.factory()
    try:
        return validate_component_instance(registration.spec, instance)
    except Exception:
        try:
            _close_component(instance)
        except Exception:
            pass
        raise


def _require_positive_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


__all__ = ["LocalExecutor"]
