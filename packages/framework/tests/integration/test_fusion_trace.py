"""P5 trace integration over the P4 fake fusion chain."""

from __future__ import annotations

import json
import unittest
import uuid

from pivotq._internal.executors import LocalExecutor
from pivotq._internal.framework import (
    ComponentRegistry,
    ComponentSpec,
    ExecutionMode,
    FusionFramework,
    ResourceRequest,
)
from pivotq._internal.models import StringMetadata
from pivotq._internal.observability import TraceCollector
from tests.fixtures.fake_components import (
    CancellingFakeComponent,
    FailingFakeComponent,
    FakeClassicalComponent,
    FakeForceComponent,
    FakeQuantumComponent,
    RuntimeProbeComponent,
    identity_energy,
    reset_all_fakes,
)

try:
    import ray
except ImportError:  # pragma: no cover - target environment has Ray.
    ray = None


def _register_components(framework: FusionFramework) -> None:
    framework.register(
        ComponentSpec(
            component_id="trace-quantum",
            execution=ExecutionMode.TASK,
            resources=ResourceRequest(
                num_cpus=0.25,
                custom_resources={"QPU": 1},
            ),
            allowed_methods=("describe", "extract_features"),
        ),
        FakeQuantumComponent,
    )
    framework.register(
        ComponentSpec(
            component_id="trace-classical",
            execution=ExecutionMode.ACTOR,
            resources=ResourceRequest(num_cpus=0.25),
            allowed_methods=("describe", "predict"),
            stateful=True,
        ),
        FakeClassicalComponent,
    )
    framework.register(
        ComponentSpec(
            component_id="trace-force",
            execution=ExecutionMode.TASK,
            resources=ResourceRequest(num_cpus=0.25),
            allowed_methods=("describe", "calculate"),
        ),
        FakeForceComponent,
    )
    framework.register(
        ComponentSpec(
            component_id="trace-failing",
            execution=ExecutionMode.TASK,
            resources=ResourceRequest(num_cpus=0.25),
            allowed_methods=("describe", "fail"),
        ),
        FailingFakeComponent,
    )
    framework.register(
        ComponentSpec(
            component_id="trace-cancelling",
            execution=ExecutionMode.TASK,
            resources=ResourceRequest(num_cpus=0.25),
            allowed_methods=("describe", "cancel"),
        ),
        CancellingFakeComponent,
    )
    framework.register(
        ComponentSpec(
            component_id="trace-timeout",
            execution=ExecutionMode.TASK,
            resources=ResourceRequest(num_cpus=0.25),
            allowed_methods=("describe", "sleep"),
            timeout_seconds=0.05,
        ),
        RuntimeProbeComponent,
    )


class FusionTraceContractMixin:
    collector: TraceCollector
    framework: FusionFramework
    backend: str

    def test_fake_chain_emits_correlated_terminal_trace(self) -> None:
        context = StringMetadata.from_mapping(
            {"trace_id": f"p5-{self.backend}", "run_id": "fake-run"}
        )
        secret = "must-not-appear-in-trace"
        quantum = self.framework.submit(
            "trace-quantum",
            "extract_features",
            {"opaque": secret},
            invocation_id=f"{self.backend}-q",
            trace_context=context,
        )
        classical = self.framework.submit(
            "trace-classical",
            "predict",
            quantum,
            invocation_id=f"{self.backend}-c",
            trace_context=context,
        )
        force = self.framework.submit(
            "trace-force",
            "calculate",
            classical,
            identity_energy,
            invocation_id=f"{self.backend}-f",
            trace_context=context,
        )

        result = self.framework.result(force)
        records = self.collector.snapshot()

        self.assertTrue(result.succeeded)
        self.assertEqual(len(records), 3)
        by_id = {record.invocation_id: record for record in records}
        self.assertEqual(
            by_id[f"{self.backend}-c"].dependencies,
            (f"{self.backend}-q",),
        )
        self.assertEqual(
            by_id[f"{self.backend}-f"].dependencies,
            (f"{self.backend}-c",),
        )
        self.assertTrue(
            all(record.status.value == "succeeded" for record in records)
        )
        self.assertTrue(
            all(record.trace_id == f"p5-{self.backend}" for record in records)
        )
        self.assertTrue(all(record.node_id for record in records))
        self.assertTrue(all(record.scheduled_at for record in records))
        self.assertTrue(all(record.started_at for record in records))
        self.assertTrue(all(record.finished_at for record in records))
        self.assertTrue(all(record.queue_seconds is not None for record in records))
        self.assertTrue(
            all(record.execution_seconds is not None for record in records)
        )
        if self.backend == "ray":
            self.assertTrue(all(record.task_id for record in records))
            self.assertIsNotNone(
                by_id[f"{self.backend}-c"].actor_id,
            )
        self.assertEqual(
            by_id[f"{self.backend}-q"].resources.custom_resources_dict(),
            {"QPU": 1.0},
        )

        exported = json.dumps(
            [record.as_dict() for record in records],
            sort_keys=True,
        )
        self.assertNotIn(secret, exported)

    def test_failure_cancel_and_timeout_are_terminal_traces(self) -> None:
        cases = (
            ("failed", "trace-failing", "fail", (), "failed"),
            ("cancelled", "trace-cancelling", "cancel", (), "cancelled"),
            ("timed-out", "trace-timeout", "sleep", (0.2,), "timed_out"),
        )
        for prefix, component_id, method, args, status in cases:
            with self.subTest(status=status):
                result = self.framework.invoke(
                    component_id,
                    method,
                    *args,
                    invocation_id=f"{self.backend}-{prefix}",
                )
                self.assertEqual(result.status.value, status)

        by_id = {
            record.invocation_id: record
            for record in self.collector.snapshot()
        }
        self.assertEqual(by_id[f"{self.backend}-failed"].status.value, "failed")
        self.assertEqual(
            by_id[f"{self.backend}-cancelled"].status.value,
            "cancelled",
        )
        self.assertEqual(
            by_id[f"{self.backend}-timed-out"].status.value,
            "timed_out",
        )


class LocalFusionTraceTest(
    FusionTraceContractMixin,
    unittest.TestCase,
):
    def setUp(self) -> None:
        reset_all_fakes()
        self.backend = "local"
        self.collector = TraceCollector()
        self.registry = ComponentRegistry()
        self.executor = LocalExecutor(
            self.registry,
            max_workers=4,
            max_pending=16,
            trace_collector=self.collector,
        )
        self.framework = FusionFramework(self.executor)
        _register_components(self.framework)

    def tearDown(self) -> None:
        self.framework.close()
        self.registry.close()


@unittest.skipIf(ray is None, "Ray is not installed in the editing environment")
class RayFusionTraceTest(
    FusionTraceContractMixin,
    unittest.TestCase,
):
    @classmethod
    def setUpClass(cls) -> None:
        assert ray is not None
        if ray.is_initialized():
            ray.shutdown()
        ray.init(
            num_cpus=2,
            resources={"QPU": 1},
            include_dashboard=False,
            log_to_driver=False,
            namespace=f"ray-quantum-p5-{uuid.uuid4().hex}",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        assert ray is not None
        if ray.is_initialized():
            ray.shutdown()

    def setUp(self) -> None:
        from pivotq._internal.executors import RayExecutor

        reset_all_fakes()
        self.backend = "ray"
        self.collector = TraceCollector()
        self.registry = ComponentRegistry()
        self.executor = RayExecutor(
            self.registry,
            actor_close_timeout_seconds=2.0,
            trace_collector=self.collector,
        )
        self.framework = FusionFramework(self.executor)
        _register_components(self.framework)

    def tearDown(self) -> None:
        self.framework.close()
        self.registry.close()


if __name__ == "__main__":
    unittest.main()
