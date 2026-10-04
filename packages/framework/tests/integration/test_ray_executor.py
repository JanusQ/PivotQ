"""Single-node integration tests for the P3 RayExecutor."""

from __future__ import annotations

import os
import threading
import time
import unittest
import uuid

import ray

from pivotq._internal.errors import ExecutionError
from pivotq._internal.executors import Executor, RayExecutor
from pivotq._internal.framework import (
    ComponentRegistry,
    ComponentSpec,
    ExecutionMode,
    InvocationSpec,
    InvocationStatus,
    ResourceRequest,
)
from tests.contract.executor_contract import ExecutorContractMixin
from tests.fixtures.fake_components import (
    ConcurrencyProbeComponent,
    RuntimeProbeComponent,
    reset_all_fakes,
)


_RAY_WAS_INITIALIZED_AFTER_EXECUTOR_IMPORT = ray.is_initialized()


def _spec(
    component_id: str,
    *,
    execution: ExecutionMode,
    resources: ResourceRequest | None = None,
    timeout_seconds: float | None = None,
) -> ComponentSpec:
    return ComponentSpec(
        component_id=component_id,
        execution=execution,
        resources=resources or ResourceRequest(),
        allowed_methods=(
            "describe",
            "instance_token",
            "process_id",
            "sleep",
        ),
        stateful=execution is ExecutionMode.ACTOR,
        timeout_seconds=timeout_seconds,
    )


class RayExecutorContractTest(ExecutorContractMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if ray.is_initialized():
            ray.shutdown()
        ray.init(
            num_cpus=4,
            include_dashboard=False,
            log_to_driver=False,
            namespace=f"ray-quantum-p3-{uuid.uuid4().hex}",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        if ray.is_initialized():
            ray.shutdown()

    def setUp(self) -> None:
        reset_all_fakes()
        self.registry = ComponentRegistry()
        self.executor = RayExecutor(
            self.registry,
            actor_close_timeout_seconds=2.0,
        )

    def tearDown(self) -> None:
        self.executor.close()
        self.registry.close()

    def test_executor_implements_shared_contract_and_import_did_not_init(self) -> None:
        self.assertIsInstance(self.executor, Executor)
        self.assertFalse(_RAY_WAS_INITIALIZED_AFTER_EXECUTOR_IMPORT)
        self.assertTrue(ray.is_initialized())

    def test_task_and_actor_run_outside_driver_process(self) -> None:
        self.registry.register(
            _spec("ray-task-process", execution=ExecutionMode.TASK),
            RuntimeProbeComponent,
        )
        self.registry.register(
            _spec("ray-actor-process", execution=ExecutionMode.ACTOR),
            RuntimeProbeComponent,
        )
        driver_pid = os.getpid()

        task_result = self.executor.invoke(
            InvocationSpec(
                "ray-task-process-1",
                "ray-task-process",
                "process_id",
            )
        )
        actor_result = self.executor.invoke(
            InvocationSpec(
                "ray-actor-process-1",
                "ray-actor-process",
                "process_id",
            )
        )

        self.assertTrue(task_result.succeeded)
        self.assertTrue(actor_result.succeeded)
        self.assertNotEqual(task_result.value, driver_pid)
        self.assertNotEqual(actor_result.value, driver_pid)

    def test_async_handle_contains_object_ref_and_close_keeps_ray_running(self) -> None:
        self.registry.register(
            _spec("ray-async", execution=ExecutionMode.TASK),
            RuntimeProbeComponent,
        )

        handle = self.executor.submit(
            InvocationSpec(
                "ray-async-1",
                "ray-async",
                "process_id",
            )
        )

        self.assertIsInstance(handle.reference, ray.ObjectRef)
        self.assertTrue(self.executor.result(handle).succeeded)
        self.executor.close()
        self.assertTrue(ray.is_initialized())

    def test_actor_max_concurrency_is_applied(self) -> None:
        self.registry.register(
            ComponentSpec(
                component_id="ray-concurrent-actor",
                execution=ExecutionMode.ACTOR,
                resources=ResourceRequest(num_cpus=1),
                allowed_methods=("describe", "probe"),
                stateful=True,
                max_concurrency=2,
            ),
            ConcurrencyProbeComponent,
        )

        first = self.executor.submit(
            InvocationSpec(
                "ray-concurrent-1",
                "ray-concurrent-actor",
                "probe",
                args=(0.3,),
            )
        )
        second = self.executor.submit(
            InvocationSpec(
                "ray-concurrent-2",
                "ray-concurrent-actor",
                "probe",
                args=(0.3,),
            )
        )

        results = (
            self.executor.result(first),
            self.executor.result(second),
        )

        self.assertTrue(all(result.succeeded for result in results))
        self.assertEqual(max(result.value for result in results), 2)

    def test_timeout_is_prompt_and_blocks_dependent_invocation(self) -> None:
        self.registry.register(
            _spec(
                "ray-timeout",
                execution=ExecutionMode.TASK,
                timeout_seconds=0.1,
            ),
            RuntimeProbeComponent,
        )
        self.registry.register(
            _spec("ray-after-timeout", execution=ExecutionMode.TASK),
            RuntimeProbeComponent,
        )
        started_at = time.monotonic()
        upstream = self.executor.submit(
            InvocationSpec(
                "ray-timeout-1",
                "ray-timeout",
                "sleep",
                args=(0.5,),
            )
        )
        downstream = self.executor.submit(
            InvocationSpec(
                "ray-after-timeout-1",
                "ray-after-timeout",
                "process_id",
                dependencies=("ray-timeout-1",),
            )
        )

        upstream_result = self.executor.result(upstream)
        elapsed = time.monotonic() - started_at
        downstream_result = self.executor.result(downstream)

        self.assertLess(elapsed, 0.75)
        self.assertEqual(
            upstream_result.status,
            InvocationStatus.TIMED_OUT,
        )
        self.assertEqual(
            downstream_result.status,
            InvocationStatus.FAILED,
        )

    def test_unserializable_factory_becomes_structured_failure(self) -> None:
        lock = threading.Lock()

        def factory() -> RuntimeProbeComponent:
            if lock.locked():
                raise RuntimeError("unreachable")
            return RuntimeProbeComponent()

        self.registry.register(
            _spec("ray-bad-factory", execution=ExecutionMode.TASK),
            factory,
        )

        result = self.executor.invoke(
            InvocationSpec(
                "ray-bad-factory-1",
                "ray-bad-factory",
                "describe",
            )
        )

        self.assertEqual(result.status, InvocationStatus.FAILED)
        self.assertIsInstance(result.error, ExecutionError)

    def test_gpu_execution_is_explicitly_skipped_without_hardware(self) -> None:
        if ray.cluster_resources().get("GPU", 0.0) < 1.0:
            self.skipTest(
                "GPU unavailable; num_gpus mapping is covered by unit tests"
            )
        self.registry.register(
            _spec(
                "ray-gpu",
                execution=ExecutionMode.TASK,
                resources=ResourceRequest(num_cpus=0.1, num_gpus=1),
            ),
            RuntimeProbeComponent,
        )

        result = self.executor.invoke(
            InvocationSpec(
                "ray-gpu-1",
                "ray-gpu",
                "process_id",
            )
        )

        self.assertTrue(result.succeeded)


if __name__ == "__main__":
    unittest.main()
