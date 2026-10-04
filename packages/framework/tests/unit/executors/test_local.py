"""Unit tests for the bounded no-Ray LocalExecutor."""

from __future__ import annotations

import importlib
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

from tests.contract.executor_contract import ExecutorContractMixin
from pivotq._internal.errors import (
    ExecutionError,
    TimeoutError as FrameworkTimeoutError,
    UnavailableError,
    ValidationError,
)
from pivotq._internal.executors import Executor, LocalExecutor
from pivotq._internal.framework import (
    ComponentRegistry,
    ComponentSpec,
    ExecutionMode,
    InvocationHandle,
    InvocationSpec,
    InvocationStatus,
    ResourceRequest,
)
from pivotq._internal.observability import TraceCollector, TraceRecord
from tests.fixtures.fake_components import (
    BlockingFakeComponent,
    FailingFakeComponent,
    FakeClassicalComponent,
    FakeForceComponent,
    FakeMarker,
    FakeQuantumComponent,
    InvalidFakeComponent,
    RecordingFakeComponent,
    RuntimeProbeComponent,
    call_log,
    identity_energy,
    reset_all_fakes,
)


class _BlockingTraceCollector(TraceCollector):
    def __init__(self) -> None:
        super().__init__()
        self.record_started = threading.Event()
        self.release_record = threading.Event()

    def record(self, trace: TraceRecord) -> None:
        self.record_started.set()
        if not self.release_record.wait(timeout=2.0):
            raise RuntimeError("test did not release trace recording")
        super().record(trace)


def _spec(
    component_id: str,
    *,
    execution: ExecutionMode,
    allowed_methods: tuple[str, ...],
    timeout_seconds: float | None = None,
    max_concurrency: int = 1,
) -> ComponentSpec:
    return ComponentSpec(
        component_id=component_id,
        execution=execution,
        resources=ResourceRequest(),
        allowed_methods=allowed_methods,
        stateful=execution is ExecutionMode.ACTOR,
        timeout_seconds=timeout_seconds,
        max_concurrency=max_concurrency,
    )


def _invocation(
    invocation_id: str,
    component_id: str,
    method: str,
    *,
    args: tuple[Any, ...] = (),
    dependencies: tuple[str, ...] = (),
) -> InvocationSpec:
    return InvocationSpec(
        invocation_id=invocation_id,
        component_id=component_id,
        method=method,
        args=args,
        dependencies=dependencies,
    )


class LocalExecutorTest(ExecutorContractMixin, unittest.TestCase):
    def setUp(self) -> None:
        reset_all_fakes()
        self.registry = ComponentRegistry()
        self.executor = LocalExecutor(
            self.registry,
            max_workers=4,
            max_pending=16,
        )

    def test_terminal_result_is_not_visible_before_trace_record(self) -> None:
        collector = _BlockingTraceCollector()
        executor = LocalExecutor(
            self.registry,
            max_workers=1,
            max_pending=2,
            trace_collector=collector,
        )
        self.registry.register(
            _spec(
                "trace-order",
                execution=ExecutionMode.TASK,
                allowed_methods=("describe", "sleep"),
            ),
            RuntimeProbeComponent,
        )
        handle = executor.submit(
            _invocation(
                "trace-order-invocation",
                "trace-order",
                "sleep",
                args=(0.05,),
            )
        )
        self.assertTrue(collector.record_started.wait(timeout=1.0))

        result_observed = threading.Event()

        def resolve() -> None:
            executor.result(handle)
            result_observed.set()

        observer = threading.Thread(target=resolve)
        observer.start()
        try:
            self.assertFalse(
                result_observed.wait(timeout=0.1),
                "result() returned before terminal Trace recording completed",
            )
        finally:
            collector.release_record.set()
            observer.join(timeout=2.0)
            executor.close()

        self.assertFalse(observer.is_alive())
        self.assertTrue(result_observed.is_set())
        self.assertEqual(len(collector.snapshot()), 1)

    def tearDown(self) -> None:
        BlockingFakeComponent.release.set()
        self.executor.close()
        self.registry.close()

    def test_executor_implements_shared_contract(self) -> None:
        self.assertIsInstance(self.executor, Executor)
        self.assertFalse(self.executor.closed)

    def test_all_screenshot_methods_can_be_invoked_without_algorithms(self) -> None:
        self.registry.register(
            _spec(
                "quantum",
                execution=ExecutionMode.ACTOR,
                allowed_methods=("describe", "extract_features"),
            ),
            FakeQuantumComponent,
        )
        self.registry.register(
            _spec(
                "classical",
                execution=ExecutionMode.ACTOR,
                allowed_methods=(
                    "describe",
                    "fit",
                    "predict",
                    "save_checkpoint",
                    "load_checkpoint",
                ),
            ),
            FakeClassicalComponent,
        )
        self.registry.register(
            _spec(
                "force",
                execution=ExecutionMode.TASK,
                allowed_methods=("describe", "calculate"),
            ),
            FakeForceComponent,
        )
        payload = ["opaque", "payload"]
        calls = [
            _invocation("q-01", "quantum", "describe"),
            _invocation(
                "q-02",
                "quantum",
                "extract_features",
                args=(payload,),
            ),
            _invocation("c-01", "classical", "describe"),
            _invocation("c-02", "classical", "fit", args=({"x": 1},)),
            _invocation(
                "c-03",
                "classical",
                "predict",
                args=({"x": 2},),
            ),
            _invocation(
                "c-04",
                "classical",
                "save_checkpoint",
                args=("checkpoint.test",),
            ),
            _invocation(
                "c-05",
                "classical",
                "load_checkpoint",
                args=("checkpoint.test",),
            ),
            _invocation("f-01", "force", "describe"),
            _invocation(
                "f-02",
                "force",
                "calculate",
                args=(payload, identity_energy),
            ),
        ]

        results = [self.executor.invoke(call) for call in calls]

        self.assertTrue(all(result.succeeded for result in results))
        self.assertIsInstance(results[1].value, FakeMarker)
        self.assertIs(results[1].value.payload, payload)
        self.assertIsInstance(results[6].value, FakeClassicalComponent)
        self.assertEqual(results[6].value.loaded_from, "checkpoint.test")
        self.assertIsInstance(results[8].value, FakeMarker)
        self.assertIs(results[8].value.payload[0], payload)
        self.assertIs(results[8].value.payload[1], identity_energy)
        self.assertEqual(
            call_log(),
            (
                "quantum.describe",
                "quantum.extract_features",
                "classical.describe",
                "classical.fit",
                "classical.predict",
                "classical.save_checkpoint",
                "classical.load_checkpoint",
                "force.describe",
                "force.calculate",
            ),
        )
        results[6].value.close()

    def test_actor_reuses_one_instance_and_closes_it_once(self) -> None:
        self.registry.register(
            _spec(
                "actor",
                execution=ExecutionMode.ACTOR,
                allowed_methods=("describe", "record"),
            ),
            RecordingFakeComponent,
        )

        first = self.executor.invoke(
            _invocation("invoke-01", "actor", "record", args=("first",))
        )
        second = self.executor.invoke(
            _invocation("invoke-02", "actor", "record", args=("second",))
        )
        self.executor.close()

        self.assertTrue(first.succeeded)
        self.assertTrue(second.succeeded)
        self.assertEqual(RecordingFakeComponent.created_count, 1)
        self.assertEqual(RecordingFakeComponent.closed_count, 1)

    def test_task_creates_and_closes_each_instance_and_preserves_identity(self) -> None:
        self.registry.register(
            _spec(
                "task",
                execution=ExecutionMode.TASK,
                allowed_methods=("describe", "calculate"),
            ),
            FakeForceComponent,
        )
        payload = ["same-object"]

        first = self.executor.invoke(
            _invocation(
                "invoke-01",
                "task",
                "calculate",
                args=(payload, identity_energy),
            )
        )
        second = self.executor.invoke(
            _invocation(
                "invoke-02",
                "task",
                "calculate",
                args=(payload, identity_energy),
            )
        )

        self.assertIs(first.value.payload[0], payload)
        self.assertIs(second.value.payload[0], payload)
        self.assertEqual(FakeForceComponent.created_count, 2)
        self.assertEqual(FakeForceComponent.closed_count, 2)

    def test_dependency_waits_then_allows_downstream_call(self) -> None:
        self.registry.register(
            _spec(
                "upstream",
                execution=ExecutionMode.ACTOR,
                allowed_methods=("describe", "run"),
            ),
            BlockingFakeComponent,
        )
        self.registry.register(
            _spec(
                "downstream",
                execution=ExecutionMode.ACTOR,
                allowed_methods=("describe", "record"),
            ),
            RecordingFakeComponent,
        )
        upstream = self.executor.submit(
            _invocation(
                "upstream-01",
                "upstream",
                "run",
                args=("upstream",),
            )
        )
        self.assertTrue(BlockingFakeComponent.started.wait(timeout=1.0))
        submitted: dict[str, InvocationHandle] = {}
        submit_returned = threading.Event()

        def submit_downstream() -> None:
            submitted["handle"] = self.executor.submit(
                _invocation(
                    "downstream-01",
                    "downstream",
                    "record",
                    args=("downstream",),
                    dependencies=("upstream-01",),
                )
            )
            submit_returned.set()

        thread = threading.Thread(target=submit_downstream)
        thread.start()
        self.assertFalse(RecordingFakeComponent.called.wait(timeout=0.05))
        self.assertFalse(submit_returned.is_set())

        BlockingFakeComponent.release.set()
        thread.join(timeout=1.0)

        self.assertFalse(thread.is_alive())
        self.assertTrue(self.executor.result(upstream).succeeded)
        self.assertTrue(
            self.executor.result(submitted["handle"]).succeeded
        )
        self.assertEqual(
            call_log(),
            ("upstream:start", "upstream:end", "downstream"),
        )

    def test_failed_dependency_prevents_downstream_call(self) -> None:
        self.registry.register(
            _spec(
                "failing",
                execution=ExecutionMode.TASK,
                allowed_methods=("describe", "fail"),
            ),
            FailingFakeComponent,
        )
        self.registry.register(
            _spec(
                "downstream",
                execution=ExecutionMode.ACTOR,
                allowed_methods=("describe", "record"),
            ),
            RecordingFakeComponent,
        )
        failed = self.executor.submit(
            _invocation("failed-01", "failing", "fail")
        )

        downstream = self.executor.submit(
            _invocation(
                "downstream-01",
                "downstream",
                "record",
                args=("must-not-run",),
                dependencies=("failed-01",),
            )
        )

        self.assertEqual(
            self.executor.result(failed).status,
            InvocationStatus.FAILED,
        )
        downstream_result = self.executor.result(downstream)
        self.assertEqual(downstream_result.status, InvocationStatus.FAILED)
        self.assertIsInstance(downstream_result.error, ExecutionError)
        self.assertFalse(RecordingFakeComponent.called.is_set())

    def test_component_exception_is_converted_to_structured_failure(self) -> None:
        self.registry.register(
            _spec(
                "failing",
                execution=ExecutionMode.TASK,
                allowed_methods=("describe", "fail"),
            ),
            FailingFakeComponent,
        )

        result = self.executor.invoke(
            _invocation("invoke-01", "failing", "fail")
        )

        self.assertEqual(result.status, InvocationStatus.FAILED)
        self.assertIsInstance(result.error, ExecutionError)
        self.assertNotIn("fixture failure", result.error.message)

    def test_invalid_task_instance_is_closed_after_validation_failure(self) -> None:
        self.registry.register(
            _spec(
                "invalid",
                execution=ExecutionMode.TASK,
                allowed_methods=("describe",),
            ),
            InvalidFakeComponent,
        )

        result = self.executor.invoke(
            _invocation("invoke-01", "invalid", "describe")
        )

        self.assertEqual(result.status, InvocationStatus.FAILED)
        self.assertEqual(InvalidFakeComponent.created_count, 1)
        self.assertEqual(InvalidFakeComponent.closed_count, 1)

    def test_expired_deadline_skips_component_construction(self) -> None:
        self.registry.register(
            _spec(
                "recording",
                execution=ExecutionMode.ACTOR,
                allowed_methods=("describe", "record"),
            ),
            RecordingFakeComponent,
        )
        invocation = InvocationSpec(
            invocation_id="invoke-01",
            component_id="recording",
            method="record",
            args=("must-not-run",),
            deadline=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

        result = self.executor.invoke(invocation)

        self.assertEqual(result.status, InvocationStatus.TIMED_OUT)
        self.assertEqual(RecordingFakeComponent.created_count, 0)
        self.assertFalse(RecordingFakeComponent.called.is_set())

    def test_actor_max_concurrency_serializes_calls(self) -> None:
        self.registry.register(
            _spec(
                "blocking",
                execution=ExecutionMode.ACTOR,
                allowed_methods=("describe", "run"),
                max_concurrency=1,
            ),
            BlockingFakeComponent,
        )
        first = self.executor.submit(
            _invocation(
                "invoke-01",
                "blocking",
                "run",
                args=("first",),
            )
        )
        self.assertTrue(BlockingFakeComponent.started.wait(timeout=1.0))
        second = self.executor.submit(
            _invocation(
                "invoke-02",
                "blocking",
                "run",
                args=("second",),
            )
        )

        self.assertFalse(
            BlockingFakeComponent.second_started.wait(timeout=0.05)
        )
        self.assertEqual(call_log(), ("first:start",))
        BlockingFakeComponent.release.set()

        self.assertTrue(self.executor.result(first).succeeded)
        self.assertTrue(self.executor.result(second).succeeded)
        self.assertEqual(
            call_log(),
            ("first:start", "first:end", "second:start", "second:end"),
        )

    def test_timeout_returns_promptly_and_close_reclaims_worker(self) -> None:
        self.registry.register(
            _spec(
                "blocking",
                execution=ExecutionMode.ACTOR,
                allowed_methods=("describe", "run"),
                timeout_seconds=0.05,
            ),
            BlockingFakeComponent,
        )
        before = {
            thread.ident
            for thread in threading.enumerate()
            if thread.name.startswith("ray-quantum-local")
        }
        started_at = time.monotonic()

        result = self.executor.invoke(
            _invocation(
                "invoke-01",
                "blocking",
                "run",
                args=("blocking",),
            )
        )
        elapsed = time.monotonic() - started_at

        self.assertLess(elapsed, 0.5)
        self.assertEqual(result.status, InvocationStatus.TIMED_OUT)
        self.assertIsInstance(result.error, FrameworkTimeoutError)
        BlockingFakeComponent.release.set()
        self.executor.close()
        after = {
            thread.ident
            for thread in threading.enumerate()
            if thread.name.startswith("ray-quantum-local")
        }
        self.assertEqual(after, before)

    def test_pending_capacity_is_bounded(self) -> None:
        self.executor.close()
        self.executor = LocalExecutor(
            self.registry,
            max_workers=1,
            max_pending=1,
        )
        self.registry.register(
            _spec(
                "blocking",
                execution=ExecutionMode.ACTOR,
                allowed_methods=("describe", "run"),
            ),
            BlockingFakeComponent,
        )
        first = self.executor.submit(
            _invocation(
                "invoke-01",
                "blocking",
                "run",
                args=("first",),
            )
        )
        self.assertTrue(BlockingFakeComponent.started.wait(timeout=1.0))

        with self.assertRaises(UnavailableError):
            self.executor.submit(
                _invocation(
                    "invoke-02",
                    "blocking",
                    "run",
                    args=("second",),
                )
            )

        BlockingFakeComponent.release.set()
        self.assertTrue(self.executor.result(first).succeeded)

    def test_invalid_submission_handle_and_release_are_rejected(self) -> None:
        self.registry.register(
            _spec(
                "recording",
                execution=ExecutionMode.TASK,
                allowed_methods=("describe", "record"),
            ),
            RecordingFakeComponent,
        )
        invocation = _invocation(
            "invoke-01",
            "recording",
            "record",
            args=("value",),
        )
        handle = self.executor.submit(invocation)
        result = self.executor.result(handle)

        with self.assertRaises(ValidationError):
            self.executor.submit(invocation)
        with self.assertRaises(ValidationError):
            self.executor.submit(
                _invocation(
                    "invoke-02",
                    "recording",
                    "record",
                    dependencies=("missing",),
                )
            )
        with self.assertRaises(ValidationError):
            self.executor.submit(
                _invocation("invoke-03", "recording", "close")
            )
        with self.assertRaises(ValidationError):
            self.executor.result(
                InvocationHandle(
                    "invoke-01",
                    "recording",
                    "forged-reference",
                )
            )

        self.assertTrue(result.succeeded)
        self.executor.release(handle)
        with self.assertRaises(ValidationError):
            self.executor.result(handle)

    def test_close_rejects_new_submissions_but_is_idempotent(self) -> None:
        self.executor.close()
        self.executor.close()

        self.assertTrue(self.executor.closed)
        with self.assertRaises(UnavailableError):
            self.executor.submit(
                _invocation("invoke-01", "missing", "describe")
            )

    def test_import_does_not_load_ray(self) -> None:
        before = {
            name
            for name in sys.modules
            if name == "ray" or name.startswith("ray.")
        }

        importlib.import_module("pivotq._internal.executors")

        after = {
            name
            for name in sys.modules
            if name == "ray" or name.startswith("ray.")
        }
        self.assertEqual(after, before)


class LocalExecutorConstructorTest(unittest.TestCase):
    def test_constructor_rejects_invalid_capacity(self) -> None:
        registry = ComponentRegistry()
        try:
            invalid_arguments = [
                {"max_workers": 0},
                {"max_workers": True},
                {"max_pending": 0},
                {"max_pending": True},
            ]
            for arguments in invalid_arguments:
                with self.subTest(arguments=arguments), self.assertRaises(
                    (TypeError, ValueError)
                ):
                    LocalExecutor(registry, **arguments)
            with self.assertRaises(TypeError):
                LocalExecutor(object())  # type: ignore[arg-type]
        finally:
            registry.close()


if __name__ == "__main__":
    unittest.main()
