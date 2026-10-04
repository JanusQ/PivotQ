"""CLN-PY01-PY09: real Ray 2.31 types, with every transport action mocked."""

from dataclasses import FrozenInstanceError
import json
from unittest.mock import Mock, patch

import pytest
import ray
from ray.exceptions import GetTimeoutError, RayTaskError

from pivotq._internal.executors.cleanup import ExecutorCleanupError
from pivotq._internal.executors.ray import RayExecutor, _RayActorEntry
from pivotq._internal.framework import ComponentRegistry


@pytest.fixture(autouse=True)
def no_ray_service(monkeypatch):
    monkeypatch.setattr(ray, "init", Mock(side_effect=AssertionError("Ray startup forbidden")))
    monkeypatch.setattr(ray, "shutdown", Mock(side_effect=AssertionError("Ray shutdown forbidden")))
    monkeypatch.setattr(ray, "is_initialized", lambda: True)


def executor_with_actors(names):
    executor = RayExecutor(ComponentRegistry(), actor_close_timeout_seconds=2)
    actors = {}
    for name in names:
        handle = Mock()
        handle.close.remote.return_value = name
        actors[name] = handle
        executor._actors[name] = _RayActorEntry(
            name=f"ray-quantum-{'a' * 32}-{name}", handle=handle,
        )
    return executor, actors


def test_empty_actor_snapshot_is_clean():
    executor, _ = executor_with_actors([])
    with patch.object(ray, "get") as get, patch.object(ray, "kill") as kill:
        executor.close()
    assert executor.cleanup_report.outcome == "clean"
    assert executor.cleanup_report.as_dict()["total"] == 0
    get.assert_not_called()
    kill.assert_not_called()


@pytest.mark.parametrize("outcomes,expected", [
    ([None, None], "clean"),
    ([GetTimeoutError("secret"), None], "fallback_pending_verification"),
    ([RuntimeError("secret"), None], "failed"),
])
def test_actor_outcomes_order_actions_and_repeat_close(outcomes, expected):
    executor, actors = executor_with_actors(["z", "a"])
    with patch.object(ray, "get", side_effect=outcomes) as get, patch.object(ray, "kill") as kill, patch.object(ray, "cancel"):
        if expected == "clean":
            executor.close()
        else:
            with pytest.raises(ExecutorCleanupError) as raised:
                executor.close()
            assert raised.value.cleanup_report is executor.cleanup_report
        report = executor.cleanup_report
        executor.close()
    assert report.outcome == expected
    assert [r.component_id for r in report.records] == ["a", "z"]
    assert all(r.actor_id is None for r in report.records)
    assert get.call_count == kill.call_count == 2
    for handle in actors.values():
        handle.close.remote.assert_called_once_with()
    assert "secret" not in json.dumps(report.as_dict())
    with pytest.raises(FrozenInstanceError):
        report.records_complete = False
    copy = report.as_dict()
    copy["records"].clear()
    assert len(report.records) == 2


def test_timeout_during_remote_request_construction_is_not_a_wait_timeout():
    executor, actors = executor_with_actors(["a"])
    actors["a"].close.remote.side_effect = GetTimeoutError("secret")
    with patch.object(ray, "get") as get, patch.object(ray, "kill"), pytest.raises(ExecutorCleanupError):
        executor.close()
    get.assert_not_called()
    assert executor.cleanup_report.outcome == "failed"
    assert executor.cleanup_report.records[0].termination_mode == "fallback_after_error"


def test_termination_failure_is_recorded_even_after_successful_close():
    executor, _ = executor_with_actors(["a"])
    with patch.object(ray, "get"), patch.object(ray, "kill", side_effect=RuntimeError("secret")), pytest.raises(ExecutorCleanupError):
        executor.close()
    record = executor.cleanup_report.records[0]
    assert record.cooperative_state == "succeeded"
    assert record.termination_state == "failed"
    assert record.termination_error_type == "RuntimeError"
    assert executor.cleanup_report.as_dict()["termination_failed"] == 1


def test_remote_get_timeout_error_is_an_actor_failure_not_a_driver_wait_timeout():
    error = RayTaskError("close", "secret traceback", GetTimeoutError("secret")).as_instanceof_cause()
    assert isinstance(error, GetTimeoutError)
    executor, _ = executor_with_actors(["a"])
    with patch.object(ray, "get", side_effect=error), patch.object(ray, "kill"), patch.object(ray, "cancel"), pytest.raises(ExecutorCleanupError):
        executor.close()
    assert executor.cleanup_report.outcome == "failed"
    assert executor.cleanup_report.records[0].cooperative_state == "failed"
    assert executor.cleanup_report.records[0].termination_mode == "fallback_after_error"
    assert "secret" not in json.dumps(executor.cleanup_report.as_dict())


@pytest.mark.parametrize("count", [32, 33])
def test_actor_record_limit_does_not_skip_teardown(count):
    executor, _ = executor_with_actors([f"a-{n}" for n in range(count)])
    with patch.object(ray, "get"), patch.object(ray, "kill") as kill:
        if count == 32:
            executor.close()
        else:
            with pytest.raises(ExecutorCleanupError):
                executor.close()
    assert kill.call_count == count
    assert len(executor.cleanup_report.records) == 32
    assert executor.cleanup_report.records_complete == (count == 32)


def test_public_ray_api_version_and_timeout_type():
    assert ray.__version__ == "2.31.0"
    assert issubclass(GetTimeoutError, ray.exceptions.RayError)
    assert not any(not name.startswith("_") and "actor_id" in name for name in dir(ray.actor.ActorHandle))
