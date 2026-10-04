"""Unit tests for external component structural contracts."""

from __future__ import annotations

import unittest

from pivotq._internal.framework.component import (
    ComponentAdapter,
    ComponentFactory,
    validate_component_factory,
    validate_component_instance,
    validate_invocation,
)
from pivotq._internal.framework.models import (
    ComponentSpec,
    ExecutionMode,
    InvocationSpec,
    ResourceRequest,
)


class ScreenshotStyleComponent:
    def describe(self) -> dict[str, object]:
        return {"kind": "test-only"}

    def extract_features(self, request: object) -> object:
        return request


class MissingBusinessMethod:
    def describe(self) -> dict[str, object]:
        return {}


class NonCallableBusinessMethod:
    extract_features = "not-callable"

    def describe(self) -> dict[str, object]:
        return {}


class MissingDescribe:
    def extract_features(self, request: object) -> object:
        return request


def _spec() -> ComponentSpec:
    return ComponentSpec(
        component_id="quantum_features",
        execution=ExecutionMode.ACTOR,
        resources=ResourceRequest(custom_resources={"QPU": 1}),
        allowed_methods=("describe", "extract_features"),
        stateful=True,
    )


class ComponentProtocolTest(unittest.TestCase):
    def test_valid_factory_and_instance_pass_without_method_calls(self) -> None:
        instance = ScreenshotStyleComponent()

        factory = validate_component_factory(ScreenshotStyleComponent)
        validated = validate_component_instance(_spec(), instance)

        self.assertIs(factory, ScreenshotStyleComponent)
        self.assertIs(validated, instance)
        self.assertIsInstance(factory, ComponentFactory)
        self.assertIsInstance(instance, ComponentAdapter)

    def test_factory_validation_does_not_construct_component(self) -> None:
        calls = 0

        def factory() -> ScreenshotStyleComponent:
            nonlocal calls
            calls += 1
            return ScreenshotStyleComponent()

        validate_component_factory(factory)

        self.assertEqual(calls, 0)

    def test_invalid_factory_and_instances_are_rejected(self) -> None:
        invalid_instances = [
            None,
            MissingBusinessMethod(),
            NonCallableBusinessMethod(),
            MissingDescribe(),
        ]
        with self.assertRaises(TypeError):
            validate_component_factory(object())

        for instance in invalid_instances:
            with self.subTest(instance=instance), self.assertRaises(TypeError):
                validate_component_instance(_spec(), instance)

    def test_invocation_must_target_an_allowed_component_method(self) -> None:
        spec = _spec()
        invocation = InvocationSpec(
            "invoke-01",
            spec.component_id,
            "extract_features",
            args=({"opaque": True},),
        )

        self.assertIs(validate_invocation(spec, invocation), invocation)

        invalid_invocations = [
            InvocationSpec("invoke-02", "other_component", "extract_features"),
            InvocationSpec("invoke-03", spec.component_id, "close"),
        ]
        for invalid in invalid_invocations:
            with self.subTest(invocation=invalid), self.assertRaises(ValueError):
                validate_invocation(spec, invalid)

    def test_validation_helpers_require_contract_types(self) -> None:
        invocation = InvocationSpec(
            "invoke-01",
            "quantum_features",
            "describe",
        )
        with self.assertRaises(TypeError):
            validate_component_instance(object(), ScreenshotStyleComponent())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            validate_invocation(_spec(), object())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            validate_invocation(object(), invocation)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
