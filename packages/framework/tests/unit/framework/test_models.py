"""Unit tests for framework component, resource, and invocation models."""

from __future__ import annotations

import importlib
import pickle
import sys
import threading
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from pivotq._internal.errors import ExecutionError, TimeoutError
from pivotq._internal.framework.models import (
    ComponentSpec,
    ExecutionMode,
    InvocationHandle,
    InvocationResult,
    InvocationSpec,
    InvocationStatus,
    ResourceRequest,
)
from pivotq._internal.models import StringMetadata


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def _resources() -> ResourceRequest:
    return ResourceRequest(
        num_cpus=0.5,
        num_gpus=0.25,
        custom_resources={"QPU": 1, "accelerator_type:test": 0.01},
    )


def _component_spec() -> ComponentSpec:
    return ComponentSpec(
        component_id="quantum_features",
        execution=ExecutionMode.ACTOR,
        resources=_resources(),
        allowed_methods=["describe", "extract_features"],
        stateful=True,
        timeout_seconds=30,
        metadata=StringMetadata.from_mapping({"owner": "external"}),
    )


class ResourceRequestTest(unittest.TestCase):
    def test_resources_are_normalized_immutable_and_serializable(self) -> None:
        request = _resources()

        self.assertEqual(request.num_cpus, 0.5)
        self.assertEqual(
            request.custom_resources,
            (("QPU", 1.0), ("accelerator_type:test", 0.01)),
        )
        copied = request.custom_resources_dict()
        copied["QPU"] = 2
        self.assertEqual(request.custom_resources_dict()["QPU"], 1.0)
        self.assertEqual(pickle.loads(pickle.dumps(request)), request)
        with self.assertRaises(FrozenInstanceError):
            request.num_cpus = 2  # type: ignore[misc]

    def test_fractional_non_qpu_resources_are_supported(self) -> None:
        request = ResourceRequest(
            num_cpus=0.125,
            num_gpus=0.5,
            custom_resources={"shared_capacity": 0.25},
        )

        self.assertEqual(request.custom_resources_dict()["shared_capacity"], 0.25)

    def test_fractional_physical_qpu_resources_are_rejected(self) -> None:
        invalid_resources = [
            {"QPU": 0.5},
            {"qpu_device_lab_01": 1.5},
        ]
        for resources in invalid_resources:
            with self.subTest(resources=resources), self.assertRaises(ValueError):
                ResourceRequest(custom_resources=resources)

    def test_invalid_resources_are_rejected(self) -> None:
        invalid_calls = [
            lambda: ResourceRequest(num_cpus=-1),
            lambda: ResourceRequest(num_gpus=float("nan")),
            lambda: ResourceRequest(num_cpus=float("inf")),
            lambda: ResourceRequest(num_cpus=True),
            lambda: ResourceRequest(custom_resources={"QPU": 0}),
            lambda: ResourceRequest(custom_resources={"GPU": 1}),
            lambda: ResourceRequest(custom_resources={" spaced ": 1}),
            lambda: ResourceRequest(
                custom_resources=(("duplicate", 1), ("duplicate", 2))
            ),
            lambda: ResourceRequest(schema_version=0),
        ]
        for call in invalid_calls:
            with self.subTest(call=call), self.assertRaises((TypeError, ValueError)):
                call()


class ComponentSpecTest(unittest.TestCase):
    def test_screenshot_style_components_can_be_described(self) -> None:
        method_sets = {
            "quantum_features": ("describe", "extract_features"),
            "classical_potential": (
                "describe",
                "fit",
                "predict",
                "save_checkpoint",
                "load_checkpoint",
            ),
            "force_calculator": ("describe", "calculate"),
        }

        for component_id, methods in method_sets.items():
            with self.subTest(component_id=component_id):
                spec = ComponentSpec(
                    component_id=component_id,
                    execution=ExecutionMode.ACTOR,
                    resources=ResourceRequest(),
                    allowed_methods=methods,
                )
                self.assertEqual(spec.allowed_methods, methods)
                self.assertEqual(pickle.loads(pickle.dumps(spec)), spec)

    def test_component_spec_is_normalized_and_immutable(self) -> None:
        spec = _component_spec()

        self.assertEqual(spec.allowed_methods, ("describe", "extract_features"))
        self.assertEqual(spec.timeout_seconds, 30.0)
        with self.assertRaises(FrozenInstanceError):
            spec.component_id = "changed"  # type: ignore[misc]

    def test_stateful_component_requires_actor_execution(self) -> None:
        with self.assertRaises(ValueError):
            ComponentSpec(
                component_id="stateful_task",
                execution=ExecutionMode.TASK,
                resources=ResourceRequest(),
                allowed_methods=("describe",),
                stateful=True,
            )

    def test_invalid_component_specs_are_rejected(self) -> None:
        base = {
            "component_id": "component",
            "execution": ExecutionMode.TASK,
            "resources": ResourceRequest(),
            "allowed_methods": ("describe",),
        }
        invalid_overrides = [
            {"component_id": " component"},
            {"component_id": "component/child"},
            {"execution": "task"},
            {"resources": {}},
            {"allowed_methods": ()},
            {"allowed_methods": ("_private",)},
            {"allowed_methods": ("describe", "describe")},
            {"max_concurrency": 0},
            {"max_concurrency": True},
            {"timeout_seconds": 0},
            {"timeout_seconds": float("inf")},
            {"stateful": 1},
            {"metadata": {}},
        ]
        for override in invalid_overrides:
            with self.subTest(override=override), self.assertRaises(
                (TypeError, ValueError)
            ):
                ComponentSpec(**(base | override))  # type: ignore[arg-type]


class InvocationSpecTest(unittest.TestCase):
    def test_opaque_arguments_dependencies_deadline_and_trace_are_frozen(self) -> None:
        local_time = datetime(
            2026,
            7,
            25,
            20,
            1,
            tzinfo=timezone(timedelta(hours=8)),
        )
        invocation = InvocationSpec(
            invocation_id="invoke-02",
            component_id="classical_potential",
            method="predict",
            args=[{"opaque": [1, 2]}],
            kwargs={"mode": "external"},
            dependencies=["invoke-01"],
            deadline=local_time,
            trace_context=StringMetadata.from_mapping({"trace_id": "trace-01"}),
        )

        self.assertEqual(invocation.args, ({"opaque": [1, 2]},))
        self.assertEqual(invocation.kwargs, (("mode", "external"),))
        self.assertEqual(invocation.kwargs_dict(), {"mode": "external"})
        self.assertEqual(
            invocation.deadline,
            datetime(2026, 7, 25, 12, 1, tzinfo=timezone.utc),
        )
        self.assertFalse(invocation.is_expired(NOW))
        self.assertTrue(invocation.is_expired(invocation.deadline))
        self.assertEqual(pickle.loads(pickle.dumps(invocation)), invocation)

    def test_naive_deadline_and_unserializable_input_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            InvocationSpec(
                "invoke-01",
                "component",
                "describe",
                deadline=datetime(2026, 7, 25, 12, 0),
            )
        with self.assertRaises(ValueError):
            InvocationSpec(
                "invoke-01",
                "component",
                "describe",
                args=(threading.Lock(),),
            )

    def test_invalid_invocations_are_rejected(self) -> None:
        invalid_calls = [
            lambda: InvocationSpec("bad id", "component", "describe"),
            lambda: InvocationSpec("invoke-01", "bad/component", "describe"),
            lambda: InvocationSpec("invoke-01", "component", "_private"),
            lambda: InvocationSpec(
                "invoke-01",
                "component",
                "describe",
                dependencies=("invoke-01",),
            ),
            lambda: InvocationSpec(
                "invoke-01",
                "component",
                "describe",
                dependencies=("invoke-00", "invoke-00"),
            ),
            lambda: InvocationSpec(
                "invoke-01",
                "component",
                "describe",
                kwargs=(("value", 1), ("value", 2)),
            ),
            lambda: InvocationSpec(
                "invoke-01",
                "component",
                "describe",
                trace_context={},
            ),
        ]
        for call in invalid_calls:
            with self.subTest(call=call), self.assertRaises((TypeError, ValueError)):
                call()


class InvocationBoundaryTest(unittest.TestCase):
    def test_handle_and_success_result_are_serializable(self) -> None:
        handle = InvocationHandle(
            invocation_id="invoke-01",
            component_id="component",
            reference=("local-token", 1),
        )
        result = InvocationResult(
            invocation_id=handle.invocation_id,
            component_id=handle.component_id,
            status=InvocationStatus.SUCCEEDED,
            value={"opaque-result": [1, 2]},
        )

        self.assertTrue(result.succeeded)
        self.assertEqual(pickle.loads(pickle.dumps(handle)), handle)
        self.assertEqual(pickle.loads(pickle.dumps(result)), result)

    def test_failure_and_timeout_results_use_structured_errors(self) -> None:
        cases = [
            (
                InvocationStatus.FAILED,
                ExecutionError(
                    "external component failed",
                    framework_job_id="invoke-01",
                ),
            ),
            (
                InvocationStatus.TIMED_OUT,
                TimeoutError(
                    "deadline exceeded",
                    framework_job_id="invoke-01",
                ),
            ),
        ]
        for status, error in cases:
            with self.subTest(status=status):
                result = InvocationResult(
                    "invoke-01",
                    "component",
                    status,
                    error=error,
                )
                self.assertFalse(result.succeeded)
                restored = pickle.loads(pickle.dumps(result))
                self.assertEqual(
                    restored.error.to_record(include_message=True),
                    error.to_record(include_message=True),
                )

    def test_invalid_handle_and_results_are_rejected(self) -> None:
        invalid_calls = [
            lambda: InvocationHandle("invoke-01", "component", None),
            lambda: InvocationHandle(
                "invoke-01",
                "component",
                threading.Lock(),
            ),
            lambda: InvocationResult(
                "invoke-01",
                "component",
                InvocationStatus.RUNNING,
            ),
            lambda: InvocationResult(
                "invoke-01",
                "component",
                InvocationStatus.SUCCEEDED,
                error=ExecutionError("unexpected"),
            ),
            lambda: InvocationResult(
                "invoke-01",
                "component",
                InvocationStatus.FAILED,
            ),
            lambda: InvocationResult(
                "invoke-01",
                "component",
                InvocationStatus.FAILED,
                value="partial",
                error=ExecutionError("failed"),
            ),
        ]
        for call in invalid_calls:
            with self.subTest(call=call), self.assertRaises((TypeError, ValueError)):
                call()

    def test_framework_import_does_not_import_ray(self) -> None:
        before = {
            name
            for name in sys.modules
            if name == "ray" or name.startswith("ray.")
        }

        importlib.import_module("pivotq._internal.framework")

        after = {
            name
            for name in sys.modules
            if name == "ray" or name.startswith("ray.")
        }
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
