"""Unit tests for Ray Trace v2 wiring that do not initialize Ray."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from pivotq._internal.executors.ray import (
    _create_trace_event_sink,
    _finalize_trace_event_sink,
    _send_trace_event,
)
from pivotq._internal.framework.models import (
    ComponentSpec,
    ExecutionMode,
    InvocationSpec,
    InvocationStatus,
    ResourceRequest,
)
from pivotq._internal.observability.events import (
    TraceEventJournalConfig,
    TraceEventKind,
    TraceEventSource,
)


class _RemoteMethod:
    def __init__(self) -> None:
        self.arguments: list[object] = []
        self.return_value = object()

    def remote(self, argument: object = None) -> object:
        self.arguments.append(argument)
        return self.return_value


class _Sink:
    def __init__(self) -> None:
        self.record = _RemoteMethod()
        self.finalize = _RemoteMethod()


class _RuntimeId:
    def hex(self) -> str:
        return "abc123"


class _RuntimeContext:
    def get_node_id(self) -> _RuntimeId:
        return _RuntimeId()


class _ActorFactory:
    options_seen: dict[str, object] | None = None
    config_seen: TraceEventJournalConfig | None = None
    handle = object()

    @classmethod
    def options(cls, **kwargs: object):
        cls.options_seen = dict(kwargs)
        return cls

    @classmethod
    def remote(cls, config: TraceEventJournalConfig) -> object:
        cls.config_seen = config
        return cls.handle


def _component() -> ComponentSpec:
    return ComponentSpec(
        component_id="component",
        execution=ExecutionMode.TASK,
        resources=ResourceRequest(num_cpus=1),
        allowed_methods=("run",),
    )


def _invocation() -> InvocationSpec:
    return InvocationSpec(
        invocation_id="invocation",
        component_id="component",
        method="run",
    )


class RayTraceEventWiringTest(unittest.TestCase):
    def test_send_is_payload_free_and_fail_open(self) -> None:
        sink = _Sink()

        _send_trace_event(
            sink,
            _invocation(),
            _component(),
            event=TraceEventKind.STARTED,
            source=TraceEventSource.WORKER,
            status=InvocationStatus.RUNNING,
            run_id="run-1",
            task_id="task-1",
            node_id="node-1",
        )

        self.assertEqual(len(sink.record.arguments), 1)
        event = sink.record.arguments[0]
        self.assertEqual(event.run_id, "run-1")
        self.assertEqual(event.task_id, "task-1")
        self.assertEqual(event.node_id, "node-1")

        broken = Mock()
        broken.record.remote.side_effect = RuntimeError("trace unavailable")
        _send_trace_event(
            broken,
            _invocation(),
            _component(),
            event=TraceEventKind.STARTED,
            source=TraceEventSource.WORKER,
            status=InvocationStatus.RUNNING,
            run_id="run-1",
        )

    def test_sink_is_zero_cpu_and_pinned_to_driver_node(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config = TraceEventJournalConfig(
                run_id="run-1",
                event_path=root / "events.jsonl",
                manifest_path=root / "manifest.json",
            )
            _ActorFactory.options_seen = None
            _ActorFactory.config_seen = None
            with (
                patch(
                    "pivotq._internal.executors.ray.ray.get_runtime_context",
                    return_value=_RuntimeContext(),
                ),
                patch(
                    "pivotq._internal.executors.ray._TraceEventJournalActor",
                    _ActorFactory,
                ),
            ):
                handle = _create_trace_event_sink(config)

        self.assertIs(handle, _ActorFactory.handle)
        self.assertIs(_ActorFactory.config_seen, config)
        self.assertEqual(_ActorFactory.options_seen["num_cpus"], 0)
        self.assertEqual(_ActorFactory.options_seen["max_restarts"], 1)
        strategy = _ActorFactory.options_seen["scheduling_strategy"]
        self.assertEqual(strategy.node_id, "abc123")
        self.assertFalse(strategy.soft)

    def test_finalize_waits_boundedly_and_kills_sink_without_propagating(self) -> None:
        sink = _Sink()
        with (
            patch("pivotq._internal.executors.ray.ray.get") as ray_get,
            patch("pivotq._internal.executors.ray.ray.kill") as ray_kill,
        ):
            _finalize_trace_event_sink(sink, timeout_seconds=2.5)

        ray_get.assert_called_once_with(
            sink.finalize.return_value,
            timeout=2.5,
        )
        ray_kill.assert_called_once_with(sink, no_restart=True)

        broken = Mock()
        broken.finalize.remote.side_effect = RuntimeError("unavailable")
        with patch("pivotq._internal.executors.ray.ray.kill", side_effect=RuntimeError):
            _finalize_trace_event_sink(broken, timeout_seconds=1)


if __name__ == "__main__":
    unittest.main()
