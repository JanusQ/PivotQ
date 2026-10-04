"""Unit tests for the minimal versioned trace schema and exporters."""

from __future__ import annotations

import importlib
import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import mock_open, patch

from pivotq._internal.framework import (
    ComponentSpec,
    ExecutionMode,
    InvocationResult,
    InvocationSpec,
    InvocationStatus,
    ResourceRequest,
)
from pivotq._internal.models import StringMetadata
from pivotq._internal.observability import (
    TRACE_SCHEMA_VERSION,
    TraceCollector,
    build_trace_record,
    export_trace_json,
    export_trace_jsonl,
    utc_now,
)


def _record(invocation_id: str = "trace-invocation-1"):
    submitted_at = utc_now()
    scheduled_at = submitted_at + timedelta(milliseconds=1)
    started_at = scheduled_at + timedelta(milliseconds=1)
    finished_at = started_at + timedelta(milliseconds=2)
    invocation = InvocationSpec(
        invocation_id,
        "trace-component",
        "execute",
        args=("secret-payload",),
        dependencies=("trace-upstream",),
        trace_context=StringMetadata.from_mapping(
            {"trace_id": "trace-workflow", "run_id": "run-1"}
        ),
    )
    component = ComponentSpec(
        component_id="trace-component",
        execution=ExecutionMode.TASK,
        resources=ResourceRequest(
            num_cpus=0.5,
            num_gpus=1,
            custom_resources={"QPU": 1},
        ),
        allowed_methods=("describe", "execute"),
    )
    result = InvocationResult(
        invocation_id=invocation_id,
        component_id="trace-component",
        status=InvocationStatus.SUCCEEDED,
        value={"opaque": "secret-result"},
    )
    return build_trace_record(
        invocation,
        component,
        result,
        backend="local",
        submitted_at=submitted_at,
        scheduled_at=scheduled_at,
        started_at=started_at,
        finished_at=finished_at,
        node_id="test-node",
    )


class TraceRecordTest(unittest.TestCase):
    def test_record_is_versioned_json_ready_and_contains_no_payload(self) -> None:
        record = _record()

        document = record.as_dict()
        encoded = json.dumps(document, sort_keys=True)

        self.assertEqual(document["schema_version"], TRACE_SCHEMA_VERSION)
        self.assertEqual(document["trace_id"], "trace-workflow")
        self.assertEqual(document["dependencies"], ["trace-upstream"])
        self.assertEqual(document["resources"]["custom_resources"], {"QPU": 1.0})
        self.assertEqual(document["status"], "succeeded")
        self.assertGreater(document["sizes_bytes"]["input"], 0)
        self.assertGreater(document["sizes_bytes"]["output"], 0)
        self.assertNotIn("secret-payload", encoded)
        self.assertNotIn("secret-result", encoded)

    def test_observation_copy_preserves_record_and_sets_transfer_time(self) -> None:
        record = _record()
        observed = record.observed(record.finished_at + timedelta(seconds=1))

        self.assertIsNone(record.result_observed_at)
        self.assertEqual(observed.transfer_seconds, 1.0)
        self.assertEqual(observed.invocation_id, record.invocation_id)

    def test_collector_is_bounded_and_replaces_same_invocation(self) -> None:
        collector = TraceCollector(max_records=2)
        first = _record("trace-1")
        collector.record(first)
        collector.record(first.observed())
        collector.record(_record("trace-2"))
        collector.record(_record("trace-3"))

        self.assertEqual(
            tuple(record.invocation_id for record in collector.snapshot()),
            ("trace-2", "trace-3"),
        )
        self.assertEqual(collector.dropped_records, 1)

    def test_invalid_collector_capacity_is_rejected(self) -> None:
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(
                (TypeError, ValueError)
            ):
                TraceCollector(max_records=value)  # type: ignore[arg-type]


class TraceExporterTest(unittest.TestCase):
    def test_json_and_jsonl_export_versioned_records(self) -> None:
        collector = TraceCollector()
        collector.record(_record("trace-1"))
        collector.record(_record("trace-2"))

        json_stream = mock_open()
        with patch.object(Path, "open", json_stream):
            json_path = export_trace_json(
                collector,
                Path.cwd() / "trace.json",
            )
        json_text = "".join(
            call.args[0]
            for call in json_stream().write.call_args_list
        )

        jsonl_stream = mock_open()
        with patch.object(Path, "open", jsonl_stream):
            jsonl_path = export_trace_jsonl(
                collector.snapshot(),
                Path.cwd() / "trace.jsonl",
            )
        jsonl_text = "".join(
            call.args[0]
            for call in jsonl_stream().write.call_args_list
        )
        document = json.loads(json_text)
        lines = [
            json.loads(line) for line in jsonl_text.splitlines()
        ]

        self.assertEqual(json_path.name, "trace.json")
        self.assertEqual(jsonl_path.name, "trace.jsonl")
        self.assertEqual(document["schema_version"], TRACE_SCHEMA_VERSION)
        self.assertEqual(len(document["records"]), 2)
        self.assertEqual(len(lines), 2)
        self.assertTrue(
            all(line["schema_version"] == TRACE_SCHEMA_VERSION for line in lines)
        )

    def test_export_rejects_invalid_records_and_missing_directory(self) -> None:
        with self.assertRaises(TypeError):
            export_trace_json([object()], Path.cwd() / "invalid.json")
        with self.assertRaises(FileNotFoundError):
            export_trace_json(
                [],
                Path.cwd() / "missing-trace-directory" / "trace.json",
            )

    def test_observability_import_does_not_load_ray(self) -> None:
        before = {
            name
            for name in sys.modules
            if name == "ray" or name.startswith("ray.")
        }

        importlib.import_module("pivotq._internal.observability")

        after = {
            name
            for name in sys.modules
            if name == "ray" or name.startswith("ray.")
        }
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
