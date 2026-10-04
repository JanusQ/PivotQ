"""Behavioral contract shared by LocalExecutor and RayExecutor."""

from __future__ import annotations

from typing import Any

from pivotq._internal.errors import ExecutionError, ValidationError
from pivotq._internal.framework import (
    ComponentSpec,
    ExecutionMode,
    InvocationSpec,
    InvocationStatus,
    ResourceRequest,
)
from tests.fixtures.fake_components import (
    FailingFakeComponent,
    FakeClassicalComponent,
    FakeForceComponent,
    FakeMarker,
    FakeQuantumComponent,
    RecordingFakeComponent,
    RuntimeProbeComponent,
    identity_energy,
)


def _spec(
    component_id: str,
    *,
    execution: ExecutionMode,
    allowed_methods: tuple[str, ...],
    resources: ResourceRequest | None = None,
    timeout_seconds: float | None = None,
) -> ComponentSpec:
    return ComponentSpec(
        component_id=component_id,
        execution=execution,
        resources=resources or ResourceRequest(),
        allowed_methods=allowed_methods,
        stateful=execution is ExecutionMode.ACTOR,
        timeout_seconds=timeout_seconds,
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


class ExecutorContractMixin:
    """Mixin whose subclasses provide fresh ``registry`` and ``executor``."""

    def test_contract_screenshot_method_shapes(self) -> None:
        self.registry.register(
            _spec(
                "contract-quantum",
                execution=ExecutionMode.ACTOR,
                allowed_methods=("describe", "extract_features"),
            ),
            FakeQuantumComponent,
        )
        self.registry.register(
            _spec(
                "contract-classical",
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
                "contract-force",
                execution=ExecutionMode.TASK,
                allowed_methods=("describe", "calculate"),
            ),
            FakeForceComponent,
        )
        payload = {"opaque": "payload"}
        invocations = (
            _invocation(
                "contract-q-1",
                "contract-quantum",
                "extract_features",
                args=(payload,),
            ),
            _invocation(
                "contract-c-1",
                "contract-classical",
                "fit",
                args=(payload,),
            ),
            _invocation(
                "contract-c-2",
                "contract-classical",
                "predict",
                args=(payload,),
            ),
            _invocation(
                "contract-c-3",
                "contract-classical",
                "save_checkpoint",
                args=("checkpoint.test",),
            ),
            _invocation(
                "contract-c-4",
                "contract-classical",
                "load_checkpoint",
                args=("checkpoint.test",),
            ),
            _invocation(
                "contract-f-1",
                "contract-force",
                "calculate",
                args=(payload, identity_energy),
            ),
        )

        results = tuple(self.executor.invoke(item) for item in invocations)

        self.assertTrue(all(result.succeeded for result in results))
        self.assertIsInstance(results[0].value, FakeMarker)
        self.assertEqual(results[0].value.payload, payload)
        self.assertIsInstance(results[4].value, FakeClassicalComponent)
        self.assertEqual(results[4].value.loaded_from, "checkpoint.test")
        self.assertIsInstance(results[5].value, FakeMarker)
        self.assertEqual(results[5].value.payload[0], payload)
        results[4].value.close()

    def test_contract_actor_state_and_task_instance_lifecycle(self) -> None:
        self.registry.register(
            _spec(
                "contract-stateful",
                execution=ExecutionMode.ACTOR,
                allowed_methods=("describe", "fit"),
            ),
            FakeClassicalComponent,
        )
        self.registry.register(
            _spec(
                "contract-task-probe",
                execution=ExecutionMode.TASK,
                allowed_methods=("describe", "instance_token"),
            ),
            RuntimeProbeComponent,
        )

        self.assertTrue(
            self.executor.invoke(
                _invocation(
                    "contract-state-1",
                    "contract-stateful",
                    "fit",
                    args=({"state": "set"},),
                )
            ).succeeded
        )
        actor_description = self.executor.invoke(
            _invocation(
                "contract-state-2",
                "contract-stateful",
                "describe",
            )
        )
        first_token = self.executor.invoke(
            _invocation(
                "contract-token-1",
                "contract-task-probe",
                "instance_token",
            )
        )
        second_token = self.executor.invoke(
            _invocation(
                "contract-token-2",
                "contract-task-probe",
                "instance_token",
            )
        )

        self.assertTrue(actor_description.succeeded)
        self.assertTrue(actor_description.value["fitted"])
        self.assertTrue(first_token.succeeded)
        self.assertTrue(second_token.succeeded)
        self.assertNotEqual(first_token.value, second_token.value)

    def test_contract_object_dependency_success_and_failure(self) -> None:
        self.registry.register(
            _spec(
                "contract-upstream",
                execution=ExecutionMode.TASK,
                allowed_methods=("describe", "record"),
            ),
            RecordingFakeComponent,
        )
        self.registry.register(
            _spec(
                "contract-failing",
                execution=ExecutionMode.TASK,
                allowed_methods=("describe", "fail"),
            ),
            FailingFakeComponent,
        )
        self.registry.register(
            _spec(
                "contract-downstream",
                execution=ExecutionMode.TASK,
                allowed_methods=("describe", "record"),
            ),
            RecordingFakeComponent,
        )

        upstream = self.executor.submit(
            _invocation(
                "contract-upstream-1",
                "contract-upstream",
                "record",
                args=("upstream",),
            )
        )
        downstream = self.executor.submit(
            _invocation(
                "contract-downstream-1",
                "contract-downstream",
                "record",
                args=("downstream",),
                dependencies=("contract-upstream-1",),
            )
        )
        failed = self.executor.submit(
            _invocation(
                "contract-failed-1",
                "contract-failing",
                "fail",
            )
        )
        blocked = self.executor.submit(
            _invocation(
                "contract-blocked-1",
                "contract-downstream",
                "record",
                args=("must-not-run",),
                dependencies=("contract-failed-1",),
            )
        )

        self.assertTrue(self.executor.result(upstream).succeeded)
        self.assertTrue(self.executor.result(downstream).succeeded)
        self.assertEqual(
            self.executor.result(failed).status,
            InvocationStatus.FAILED,
        )
        blocked_result = self.executor.result(blocked)
        self.assertEqual(blocked_result.status, InvocationStatus.FAILED)
        self.assertIsInstance(blocked_result.error, ExecutionError)

    def test_contract_async_result_and_release(self) -> None:
        self.registry.register(
            _spec(
                "contract-async",
                execution=ExecutionMode.TASK,
                allowed_methods=("describe", "process_id"),
            ),
            RuntimeProbeComponent,
        )
        handle = self.executor.submit(
            _invocation(
                "contract-async-1",
                "contract-async",
                "process_id",
            )
        )

        result = self.executor.result(handle)

        self.assertTrue(result.succeeded)
        self.assertIsInstance(result.value, int)
        self.executor.release(handle)
        with self.assertRaises(ValidationError):
            self.executor.result(handle)

    def test_contract_external_exception_is_structured(self) -> None:
        self.registry.register(
            _spec(
                "contract-error",
                execution=ExecutionMode.TASK,
                allowed_methods=("describe", "fail"),
            ),
            FailingFakeComponent,
        )

        result = self.executor.invoke(
            _invocation(
                "contract-error-1",
                "contract-error",
                "fail",
            )
        )

        self.assertEqual(result.status, InvocationStatus.FAILED)
        self.assertIsInstance(result.error, ExecutionError)
        self.assertNotIn("fixture failure", result.error.message)


__all__ = ["ExecutorContractMixin"]
