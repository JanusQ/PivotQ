"""P6 opt-in validation against a real two-node Ray cluster."""

from __future__ import annotations

import os
import time
import unittest
import uuid
from typing import Any

from pivotq._internal.executors import RayExecutor
from pivotq._internal.framework import (
    ComponentRegistry,
    ComponentSpec,
    ExecutionMode,
    FusionFramework,
    InvocationSpec,
    InvocationStatus,
    ResourceRequest,
)
from pivotq._internal.observability import TraceCollector
from tests.fixtures.fake_components import RuntimeProbeComponent

try:
    import ray
except ImportError:  # pragma: no cover - target environment has Ray.
    ray = None


_CLUSTER_TEST_ENABLED = (
    ray is not None and os.environ.get("RAY_QUANTUM_CLUSTER_TEST") == "1"
)
_GPU_CLUSTER_TEST_ENABLED = (
    _CLUSTER_TEST_ENABLED
    and os.environ.get("RAY_QUANTUM_CLUSTER_GPU_TEST") == "1"
)
_NODE_FAILURE_TEST_ENABLED = (
    _CLUSTER_TEST_ENABLED
    and os.environ.get("RAY_QUANTUM_NODE_FAILURE_TEST") == "1"
)


def _probe_spec(
    component_id: str,
    *,
    execution: ExecutionMode,
    resources: ResourceRequest,
    timeout_seconds: float = 15.0,
) -> ComponentSpec:
    return ComponentSpec(
        component_id=component_id,
        execution=execution,
        resources=resources,
        allowed_methods=(
            "capture",
            "describe",
            "runtime_environment",
            "signal_and_sleep",
        ),
        stateful=execution is ExecutionMode.ACTOR,
        timeout_seconds=timeout_seconds,
    )


def _alive_node_ids_by_ip() -> dict[str, str]:
    assert ray is not None
    return {
        str(node["NodeManagerAddress"]): str(node["NodeID"])
        for node in ray.nodes()
        if node["Alive"]
    }


def _wait_for_nodes(
    expected_ips: set[str],
    *,
    timeout_seconds: float = 20.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout_seconds
    node_ids: dict[str, str] = {}
    while time.monotonic() < deadline:
        node_ids = _alive_node_ids_by_ip()
        if expected_ips <= node_ids.keys():
            return node_ids
        time.sleep(0.2)
    raise AssertionError(
        f"cluster did not expose expected nodes {sorted(expected_ips)}; "
        f"alive nodes were {node_ids}"
    )


class _ConnectedClusterTest(unittest.TestCase):
    head_ip: str
    worker_ip: str
    node_ids_by_ip: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        assert ray is not None
        cls.head_ip = os.environ["RAY_QUANTUM_HEAD_IP"]
        cls.worker_ip = os.environ["RAY_QUANTUM_WORKER_IP"]
        if ray.is_initialized():
            ray.shutdown()
        ray.init(
            address="auto",
            namespace=f"ray-quantum-p6-{uuid.uuid4().hex}",
            log_to_driver=False,
        )
        cls.node_ids_by_ip = _wait_for_nodes(
            {cls.head_ip, cls.worker_ip}
        )

    @classmethod
    def tearDownClass(cls) -> None:
        assert ray is not None
        if ray.is_initialized():
            ray.shutdown()


@unittest.skipUnless(
    _CLUSTER_TEST_ENABLED,
    "set RAY_QUANTUM_CLUSTER_TEST=1 for a configured two-node cluster",
)
class RayClusterPlacementTest(_ConnectedClusterTest):
    def setUp(self) -> None:
        self.registry = ComponentRegistry()
        self.collector = TraceCollector()
        self.executor = RayExecutor(
            self.registry,
            actor_close_timeout_seconds=3.0,
            trace_collector=self.collector,
        )
        self.framework = FusionFramework(self.executor)

    def tearDown(self) -> None:
        self.framework.close()
        self.registry.close()

    def test_cpu_qpu_placement_objectref_and_trace(self) -> None:
        self.framework.register(
            _probe_spec(
                "p6-cpu",
                execution=ExecutionMode.TASK,
                resources=ResourceRequest(num_cpus=1),
            ),
            RuntimeProbeComponent,
        )
        self.framework.register(
            _probe_spec(
                "p6-qpu",
                execution=ExecutionMode.ACTOR,
                resources=ResourceRequest(
                    num_cpus=0,
                    custom_resources={"QPU": 1},
                ),
            ),
            RuntimeProbeComponent,
        )

        qpu = self.framework.submit(
            "p6-qpu",
            "capture",
            {"opaque": "worker-to-worker"},
            invocation_id="p6-qpu-placement",
        )
        cpu = self.framework.submit(
            "p6-cpu",
            "capture",
            qpu,
            invocation_id="p6-cpu-placement",
        )

        cpu_result = self.framework.result(cpu)
        qpu_result = self.framework.result(qpu)

        self.assertTrue(cpu_result.succeeded)
        self.assertTrue(qpu_result.succeeded)
        self.assertEqual(
            cpu_result.value["runtime"]["node_id"],
            self.node_ids_by_ip[self.head_ip],
        )
        self.assertEqual(
            qpu_result.value["runtime"]["node_id"],
            self.node_ids_by_ip[self.worker_ip],
        )
        self.assertEqual(
            cpu_result.value["value"]["runtime"]["node_id"],
            self.node_ids_by_ip[self.worker_ip],
            "the logical-QPU value was not injected into the CPU task across nodes",
        )

        records = {
            record.invocation_id: record
            for record in self.collector.snapshot()
        }
        self.assertEqual(
            records["p6-cpu-placement"].dependencies,
            ("p6-qpu-placement",),
        )
        self.assertEqual(
            records["p6-cpu-placement"].node_id,
            self.node_ids_by_ip[self.head_ip],
        )
        self.assertEqual(
            records["p6-qpu-placement"].node_id,
            self.node_ids_by_ip[self.worker_ip],
        )
        self.assertIsNotNone(records["p6-qpu-placement"].actor_id)
        self.assertIsNotNone(records["p6-cpu-placement"].task_id)
        self.assertEqual(
            records["p6-qpu-placement"].resources.custom_resources_dict(),
            {"QPU": 1.0},
        )

        resources = ray.cluster_resources()
        self.assertGreaterEqual(resources.get("CPU", 0.0), 1.0)
        self.assertEqual(resources.get("QPU"), 1.0)

        self.framework.release(cpu)
        self.framework.release(qpu)

    @unittest.skipUnless(
        _GPU_CLUSTER_TEST_ENABLED,
        "set RAY_QUANTUM_CLUSTER_GPU_TEST=1 for a real GPU cluster",
    )
    def test_cpu_qpu_gpu_placement_objectref_and_trace(self) -> None:
        self.framework.register(
            _probe_spec(
                "p6-cpu",
                execution=ExecutionMode.TASK,
                resources=ResourceRequest(num_cpus=1),
            ),
            RuntimeProbeComponent,
        )
        self.framework.register(
            _probe_spec(
                "p6-qpu",
                execution=ExecutionMode.ACTOR,
                resources=ResourceRequest(
                    num_cpus=0,
                    custom_resources={"QPU": 1},
                ),
            ),
            RuntimeProbeComponent,
        )
        self.framework.register(
            _probe_spec(
                "p6-gpu",
                execution=ExecutionMode.TASK,
                resources=ResourceRequest(num_cpus=0, num_gpus=1),
            ),
            RuntimeProbeComponent,
        )

        qpu = self.framework.submit(
            "p6-qpu",
            "capture",
            {"opaque": "worker-to-worker"},
            invocation_id="p6-qpu-placement",
        )
        cpu = self.framework.submit(
            "p6-cpu",
            "capture",
            qpu,
            invocation_id="p6-cpu-placement",
        )
        gpu = self.framework.submit(
            "p6-gpu",
            "capture",
            {"opaque": "gpu-placement"},
            invocation_id="p6-gpu-placement",
        )

        cpu_result = self.framework.result(cpu)
        gpu_result = self.framework.result(gpu)
        qpu_result = self.framework.result(qpu)

        self.assertTrue(cpu_result.succeeded)
        self.assertTrue(qpu_result.succeeded)
        self.assertTrue(gpu_result.succeeded)

        cpu_runtime = cpu_result.value["runtime"]
        qpu_runtime = qpu_result.value["runtime"]
        gpu_runtime = gpu_result.value["runtime"]
        self.assertEqual(
            cpu_runtime["node_id"],
            self.node_ids_by_ip[self.head_ip],
        )
        self.assertEqual(
            qpu_runtime["node_id"],
            self.node_ids_by_ip[self.worker_ip],
        )
        self.assertEqual(
            gpu_runtime["node_id"],
            self.node_ids_by_ip[self.worker_ip],
        )
        self.assertEqual(
            cpu_result.value["value"]["runtime"]["node_id"],
            self.node_ids_by_ip[self.worker_ip],
            "the QPU value was not injected into the CPU task across nodes",
        )
        self.assertTrue(gpu_runtime["cuda_visible_devices"])
        self.assertTrue(gpu_runtime["accelerator_ids"].get("GPU"))
        self.assertIsInstance(gpu_runtime["nvidia_smi"], str)
        self.assertIn("NVIDIA", gpu_runtime["nvidia_smi"])

        records = {
            record.invocation_id: record
            for record in self.collector.snapshot()
        }
        self.assertEqual(
            records["p6-cpu-placement"].dependencies,
            ("p6-qpu-placement",),
        )
        self.assertEqual(
            records["p6-cpu-placement"].node_id,
            self.node_ids_by_ip[self.head_ip],
        )
        self.assertEqual(
            records["p6-qpu-placement"].node_id,
            self.node_ids_by_ip[self.worker_ip],
        )
        self.assertEqual(
            records["p6-gpu-placement"].node_id,
            self.node_ids_by_ip[self.worker_ip],
        )
        self.assertIsNotNone(records["p6-qpu-placement"].actor_id)
        self.assertIsNotNone(records["p6-cpu-placement"].task_id)
        self.assertIsNotNone(records["p6-gpu-placement"].task_id)
        self.assertEqual(
            records["p6-qpu-placement"].resources.custom_resources_dict(),
            {"QPU": 1.0},
        )
        self.assertEqual(
            records["p6-gpu-placement"].resources.num_gpus,
            1.0,
        )

        resources = ray.cluster_resources()
        self.assertGreaterEqual(resources.get("CPU", 0.0), 1.0)
        self.assertEqual(resources.get("QPU"), 1.0)
        self.assertEqual(resources.get("GPU"), 1.0)

    def test_qpu_capacity_and_unschedulable_timeout_are_bounded(self) -> None:
        for component_id in ("p6-qpu-a", "p6-qpu-b"):
            self.registry.register(
                _probe_spec(
                    component_id,
                    execution=ExecutionMode.ACTOR,
                    resources=ResourceRequest(
                        num_cpus=0,
                        custom_resources={"QPU": 1},
                    ),
                ),
                RuntimeProbeComponent,
            )
        self.registry.register(
            _probe_spec(
                "p6-qpu-impossible",
                execution=ExecutionMode.TASK,
                resources=ResourceRequest(
                    num_cpus=0,
                    custom_resources={"QPU": 2},
                ),
                timeout_seconds=1.0,
            ),
            RuntimeProbeComponent,
        )

        first = RayExecutor(
            self.registry,
            actor_close_timeout_seconds=3.0,
        )
        second = RayExecutor(
            self.registry,
            actor_close_timeout_seconds=3.0,
        )
        try:
            first_result = first.invoke(
                InvocationSpec(
                    "p6-qpu-capacity-a",
                    "p6-qpu-a",
                    "runtime_environment",
                )
            )
            self.assertTrue(first_result.succeeded)

            second_handle = second.submit(
                InvocationSpec(
                    "p6-qpu-capacity-b",
                    "p6-qpu-b",
                    "runtime_environment",
                )
            )
            ready, _ = ray.wait([second_handle.reference], timeout=0.5)
            self.assertEqual(
                ready,
                [],
                "the second QPU Actor ran while QPU:1 was already held",
            )

            first.close()
            second_result = second.result(second_handle)
            self.assertTrue(second_result.succeeded)
            self.assertEqual(
                second_result.value["node_id"],
                self.node_ids_by_ip[self.worker_ip],
            )

            started = time.monotonic()
            impossible = self.framework.invoke(
                "p6-qpu-impossible",
                "runtime_environment",
                invocation_id="p6-qpu-impossible",
            )
            self.assertEqual(impossible.status, InvocationStatus.TIMED_OUT)
            self.assertLess(time.monotonic() - started, 5.0)
        finally:
            first.close()
            second.close()


@unittest.skipUnless(
    _NODE_FAILURE_TEST_ENABLED,
    "set RAY_QUANTUM_NODE_FAILURE_TEST=1 for the destructive node test",
)
class RayClusterNodeFailureTest(_ConnectedClusterTest):
    def test_worker_loss_is_terminal_and_missing_resource_times_out(self) -> None:
        marker_path = os.environ["RAY_QUANTUM_NODE_FAILURE_MARKER"]
        registry = ComponentRegistry()
        registry.register(
            _probe_spec(
                "p6-node-failure",
                execution=ExecutionMode.TASK,
                resources=ResourceRequest(
                    num_cpus=0,
                    custom_resources={"QPU": 1},
                ),
                timeout_seconds=45.0,
            ),
            RuntimeProbeComponent,
        )
        registry.register(
            _probe_spec(
                "p6-missing-qpu",
                execution=ExecutionMode.TASK,
                resources=ResourceRequest(
                    num_cpus=0,
                    custom_resources={"QPU": 1},
                ),
                timeout_seconds=2.0,
            ),
            RuntimeProbeComponent,
        )
        executor = RayExecutor(
            registry,
            actor_close_timeout_seconds=3.0,
        )
        framework = FusionFramework(executor)
        try:
            in_flight = framework.submit(
                "p6-node-failure",
                "signal_and_sleep",
                marker_path,
                60.0,
                invocation_id="p6-node-failure",
            )
            result = framework.result(in_flight)
            self.assertIn(
                result.status,
                (InvocationStatus.FAILED, InvocationStatus.TIMED_OUT),
            )

            deadline = time.monotonic() + 20.0
            while (
                self.worker_ip in _alive_node_ids_by_ip()
                and time.monotonic() < deadline
            ):
                time.sleep(0.2)
            self.assertNotIn(self.worker_ip, _alive_node_ids_by_ip())

            started = time.monotonic()
            missing = framework.invoke(
                "p6-missing-qpu",
                "runtime_environment",
                invocation_id="p6-missing-qpu",
            )
            self.assertEqual(missing.status, InvocationStatus.TIMED_OUT)
            self.assertLess(time.monotonic() - started, 6.0)
        finally:
            framework.close()
            registry.close()


if __name__ == "__main__":
    unittest.main()
