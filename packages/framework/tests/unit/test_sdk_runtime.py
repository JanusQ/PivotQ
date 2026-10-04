"""Behavioral tests for ordinary Python programs using the public SDK."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
import threading
from unittest.mock import patch

import pytest

from pivotq import ResultRef, Runtime
from pivotq.errors import ExecutionError, UnavailableError, ValidationError


def identity(value):
    return value


def test_cpu_program_dependencies_keywords_and_repeated_get():
    def reduce(values, *, device, invocation_id, dependencies, deadline):
        return sum(values["items"]) + device + invocation_id + dependencies + deadline

    with Runtime() as runtime:
        first = runtime.submit(lambda value: value * 2, 3)
        second = runtime.submit(reduce, {"items": [first, 4]}, kwargs={
            "device": 1, "invocation_id": 2, "dependencies": 3, "deadline": 4,
        })
        assert runtime.get(second) == runtime.get(second) == 20
        assert runtime.get(first) == 6
        runtime.release(second, first)
        with pytest.raises(ValidationError, match="released"):
            runtime.get(first)


def test_fork_join_resolves_shared_refs_in_nested_plain_containers():
    def double(value):
        return value * 2

    def increment(value):
        return value + 1

    def join(values):
        original, branches = values["bundle"]
        return original + branches[0] + branches[1]["right"] + branches[1]["source"]

    with Runtime() as runtime:
        source = runtime.submit(identity, 3)
        left = runtime.submit(double, source)
        right = runtime.submit(increment, source)
        merged = runtime.submit(join, {
            "bundle": (source, [left, {"right": right, "source": source}]),
        })
        assert runtime.get(merged) == runtime.get(merged) == 16
        assert (runtime.get(source), runtime.get(left), runtime.get(right)) == (3, 6, 4)
        runtime.release(merged, left, right, source)
        assert not runtime._handles
        assert not runtime._framework._handles
        assert not runtime._executor._entries
        for ref in (source, left, right, merged):
            with pytest.raises(ValidationError, match="released"):
                runtime.get(ref)


def test_reference_is_runtime_owned_and_not_a_transport_object():
    with Runtime() as left, Runtime() as right:
        ref = left.submit(identity, 1)
        with pytest.raises(ValidationError, match="different runtime"):
            right.submit(identity, [ref])
        with pytest.raises(ValidationError, match="different runtime"):
            right.get(ref)
        with pytest.raises(TypeError, match="runtime.get"):
            bool(ref)
        with pytest.raises(TypeError, match="owning runtime"):
            pickle.dumps(ref)
        forged = ResultRef(ref._runtime_id, ref._invocation_id)
        with pytest.raises(ValidationError, match="not owned"):
            left.get(forged)


@dataclass
class OpaqueRequest:
    value: object


def test_unsupported_reference_containers_fail_before_execution():
    with Runtime() as runtime:
        ref = runtime.submit(identity, 1)
        with pytest.raises(ValidationError, match="dictionary keys"):
            runtime.submit(identity, {(ref,): 0})
        with pytest.raises(ValueError, match="pickle-serializable"):
            runtime.submit(identity, OpaqueRequest(ref))
        with pytest.raises(ValueError, match="pickle-serializable"):
            runtime.submit(identity, {ref})


def test_registration_reuse_and_iterative_results_are_released():
    with Runtime() as runtime:
        for step in range(20):
            ref = runtime.submit(identity, step)
            assert runtime.get(ref) == step
            runtime.release(ref)
            assert not runtime._handles
            assert not runtime._framework._handles
            assert not runtime._executor._entries
        assert len(runtime._registry.registrations()) == 1
        ref = runtime.submit(identity, 3, num_cpus=0.5)
        assert runtime.get(ref) == 3
        assert len(runtime._registry.registrations()) == 2


def test_same_cpu_function_can_run_concurrently_locally():
    barrier = threading.Barrier(2)

    def synchronize(value):
        barrier.wait(timeout=5)
        return value

    with Runtime(max_workers=2) as runtime:
        first = runtime.submit(synchronize, 1)
        second = runtime.submit(synchronize, 2)
        assert (runtime.get(first), runtime.get(second)) == (1, 2)


def test_user_failure_raises_and_prevents_dependent_function():
    calls = []

    def fail():
        raise ValueError("deliberate")

    def downstream(value):
        calls.append(value)

    with Runtime() as runtime:
        failed = runtime.submit(fail)
        dependent = runtime.submit(downstream, failed)
        with pytest.raises(ExecutionError, match="ValueError"):
            runtime.get(failed)
        with pytest.raises(ExecutionError, match="dependency"):
            runtime.get(dependent)
        assert not calls
        runtime.release(dependent, failed)


def test_lazy_lifecycle_cleanup_and_closed_runtime():
    runtime = Runtime()
    assert runtime._framework is None
    with runtime:
        ref = runtime.submit(identity, 1)
        assert runtime.get(ref) == 1
    assert runtime.closed
    assert runtime._framework is runtime._executor is runtime._registry is None
    runtime.close()
    with pytest.raises(UnavailableError, match="closed"):
        runtime.get(ref)
    with pytest.raises(UnavailableError, match="closed"):
        runtime.submit(identity, 2)


def test_body_exception_survives_cleanup_failure():
    runtime = Runtime()
    with pytest.raises(ValueError, match="body") as caught:
        with runtime:
            with patch.object(runtime._framework, "close", side_effect=RuntimeError("cleanup")):
                try:
                    raise ValueError("body")
                except ValueError as error:
                    runtime.__exit__(ValueError, error, error.__traceback__)
                    raise
    assert any("cleanup" in note for note in caught.value.__notes__)
    assert runtime._registry is None


@pytest.mark.parametrize("quantity", [0, -1, True, float("nan"), float("inf"), "1"])
def test_invalid_cpu_quantities(quantity):
    with Runtime() as runtime:
        with pytest.raises(ValueError, match="num_cpus"):
            runtime.submit(identity, 1, num_cpus=quantity)


def test_impossible_local_resources_and_invalid_runtime_options():
    with Runtime(max_workers=2) as runtime:
        with pytest.raises(ValueError, match="max_workers"):
            runtime.submit(identity, 1, num_cpus=3)
    with pytest.raises(ValueError, match="address"):
        Runtime(address="auto")
    with pytest.raises(ValueError, match="max_workers"):
        Runtime(max_workers=0)


def test_async_and_generator_functions_are_rejected():
    async def async_fn():
        return 1

    def generator_fn():
        yield 1

    with Runtime() as runtime:
        for function in (async_fn, generator_fn):
            with pytest.raises(TypeError, match="synchronous"):
                runtime.submit(function)


def test_unfinished_result_cannot_be_released():
    finish = threading.Event()

    def wait():
        assert finish.wait(5)
        return 1

    with Runtime() as runtime:
        ref = runtime.submit(wait)
        try:
            with pytest.raises(ValidationError, match="still running"):
                runtime.release(ref)
        finally:
            finish.set()
        assert runtime.get(ref) == 1
        runtime.release(ref)


def test_actual_hybrid_example_runs_and_converges_locally():
    framework_root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [
        str(framework_root), environment.get("PYTHONPATH"),
    ]))
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", str(framework_root / "examples/hybrid_program.py")],
        cwd=framework_root, env=environment, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["is_simulated"] is True
    assert result["backend"] == "simulator"
    assert result["converged"] is True
    assert 1 < result["iterations"] <= 30
