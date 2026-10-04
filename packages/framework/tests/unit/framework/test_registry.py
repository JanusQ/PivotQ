"""Unit tests for component registration and lookup."""

from __future__ import annotations

import unittest

from pivotq._internal.errors import UnavailableError, ValidationError
from pivotq._internal.framework import (
    ComponentRegistry,
    ComponentSpec,
    ExecutionMode,
    ResourceRequest,
)
from tests.fixtures.fake_components import (
    FakeQuantumComponent,
    reset_all_fakes,
)


def _spec(component_id: str) -> ComponentSpec:
    return ComponentSpec(
        component_id=component_id,
        execution=ExecutionMode.ACTOR,
        resources=ResourceRequest(custom_resources={"QPU": 1}),
        allowed_methods=("describe", "extract_features"),
        stateful=True,
    )


class ComponentRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_all_fakes()
        self.registry = ComponentRegistry()

    def tearDown(self) -> None:
        self.registry.close()

    def test_register_get_snapshot_and_unregister_do_not_call_factory(self) -> None:
        second = self.registry.register(
            _spec("component_b"),
            FakeQuantumComponent,
        )
        first = self.registry.register(
            _spec("component_a"),
            FakeQuantumComponent,
        )

        self.assertIs(self.registry.get("component_a"), first)
        self.assertEqual(
            self.registry.registrations(),
            (first, second),
        )
        self.assertEqual(FakeQuantumComponent.created_count, 0)
        self.assertIs(self.registry.unregister("component_a"), first)
        with self.assertRaises(ValidationError):
            self.registry.get("component_a")

    def test_duplicate_and_missing_components_are_rejected(self) -> None:
        self.registry.register(_spec("component"), FakeQuantumComponent)

        with self.assertRaises(ValidationError):
            self.registry.register(_spec("component"), FakeQuantumComponent)
        with self.assertRaises(ValidationError):
            self.registry.get("missing")
        with self.assertRaises(ValidationError):
            self.registry.unregister("missing")

    def test_invalid_registration_and_lookup_types_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            self.registry.register(object(), FakeQuantumComponent)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            self.registry.register(_spec("component"), object())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            self.registry.get(1)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            self.registry.get(" spaced ")

    def test_close_is_idempotent_and_rejects_future_operations(self) -> None:
        self.registry.register(_spec("component"), FakeQuantumComponent)

        self.registry.close()
        self.registry.close()

        self.assertTrue(self.registry.closed)
        with self.assertRaises(UnavailableError):
            self.registry.get("component")
        with self.assertRaises(UnavailableError):
            self.registry.registrations()
        with self.assertRaises(UnavailableError):
            self.registry.register(_spec("other"), FakeQuantumComponent)


if __name__ == "__main__":
    unittest.main()
