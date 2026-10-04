"""Public components, reusable workflows, completion control and reports."""

from dataclasses import fields
import json
import gc
import os
from pathlib import Path
import subprocess
import sys
import threading
import weakref
from unittest.mock import patch

import pytest

import pivotq as pq
from pivotq.errors import ExecutionError, ValidationError, TimeoutError


def identity(value):
    return value


class Counter:
    def __init__(self, value=0):
        self.value = value

    def add(self, value):
        self.value += value
        return self.value


class Payload:
    def __init__(self):
        self.data = bytearray(100_000)


def test_release_reclaims_business_payload_while_trace_remains():
    with pq.Runtime(trace=True) as runtime:
        ref = runtime.submit(Payload)
        value = runtime.get(ref)
        observed = weakref.ref(value)
        del value
        runtime.release(ref)
        gc.collect()
        assert observed() is None
        assert len(runtime.report().records) == 1


def test_workflow_mutable_literals_are_snapshotted_at_build_and_per_run():
    payload = bytearray(b"a")

    def mutate(value):
        before = bytes(value)
        value[0] = ord("z")
        return before

    workflow = pq.Workflow()
    out = workflow.task(mutate, payload)
    workflow.output("out", out)
    payload[0] = ord("b")
    with pq.Runtime() as runtime:
        for _ in range(2):
            run = runtime.run(workflow)
            assert runtime.get(run.outputs["out"]) == b"a"
            run.release()


def test_component_close_is_not_repeated_by_runtime_cleanup():
    closed = []

    class Closable(Counter):
        def close(self):
            closed.append(1)

    runtime = pq.Runtime()
    with runtime:
        actor = runtime.actor(Closable, methods=("add",))
        assert runtime.get(actor.submit("add", 1)) == 1
    runtime.close()
    assert closed == [1]


@pytest.mark.parametrize("options", [
    {"num_returns": True}, {"num_returns": 0}, {"num_returns": 2},
    {"timeout": True}, {"timeout": float("nan")}, {"timeout": -1},
])
def test_wait_rejects_invalid_counts_and_timeouts(options):
    with pq.Runtime() as runtime:
        ref = runtime.submit(identity, 1)
        with pytest.raises(ValueError):
            runtime.wait([ref], **options)


def test_components_wrap_plain_objects_and_actor_state_persists():
    with pq.Runtime() as runtime:
        task = runtime.register(pq.ComponentSpec("task-counter", ("add",)), Counter)
        actor = runtime.actor(Counter, 10, methods=("add",), name="counter")
        assert runtime.get(task.submit("add", 1)) == 1
        assert runtime.get(task.submit("add", 1)) == 1
        assert runtime.get(actor.submit("add", 1)) == 11
        assert runtime.get(actor.submit("add", 1)) == 12
        assert actor.describe().execution == "actor"
        with pytest.raises(ValidationError, match="already registered"):
            runtime.register(pq.ComponentSpec("counter", ("add",)), Counter)
        with pytest.raises(ValidationError, match="not allowed"):
            actor.submit("missing")
    assert not any("gpu" in field.name.lower() for field in fields(pq.ComponentSpec))


def make_workflow():
    workflow = pq.Workflow("fork-join")
    value = workflow.input("value")
    first = workflow.task(identity, value, name="first")
    left = workflow.task(lambda value: value * 2, first, name="left")
    right = workflow.task(lambda value: value + 1, first, name="right")
    merged = workflow.task(lambda values: sum(values["pair"]), {"pair": (left, right)}, name="join")
    counted = workflow.component("counter", "add", merged, name="count")
    workflow.output("count", counted)
    return workflow


def test_reusable_workflow_fork_join_actor_rebind_and_new_ids():
    workflow = make_workflow()
    with pq.Runtime(trace=True) as runtime:
        counter = runtime.actor(Counter, methods=("add",), name="counter")
        first = runtime.run(workflow, inputs={"value": 3}, bindings={"counter": counter})
        assert runtime.get(first.outputs["count"]) == 10
        second = runtime.run(workflow, inputs={"value": 3}, bindings={"counter": counter})
        assert runtime.get(second.outputs["count"]) == 20
        assert {ref._invocation_id for ref in first.refs}.isdisjoint(
            ref._invocation_id for ref in second.refs)
        first.release()
        second.release()
        assert not runtime._handles
        with pytest.raises(ValidationError, match="frozen"):
            workflow.task(identity, 1)
    with pq.Runtime() as another:
        counter = another.actor(Counter, methods=("add",))
        run = another.run(workflow, inputs={"value": 3}, bindings={"counter": counter})
        assert another.get(run.outputs["count"]) == 10
        run.release()


def test_workflow_validates_all_methods_before_any_node_executes():
    called = []
    workflow = pq.Workflow()
    first = workflow.task(lambda: called.append(1))
    bad = workflow.component("counter", "missing", first)
    workflow.output("out", bad)
    with pq.Runtime() as runtime:
        counter = runtime.actor(Counter, methods=("add",))
        with pytest.raises(ValidationError, match="not registered"):
            runtime.run(workflow, bindings={"counter": counter})
        assert called == []
        assert not runtime._handles


def test_workflow_rejects_foreign_refs_inputs_and_bindings():
    workflow, other = pq.Workflow(), pq.Workflow()
    ref = other.task(identity, 1)
    with pytest.raises(ValidationError, match="this workflow"):
        workflow.task(identity, ref)
    workflow = make_workflow()
    with pq.Runtime() as left, pq.Runtime() as right:
        counter = left.actor(Counter, methods=("add",))
        with pytest.raises(ValidationError, match="owned by this runtime"):
            right.run(workflow, inputs={"value": 1}, bindings={"counter": counter})
        with pytest.raises(ValidationError, match="ordinary pickle"):
            left.run(workflow, inputs={"value": left.submit(identity, 1)}, bindings={"counter": counter})


def test_serial_actor_nodes_have_deterministic_workflow_order():
    workflow = pq.Workflow()
    first = workflow.component("counter", "add", 2, name="first")
    second = workflow.component("counter", "add", 3, name="second")
    workflow.output("first", first)
    workflow.output("second", second)
    with pq.Runtime(trace=True) as runtime:
        counter = runtime.actor(Counter, methods=("add",))
        run = runtime.run(workflow, bindings={"counter": counter})
        assert runtime.get(run.outputs["first"]) == 2
        assert runtime.get(run.outputs["second"]) == 5
        traces = runtime.report().records
        first_trace = next(record for record in traces if record["trace_context"]["workflow.node"] == "first")
        second_trace = next(record for record in traces if record["trace_context"]["workflow.node"] == "second")
        assert first_trace["invocation_id"] in second_trace["dependencies"]


def test_partial_workflow_submission_exposes_accepted_refs_for_cleanup():
    workflow = pq.Workflow()
    first = workflow.task(identity, 1)
    second = workflow.task(identity, first)
    workflow.output("out", second)
    with pq.Runtime() as runtime:
        original = runtime._framework.submit_graph

        def fail_after_first(invocations):
            original(tuple(invocations)[:1])
            raise RuntimeError("submission interrupted")

        with patch.object(runtime._framework, "submit_graph", side_effect=fail_after_first):
            with pytest.raises(pq.WorkflowSubmissionError) as caught:
                runtime.run(workflow)
        partial = caught.value.partial_run
        assert len(partial.refs) == 1
        assert runtime.get(partial.refs[0]) == 1
        partial.release()


def test_wait_timeout_is_non_destructive_and_status_includes_failed_ready():
    finish = threading.Event()

    def blocked():
        assert finish.wait(5)
        return 5

    def fail():
        raise ValueError("expected")

    with pq.Runtime() as runtime:
        waiting = runtime.submit(blocked)
        try:
            assert runtime.status(waiting) is pq.InvocationStatus.PENDING
            assert runtime.wait([waiting], timeout=0) == ((), (waiting,))
            failed = runtime.submit(fail)
            ready, pending = runtime.wait([waiting, failed], timeout=2)
            assert ready == (failed,) and pending == (waiting,)
            assert runtime.status(failed) is pq.InvocationStatus.FAILED
            with pytest.raises(ExecutionError):
                runtime.get(failed)
            with pytest.raises(ValueError, match="duplicate"):
                runtime.wait([waiting, waiting])
        finally:
            finish.set()
        assert runtime.get(waiting) == 5
        assert runtime.status(waiting) is pq.InvocationStatus.SUCCEEDED
        runtime.release(failed, waiting)


def test_reports_survive_close_release_bound_retention_and_export(tmp_path):
    with pq.Runtime(trace=True, trace_max_records=2) as runtime:
        for value in range(4):
            ref = runtime.submit(identity, value)
            runtime.get(ref)
            runtime.release(ref)
        assert runtime.resources()["nodes"] == [{"num_cpus": 4.0}]
    report = runtime.report()
    assert report.closed and report.trace_enabled
    assert len(report.records) == 2 and report.dropped_records == 2
    assert all("num_gpus" not in item["resources"] for item in report.records)
    assert all("transfer" not in item["durations_seconds"] for item in report.records)
    assert all("observation_delay_seconds" in item for item in report.records)
    document = json.loads(report.export(tmp_path / "report.json").read_text())
    assert document["dropped_records"] == 2
    rows = report.export(tmp_path / "report.jsonl").read_text().splitlines()
    assert json.loads(rows[0])["type"] == "report"
    assert len(rows) == 3


def test_actual_system_example(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(root), env.get("PYTHONPATH")]))
    report = tmp_path / "system-report.json"
    result = subprocess.run(
        [sys.executable, "-B", str(root / "examples/system_workflow.py"), "--report-path", str(report)],
        env=env, cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["result"]["steps"] == 2
    assert output["trace_records"] == 6
    assert output["report_available_after_close"]
    records = json.loads(report.read_text())["records"]
    assert len({item["trace_context"]["workflow.id"] for item in records}) == 2


def test_component_deadline_is_independent_of_wait_timeout_and_metadata_is_reported():
    finish = threading.Event()

    class Slow:
        def run(self):
            finish.wait(5)
            return "payload-never-in-report"

    metadata = {"experiment": "timeout-case"}
    with pq.Runtime(trace=True) as runtime:
        component = runtime.register(pq.ComponentSpec(
            "slow", ("run",), timeout_seconds=0.05, metadata=metadata,
        ), Slow)
        metadata["experiment"] = "changed"
        ref = component.submit("run")
        try:
            ready, pending = runtime.wait([ref], timeout=2)
            assert ready == (ref,) and pending == ()
            assert runtime.status(ref) is pq.InvocationStatus.TIMED_OUT
            with pytest.raises(TimeoutError):
                runtime.get(ref)
        finally:
            finish.set()
    report = runtime.report()
    assert report.records[0]["trace_context"]["component.metadata.experiment"] == "timeout-case"
    assert "payload-never-in-report" not in json.dumps(report.as_dict())
