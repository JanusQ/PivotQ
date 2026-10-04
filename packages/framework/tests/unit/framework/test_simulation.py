"""Simulation selects real implementations before execution and preserves provenance."""

from dataclasses import replace
import json

import pytest

from pivotq._internal.errors import UnavailableError, ValidationError
from pivotq._internal.executors import LocalExecutor
from pivotq._internal.framework import (
    ComponentRegistry, ComponentSpec, ExecutionMode, FusionFramework,
    InvocationSpec, ResourceRequest,
)
from pivotq._internal.framework.simulation import has_device_capacity
from pivotq._internal.models import StringMetadata
from pivotq._internal.observability import TraceCollector


class CpuCounter:
    def __init__(self):
        self.value = 0

    def describe(self):
        return {"device": "cpu"}

    def increment(self, amount=1):
        self.value += amount
        return self.value


class NativeCounter(CpuCounter):
    def increment(self, amount=1):
        return 100 + super().increment(amount)


class FailingNative(CpuCounter):
    def increment(self, amount=1):
        raise RuntimeError("device submitted a job and response failed")


def spec(component_id="accelerated", mode=ExecutionMode.TASK):
    return ComponentSpec(component_id, mode, ResourceRequest(num_gpus=1),
                         ("increment",), stateful=mode is ExecutionMode.ACTOR)


@pytest.fixture
def build_framework():
    stack = []

    def build(*, simulation=True, collector=None):
        registry = ComponentRegistry()
        executor = LocalExecutor(registry, trace_collector=collector)
        framework = FusionFramework(executor, simulation=simulation)
        stack.append((framework, registry))
        return framework

    yield build
    for framework, registry in reversed(stack):
        framework.close()
        registry.close()


def install(framework, *, availability=None, mode=ExecutionMode.TASK, factory=NativeCounter):
    framework.register(spec(mode=mode), factory)
    framework.register_simulation_adapter(
        "accelerated", factory=CpuCounter, resources=ResourceRequest(),
        required_devices=("GPU",), availability=availability,
    )


def test_false_does_not_probe_or_substitute_or_change_trace(build_framework):
    trace = TraceCollector()
    framework = build_framework(simulation=False, collector=trace)
    def must_not_probe():
        raise AssertionError("disabled simulation must not inspect hardware")
    install(framework, availability=must_not_probe)
    assert framework.invoke("accelerated", "increment", invocation_id="native").value == 101
    assert framework.resolve_execution("accelerated").reason == "simulation_disabled"
    assert trace.snapshot()[0].trace_context.as_dict() == {}
    assert framework.registry.get("accelerated").factory is NativeCounter


@pytest.mark.parametrize("mode", [ExecutionMode.TASK, ExecutionMode.ACTOR])
def test_cpu_substitution_preserves_requested_spec_and_actual_trace(build_framework, mode):
    collector = TraceCollector()
    framework = build_framework(collector=collector)
    install(framework, mode=mode)
    assert framework.invoke("accelerated", "increment", 3, invocation_id="cpu").value == 3
    selection = framework.execution_selection("accelerated")
    assert selection.simulated
    assert selection.requested_devices == ("GPU",)
    assert selection.actual_devices == ("CPU",)
    assert framework.describe("accelerated").resources.num_gpus == 1
    assert framework.registry.get("accelerated").spec.resources.num_gpus == 0
    trace = collector.snapshot()[0]
    assert trace.resources.num_gpus == 0
    metadata = trace.trace_context.as_dict()
    assert metadata["simulation.simulated"] == "true"
    assert json.loads(metadata["simulation.requested_resources"])["num_gpus"] == 1
    assert json.loads(metadata["simulation.actual_devices"]) == ["CPU"]
    assert framework.execution_report()["selections"][0] == selection.as_dict()


def test_actor_selection_is_pinned_across_availability_change(build_framework):
    framework = build_framework()
    probes = []
    present = [False]
    def probe():
        probes.append(1)
        return present[0]
    install(framework, availability=probe, mode=ExecutionMode.ACTOR)
    assert framework.invoke("accelerated", "increment", invocation_id="first").value == 1
    present[0] = True
    assert framework.invoke("accelerated", "increment", invocation_id="second").value == 2
    assert probes == [1]
    with pytest.raises(ValidationError, match="after execution selection"):
        framework.register_simulation_adapter("accelerated", factory=NativeCounter, resources=ResourceRequest())


def test_configured_hardware_failure_never_retries_cpu(build_framework):
    framework = build_framework()
    framework._executor.resource_capacities = lambda: ({"CPU": 8, "GPU": 1},)
    install(framework, availability=lambda: True, factory=FailingNative)
    result = framework.invoke("accelerated", "increment", invocation_id="failed-native")
    assert not result.succeeded
    assert framework.execution_selection("accelerated").simulated is False
    assert framework.registry.get("accelerated").factory is FailingNative


def test_missing_device_without_adapter_fails_before_construction(build_framework):
    framework = build_framework()
    framework.register(spec(), NativeCounter)
    with pytest.raises(UnavailableError, match="no simulation adapter"):
        framework.submit("accelerated", "increment", invocation_id="unsupported")
    assert framework.execution_selection("accelerated") is None


def test_callback_error_and_non_boolean_do_not_mean_hardware_absent(build_framework):
    for probe in (lambda: 0, lambda: (_ for _ in ()).throw(RuntimeError("inventory error"))):
        framework = build_framework()
        install(framework, availability=probe)
        with pytest.raises((TypeError, RuntimeError)):
            framework.resolve_execution("accelerated")
        assert framework.registry.get("accelerated").factory is NativeCounter
        assert framework.execution_selection("accelerated") is None


def test_external_qpu_keeps_logical_device_even_with_cpu_only_placement(build_framework):
    framework = build_framework()
    framework.register(replace(spec("qpu"), resources=ResourceRequest()), NativeCounter)
    framework.register_simulation_adapter(
        "qpu", factory=CpuCounter, resources=ResourceRequest(),
        required_devices=("QPU",), availability=lambda: False, backend="qiskit-statevector",
    )
    selection = framework.resolve_execution("qpu")
    assert selection.requested_devices == ("QPU",)
    assert selection.requested_resources == selection.effective_resources
    assert selection.backend == "qiskit-statevector"
    assert selection.simulated


@pytest.mark.parametrize("resources, expected_simulated", [
    (ResourceRequest(), False),
    (ResourceRequest(custom_resources={"qpu_device_missing": 1}), True),
])
def test_configured_http_qpu_still_checks_explicit_placement(build_framework, resources, expected_simulated):
    framework = build_framework()
    framework.register(replace(spec("qpu"), resources=resources), NativeCounter)
    framework.register_simulation_adapter(
        "qpu", factory=CpuCounter, resources=ResourceRequest(),
        required_devices=("QPU",), availability=lambda: True,
    )
    assert framework.resolve_execution("qpu").simulated is expected_simulated


def test_graph_uses_selected_implementations_and_preserves_dependencies(build_framework):
    framework = build_framework()
    install(framework)
    first = InvocationSpec("first", "accelerated", "increment", args=(4,))
    from pivotq._internal.framework import ResultRef
    second = InvocationSpec("second", "accelerated", "increment", args=(ResultRef("first"),))
    handles = framework.submit_graph((second, first))
    assert [framework.result(handle).value for handle in handles] == [4, 4]


def test_capacity_respects_total_per_node_and_target_binding():
    request = ResourceRequest(num_gpus=1, custom_resources={"node:gpu": 1})
    installed = [{"CPU": 8, "GPU": 1, "node:gpu": 1}]
    assert has_device_capacity(request, ("GPU",), installed)
    assert not has_device_capacity(request, ("GPU",), [{"CPU": 8, "GPU": 1, "node:other": 1}])
    assert not has_device_capacity(ResourceRequest(num_gpus=2), ("GPU",),
                                   [{"CPU": 8, "GPU": 1}, {"CPU": 8, "GPU": 1}])


def test_busy_ray_gpu_keeps_native_selection_without_reading_idle_resources(monkeypatch):
    import ray
    from pivotq._internal.executors.ray import RayExecutor

    class InventoryExecutor(LocalExecutor):
        # Exercise the production Ray inventory path without starting Ray.
        resource_capacities = RayExecutor.resource_capacities

    def forbidden_idle_read():
        raise AssertionError("busy/idle resources must not decide simulation")

    monkeypatch.setattr(ray, "nodes", lambda: [
        {"Alive": True, "Resources": {"CPU": 4, "GPU": 1}},
    ])
    monkeypatch.setattr(ray, "available_resources", forbidden_idle_read)
    registry = ComponentRegistry()
    framework = FusionFramework(InventoryExecutor(registry), simulation=True)
    try:
        install(framework)
        selection = framework.resolve_execution("accelerated")
        assert selection.simulated is False
        assert selection.reason == "hardware_available"
        assert framework.registry.get("accelerated").factory is NativeCounter
    finally:
        framework.close()
        registry.close()


def test_framework_owned_provenance_overrides_conflicting_caller_metadata(build_framework):
    collector = TraceCollector()
    framework = build_framework(collector=collector)
    install(framework)
    framework.invoke("accelerated", "increment", invocation_id="provenance",
                     trace_context=StringMetadata.from_mapping({"simulation.simulated": "false"}))
    assert framework.execution_selection("accelerated").simulated
    assert collector.snapshot()[0].trace_context.as_dict()["simulation.simulated"] == "true"


def test_report_survives_close_and_does_not_capture_payloads(build_framework):
    framework = build_framework()
    install(framework)
    framework.resolve_execution("accelerated")
    framework.close()
    framework.registry.close()
    assert framework.execution_report()["selections"][0]["simulated"] is True
