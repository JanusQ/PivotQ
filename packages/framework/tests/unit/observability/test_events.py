"""Unit tests for the default-off Trace v2 event journal contract."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import unittest
import uuid

from pivotq._internal.framework.models import (
    ComponentSpec,
    ExecutionMode,
    InvocationSpec,
    InvocationStatus,
    ResourceRequest,
)
from pivotq._internal.models import StringMetadata
from pivotq._internal.observability.events import (
    TRACE_EVENT_MANIFEST_TYPE,
    TRACE_EVENT_RECORD_TYPE,
    TRACE_EVENT_SCHEMA_VERSION,
    TraceEventJournal,
    TraceEventJournalConfig,
    TraceEventKind,
    TraceEventSource,
    build_trace_event,
)


_AT = datetime(2026, 9, 5, 1, 2, 3, tzinfo=timezone.utc)


def _component() -> ComponentSpec:
    return ComponentSpec(
        component_id="electronic_structure",
        execution=ExecutionMode.TASK,
        resources=ResourceRequest(
            num_cpus=2,
            num_gpus=1,
            custom_resources={"QPU": 1},
        ),
        allowed_methods=("run",),
    )


def _invocation(
    invocation_id: str = "invocation-1",
    *,
    trace_context: dict[str, str] | None = None,
) -> InvocationSpec:
    return InvocationSpec(
        invocation_id=invocation_id,
        component_id="electronic_structure",
        method="run",
        trace_context=StringMetadata.from_mapping(trace_context or {}),
    )


def _event(
    event: TraceEventKind,
    status: InvocationStatus,
    *,
    invocation_id: str = "invocation-1",
    error_code: str | None = None,
):
    return build_trace_event(
        _invocation(invocation_id),
        _component(),
        event=event,
        source=TraceEventSource.DRIVER,
        status=status,
        backend="ray",
        occurred_at=_AT,
        error_code=error_code,
        run_id="run-1",
    )


class TraceEventModelTest(unittest.TestCase):
    def test_builds_payload_free_resource_and_execution_facts(self) -> None:
        invocation = _invocation(
            trace_context={
                "trace_id": "trace-1",
                "run_id": "untrusted-context-run",
                "phase": "electronic_structure",
                "aimd_step": "12",
                "invocation_index": "3",
                "step": "999",
            }
        )

        event = build_trace_event(
            invocation,
            _component(),
            event=TraceEventKind.STARTED,
            source=TraceEventSource.WORKER,
            status=InvocationStatus.RUNNING,
            backend="ray",
            occurred_at=_AT,
            task_id="task-1",
            node_id="node-1",
            duration_seconds=0.25,
            run_id="authoritative-run",
        )

        document = event.as_dict(cursor=7)
        self.assertEqual(document["schema_version"], TRACE_EVENT_SCHEMA_VERSION)
        self.assertEqual(document["record_type"], TRACE_EVENT_RECORD_TYPE)
        self.assertEqual(document["cursor"], 7)
        self.assertEqual(document["run_id"], "authoritative-run")
        self.assertEqual(document["trace_id"], "trace-1")
        self.assertEqual(document["aimd_step"], 12)
        self.assertEqual(document["invocation_index"], 3)
        self.assertEqual(document["phase"], "electronic_structure")
        self.assertEqual(document["execution_ids"]["node_id"], "node-1")
        self.assertEqual(document["requested_resources"]["num_cpus"], 2.0)
        self.assertEqual(document["requested_resources"]["num_gpus"], 1.0)
        self.assertEqual(
            document["requested_resources"]["custom_resources"],
            {"QPU": 1.0},
        )
        self.assertEqual(document["duration_seconds"], 0.25)
        self.assertNotIn("args", document)
        self.assertNotIn("kwargs", document)
        self.assertNotIn("value", document)

    def test_never_reinterprets_legacy_step_as_aimd_semantics(self) -> None:
        event = build_trace_event(
            _invocation(trace_context={"step": "8"}),
            _component(),
            event=TraceEventKind.SUBMITTED,
            source=TraceEventSource.DRIVER,
            status=InvocationStatus.QUEUED,
            backend="ray",
            occurred_at=_AT,
            run_id="run-1",
        )

        self.assertIsNone(event.aimd_step)
        self.assertIsNone(event.invocation_index)
        self.assertEqual(event.trace_context.as_dict(), {"step": "8"})

    def test_rejects_invalid_lifecycle_status_and_unstructured_error(self) -> None:
        with self.assertRaises(ValueError):
            _event(TraceEventKind.STARTED, InvocationStatus.SUCCEEDED)
        with self.assertRaises(ValueError):
            _event(TraceEventKind.FINISHED, InvocationStatus.FAILED)
        with self.assertRaises(ValueError):
            _event(
                TraceEventKind.FINISHED,
                InvocationStatus.SUCCEEDED,
                error_code="execution_failed",
            )


class TraceEventJournalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.output_dir = Path(f"tmp/trace-v2/{uuid.uuid4().hex}").resolve()
        self.output_dir.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, self.output_dir, True)

    def _config(self, *, max_records: int = 10) -> TraceEventJournalConfig:
        return TraceEventJournalConfig(
            run_id="run-1",
            event_path=self.output_dir / "run-1.trace-v2.jsonl",
            manifest_path=self.output_dir / "run-1.trace-v2.manifest.json",
            max_records=max_records,
        )

    def test_append_deduplicate_cursor_snapshot_and_finalize(self) -> None:
        config = self._config()
        journal = TraceEventJournal(config)
        submitted = _event(TraceEventKind.SUBMITTED, InvocationStatus.QUEUED)
        started = _event(TraceEventKind.STARTED, InvocationStatus.RUNNING)

        self.assertEqual(journal.record(submitted), 1)
        self.assertEqual(journal.record(submitted), 1)
        self.assertEqual(journal.record(started), 2)
        snapshot = journal.snapshot(after_cursor=1)
        self.assertEqual([item["cursor"] for item in snapshot], [2])
        snapshot[0]["execution_ids"]["node_id"] = "mutated"
        self.assertIsNone(journal.snapshot(after_cursor=1)[0]["execution_ids"]["node_id"])

        manifest = journal.finalize()
        data = Path(config.event_path).read_bytes()
        self.assertEqual(manifest["record_type"], TRACE_EVENT_MANIFEST_TYPE)
        self.assertEqual(manifest["record_count"], 2)
        self.assertEqual(manifest["last_cursor"], 2)
        self.assertTrue(manifest["complete"])
        self.assertFalse(manifest["truncated"])
        self.assertEqual(manifest["stream"]["size_bytes"], len(data))
        self.assertEqual(manifest["stream"]["sha256"], hashlib.sha256(data).hexdigest())
        on_disk = json.loads(Path(config.manifest_path).read_text(encoding="utf-8"))
        self.assertTrue(on_disk["complete"])
        with self.assertRaises(RuntimeError):
            journal.record(started)

    def test_reports_bounded_stream_truncation(self) -> None:
        journal = TraceEventJournal(self._config(max_records=1))

        self.assertEqual(
            journal.record(_event(TraceEventKind.SUBMITTED, InvocationStatus.QUEUED)),
            1,
        )
        self.assertIsNone(
            journal.record(_event(TraceEventKind.STARTED, InvocationStatus.RUNNING))
        )
        manifest = journal.manifest()
        self.assertEqual(manifest["record_count"], 1)
        self.assertEqual(manifest["dropped_count"], 1)
        self.assertTrue(manifest["truncated"])

    def test_recovers_incomplete_stream_and_preserves_idempotency(self) -> None:
        config = self._config()
        submitted = _event(TraceEventKind.SUBMITTED, InvocationStatus.QUEUED)
        first = TraceEventJournal(config)
        self.assertEqual(first.record(submitted), 1)

        recovered = TraceEventJournal(config)

        self.assertEqual(recovered.record(submitted), 1)
        self.assertEqual(
            recovered.record(_event(TraceEventKind.STARTED, InvocationStatus.RUNNING)),
            2,
        )
        self.assertTrue(recovered.manifest()["recovered"])

    def test_rejects_manifest_digest_mismatch_and_partial_tail(self) -> None:
        config = self._config()
        journal = TraceEventJournal(config)
        journal.record(_event(TraceEventKind.SUBMITTED, InvocationStatus.QUEUED))
        manifest_path = Path(config.manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["stream"]["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "sha256"):
            TraceEventJournal(config)

        manifest_path.unlink()
        with Path(config.event_path).open("ab") as stream:
            stream.write(b'{"partial":true}')
        with self.assertRaisesRegex(ValueError, "trailing"):
            TraceEventJournal(config)


if __name__ == "__main__":
    unittest.main()
