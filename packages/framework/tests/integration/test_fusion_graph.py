"""P4 façade and fake Quantum -> Classical -> Force DAG integration tests."""

from __future__ import annotations

import unittest
import uuid
from typing import Any

from pivotq._internal.errors import ValidationError
from pivotq._internal.executors import LocalExecutor
from pivotq._internal.framework import (
    ComponentRegistry,
    ComponentSpec,
    ExecutionMode,
    FusionFramework,
    InvocationSpec,
    InvocationStatus,
    ResourceRequest,
    ResultRef,
)
from tests.fixtures.fake_components import (
    CancellingFakeComponent,
    FailingFakeComponent,
    FakeClassicalComponent,
    FakeForceComponent,
    FakeMarker,
    FakeQuantumComponent,
    PassthroughFakeComponent,
    RuntimeProbeComponent,
    call_log,
    identity_energy,
    reset_all_fakes,
)

try:
    import ray
except ModuleNotFoundError:
    ray = None  # type: ignore[assignment]


def _spec(
    component_id: str,
    *,
    execution: ExecutionMode,
    allowed_methods: tuple[str, ...],
    timeout_seconds: float | None = None,
) -> ComponentSpec:
    return ComponentSpec(
        component_id=component_id,
        execution=execution,
        resources=ResourceRequest(num_cpus=0.1),
        allowed_methods=allowed_methods,
        stateful=execution is ExecutionMode.ACTOR,
        timeout_seconds=timeout_seconds,
    )


def _register_components(framework: FusionFramework) -> None:
    framework.register(
        _spec(
            "fusion-quantum",
            execution=ExecutionMode.ACTOR,
            allowed_methods=("describe", "extract_features"),
        ),
        FakeQuantumComponent,
    )
    framework.register(
        _spec(
            "fusion-classical",
            execution=ExecutionMode.ACTOR,
            allowed_methods=("describe", "predict"),
        ),
        FakeClassicalComponent,
    )
    framework.register(
        _spec(
            "fusion-force",
            execution=ExecutionMode.TASK,
            allowed_methods=("describe", "calculate"),
        ),
        FakeForceComponent,
    )
    framework.register(
        _spec(
            "fusion-passthrough",
            execution=ExecutionMode.TASK,
            allowed_methods=("describe", "echo"),
        ),
        PassthroughFakeComponent,
    )
    framework.register(
        _spec(
            "fusion-failing",
            execution=ExecutionMode.TASK,
            allowed_methods=("describe", "fail"),
        ),
        FailingFakeComponent,
    )
    framework.register(
        _spec(
            "fusion-cancelling",
            execution=ExecutionMode.TASK,
            allowed_methods=("describe", "cancel"),
        ),
        CancellingFakeComponent,
    )
    framework.register(
        _spec(
            "fusion-timeout",
            execution=ExecutionMode.TASK,
            allowed_methods=("describe", "sleep"),
            timeout_seconds=0.05,
        ),
        RuntimeProbeComponent,
    )


class FusionGraphContractMixin:
    """Run the same P4 application behavior against Local and Ray."""

    framework: FusionFramework
    expect_driver_call_log: bool

    def test_async_fake_chain_moves_values_without_intermediate_result_calls(
        self,
    ) -> None:
        request = {"opaque": "external-request"}

        quantum = self.framework.submit(
            "fusion-quantum",
            "extract_features",
            request,
            invocation_id="fusion-q-1",
        )
        classical = self.framework.submit(
            "fusion-classical",
            "predict",
            invocation_id="fusion-c-1",
            request=quantum,
        )
        force = self.framework.submit(
            "fusion-force",
            "calculate",
            classical,
            identity_energy,
            invocation_id="fusion-f-1",
        )

        result = self.framework.result(force)

        self.assertEqual(
            result.value,
            FakeMarker(
                "force",
                "calculate",
                (
                    FakeMarker(
                        "classical",
                        "predict",
                        FakeMarker(
                            "quantum",
                            "extract_features",
                            request,
                        ),
                    ),
                    identity_energy,
                ),
            ),
        )
        if self.expect_driver_call_log:
            self.assertEqual(
                call_log(),
                (
                    "quantum.extract_features",
                    "classical.predict",
                    "force.calculate",
                ),
            )

        self.framework.release(force)
        self.framework.release(classical)
        self.framework.release(quantum)
        with self.assertRaises(ValidationError):
            self.framework.result(force)

    def test_reversed_batch_is_validated_then_submitted_topologically(
        self,
    ) -> None:
        request = ("opaque", "batch")
        quantum = InvocationSpec(
            "batch-q",
            "fusion-quantum",
            "extract_features",
            args=(request,),
        )
        classical = InvocationSpec(
            "batch-c",
            "fusion-classical",
            "predict",
            args=(ResultRef("batch-q"),),
        )
        force = InvocationSpec(
            "batch-f",
            "fusion-force",
            "calculate",
            args=(ResultRef("batch-c"), identity_energy),
        )

        handles = self.framework.submit_graph(
            (force, classical, quantum)
        )
        result = self.framework.result(handles[-1])

        self.assertEqual(
            tuple(handle.invocation_id for handle in handles),
            ("batch-q", "batch-c", "batch-f"),
        )
        self.assertEqual(result.value.component, "force")
        self.assertEqual(
            result.value.payload[0].payload.payload,
            request,
        )

    def test_cycle_is_rejected_before_any_node_is_submitted(self) -> None:
        first = InvocationSpec(
            "cycle-a",
            "fusion-passthrough",
            "echo",
            args=(ResultRef("cycle-b"),),
        )
        second = InvocationSpec(
            "cycle-b",
            "fusion-passthrough",
            "echo",
            args=(ResultRef("cycle-a"),),
        )

        with self.assertRaisesRegex(ValidationError, "cycle"):
            self.framework.submit_graph((first, second))

        result = self.framework.invoke(
            "fusion-passthrough",
            "echo",
            "still-available",
            invocation_id="cycle-a",
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.value, "still-available")

    def test_failure_cancellation_and_timeout_block_result_consumers(
        self,
    ) -> None:
        cases: tuple[tuple[str, str, str, tuple[Any, ...], InvocationStatus], ...] = (
            (
                "failed",
                "fusion-failing",
                "fail",
                (),
                InvocationStatus.FAILED,
            ),
            (
                "cancelled",
                "fusion-cancelling",
                "cancel",
                (),
                InvocationStatus.CANCELLED,
            ),
            (
                "timed-out",
                "fusion-timeout",
                "sleep",
                (0.2,),
                InvocationStatus.TIMED_OUT,
            ),
        )
        for prefix, component_id, method, args, expected_status in cases:
            with self.subTest(prefix=prefix):
                upstream = self.framework.submit(
                    component_id,
                    method,
                    *args,
                    invocation_id=f"{prefix}-upstream",
                )
                downstream = self.framework.submit(
                    "fusion-passthrough",
                    "echo",
                    upstream,
                    invocation_id=f"{prefix}-downstream",
                )

                self.assertEqual(
                    self.framework.result(upstream).status,
                    expected_status,
                )
                self.assertEqual(
                    self.framework.result(downstream).status,
                    InvocationStatus.FAILED,
                )

    def test_register_describe_invoke_and_unregister_share_one_facade(
        self,
    ) -> None:
        spec = _spec(
            "fusion-unused",
            execution=ExecutionMode.TASK,
            allowed_methods=("describe", "echo"),
        )

        registration = self.framework.register(
            spec,
            PassthroughFakeComponent,
        )
        described = self.framework.describe("fusion-unused")
        removed = self.framework.unregister("fusion-unused")
        result = self.framework.invoke(
            "fusion-passthrough",
            "echo",
            {"opaque": "value"},
            invocation_id="sync-1",
        )

        self.assertIs(registration.spec, spec)
        self.assertIs(described, spec)
        self.assertIs(removed, registration)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.value, {"opaque": "value"})
        with self.assertRaisesRegex(ValidationError, "close the executor"):
            self.framework.unregister("fusion-passthrough")


class LocalFusionGraphTest(
    FusionGraphContractMixin,
    unittest.TestCase,
):
    def setUp(self) -> None:
        reset_all_fakes()
        self.registry = ComponentRegistry()
        self.executor = LocalExecutor(
            self.registry,
            max_workers=8,
            max_pending=32,
        )
        self.framework = FusionFramework(self.executor)
        self.expect_driver_call_log = True
        _register_components(self.framework)

    def tearDown(self) -> None:
        self.framework.close()
        self.registry.close()


@unittest.skipIf(ray is None, "Ray is not installed in the editing environment")
class RayFusionGraphTest(
    FusionGraphContractMixin,
    unittest.TestCase,
):
    @classmethod
    def setUpClass(cls) -> None:
        assert ray is not None
        if ray.is_initialized():
            ray.shutdown()
        ray.init(
            num_cpus=4,
            include_dashboard=False,
            log_to_driver=False,
            namespace=f"ray-quantum-p4-{uuid.uuid4().hex}",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        assert ray is not None
        if ray.is_initialized():
            ray.shutdown()

    def setUp(self) -> None:
        from pivotq._internal.executors import RayExecutor

        reset_all_fakes()
        self.registry = ComponentRegistry()
        self.executor = RayExecutor(
            self.registry,
            actor_close_timeout_seconds=2.0,
        )
        self.framework = FusionFramework(self.executor)
        self.expect_driver_call_log = False
        _register_components(self.framework)

    def tearDown(self) -> None:
        self.framework.close()
        self.registry.close()


if __name__ == "__main__":
    unittest.main()
