"""Unit tests for P4 result references and invocation DAG validation."""

from __future__ import annotations

import pickle
import unittest

from pivotq._internal.errors import ExecutionError, ValidationError
from pivotq._internal.framework import (
    InvocationGraph,
    InvocationResult,
    InvocationSpec,
    InvocationStatus,
    ResultRef,
    resolve_result_references,
    result_ref_ids,
)


def _invocation(
    invocation_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    value: object = None,
) -> InvocationSpec:
    args = () if value is None else (value,)
    return InvocationSpec(
        invocation_id=invocation_id,
        component_id="graph-component",
        method="echo",
        args=args,
        dependencies=dependencies,
    )


class ResultReferenceTest(unittest.TestCase):
    def test_reference_is_validated_and_pickleable(self) -> None:
        reference = ResultRef("source-1")

        restored = pickle.loads(pickle.dumps(reference))

        self.assertEqual(restored, reference)
        for invalid in ("", " has-space", "_leading", "x" * 129):
            with self.subTest(invalid=invalid), self.assertRaises(
                (TypeError, ValueError)
            ):
                ResultRef(invalid)
        with self.assertRaises(TypeError):
            ResultRef(1)  # type: ignore[arg-type]

    def test_nested_references_are_resolved_without_copying_opaque_inputs(
        self,
    ) -> None:
        opaque = ["opaque", "payload"]
        dependency_value = {"external": "result"}
        dependency = InvocationResult(
            invocation_id="source-1",
            component_id="source",
            status=InvocationStatus.SUCCEEDED,
            value=dependency_value,
        )
        value = (
            opaque,
            {
                "nested": [
                    ResultRef("source-1"),
                    ResultRef("source-1"),
                ]
            },
        )

        resolved = resolve_result_references(value, (dependency,))

        self.assertIs(resolved[0], opaque)
        self.assertIs(resolved[1]["nested"][0], dependency_value)
        self.assertIs(resolved[1]["nested"][1], dependency_value)
        self.assertEqual(result_ref_ids(value), ("source-1",))

        unchanged = (opaque, {"plain": "value"})
        self.assertIs(resolve_result_references(unchanged, ()), unchanged)

    def test_invalid_reference_positions_and_missing_results_are_rejected(
        self,
    ) -> None:
        with self.assertRaises(ValidationError):
            result_ref_ids({ResultRef("source-1"): "value"})
        with self.assertRaises(ExecutionError):
            resolve_result_references(ResultRef("missing"), ())


class InvocationGraphTest(unittest.TestCase):
    def test_topological_order_is_stable_and_allows_external_roots(self) -> None:
        source = _invocation("source")
        middle = _invocation(
            "middle",
            dependencies=("source",),
            value=ResultRef("source"),
        )
        final = _invocation(
            "final",
            dependencies=("middle", "external"),
            value=ResultRef("middle"),
        )

        graph = InvocationGraph(
            (final, source, middle),
            external_dependencies=("external",),
        )

        self.assertEqual(
            tuple(
                invocation.invocation_id
                for invocation in graph.topological_order()
            ),
            ("source", "middle", "final"),
        )

    def test_cycle_is_rejected(self) -> None:
        first = _invocation(
            "first",
            dependencies=("second",),
            value=ResultRef("second"),
        )
        second = _invocation(
            "second",
            dependencies=("first",),
            value=ResultRef("first"),
        )

        with self.assertRaisesRegex(ValidationError, "cycle"):
            InvocationGraph((first, second))

    def test_missing_and_undeclared_dependencies_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "not present"):
            InvocationGraph(
                (_invocation("child", dependencies=("missing",)),)
            )
        with self.assertRaisesRegex(ValidationError, "also be declared"):
            InvocationGraph(
                (_invocation("child", value=ResultRef("source")),),
                external_dependencies=("source",),
            )

    def test_duplicate_invocations_are_rejected(self) -> None:
        invocation = _invocation("duplicate")

        with self.assertRaisesRegex(ValidationError, "appears twice"):
            InvocationGraph((invocation, invocation))


if __name__ == "__main__":
    unittest.main()
