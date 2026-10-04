"""Capacity test for logical QPU custom resources on one Ray node."""

from __future__ import annotations

import time
import unittest
import uuid

import ray

from pivotq._internal.executors import RayExecutor
from pivotq._internal.framework import (
    ComponentRegistry,
    ComponentSpec,
    ExecutionMode,
    InvocationSpec,
    ResourceRequest,
)
from tests.fixtures.fake_components import RuntimeProbeComponent


def _qpu_spec(component_id: str) -> ComponentSpec:
    return ComponentSpec(
        component_id=component_id,
        execution=ExecutionMode.ACTOR,
        resources=ResourceRequest(
            num_cpus=0.1,
            custom_resources={"QPU": 1},
        ),
        allowed_methods=("describe", "process_id"),
        stateful=True,
        timeout_seconds=5.0,
    )


class QpuResourceCapacityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if ray.is_initialized():
            ray.shutdown()
        ray.init(
            num_cpus=2,
            resources={"QPU": 1},
            include_dashboard=False,
            log_to_driver=False,
            namespace=f"ray-quantum-p3-qpu-{uuid.uuid4().hex}",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        if ray.is_initialized():
            ray.shutdown()

    def setUp(self) -> None:
        self.registry = ComponentRegistry()
        self.registry.register(
            _qpu_spec("qpu-actor-a"),
            RuntimeProbeComponent,
        )
        self.registry.register(
            _qpu_spec("qpu-actor-b"),
            RuntimeProbeComponent,
        )
        self.first = RayExecutor(
            self.registry,
            actor_close_timeout_seconds=2.0,
        )
        self.second = RayExecutor(
            self.registry,
            actor_close_timeout_seconds=2.0,
        )

    def tearDown(self) -> None:
        self.first.close()
        self.second.close()
        self.registry.close()

    def test_qpu_actor_capacity_is_not_oversold_and_is_released(self) -> None:
        first_result = self.first.invoke(
            InvocationSpec(
                "qpu-invocation-a",
                "qpu-actor-a",
                "process_id",
            )
        )
        self.assertTrue(first_result.succeeded)

        second_handle = self.second.submit(
            InvocationSpec(
                "qpu-invocation-b",
                "qpu-actor-b",
                "process_id",
            )
        )
        ready, _ = ray.wait([second_handle.reference], timeout=0.3)
        self.assertEqual(
            ready,
            [],
            "a second QPU:1 Actor ran while the only token was held",
        )

        self.first.close()
        second_result = self.second.result(second_handle)
        self.assertTrue(second_result.succeeded)

        self.second.close()
        deadline = time.monotonic() + 5.0
        while (
            ray.available_resources().get("QPU", 0.0) < 1.0
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)
        self.assertEqual(
            ray.available_resources().get("QPU", 0.0),
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
