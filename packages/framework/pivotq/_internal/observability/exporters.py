"""JSON and JSONL exporters for versioned trace records."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from .trace import TRACE_SCHEMA_VERSION, TraceCollector, TraceRecord


def export_trace_json(
    traces: TraceCollector | Iterable[TraceRecord],
    destination: str | Path,
) -> Path:
    """Write one versioned JSON document and return its resolved path."""

    records = _freeze_records(traces)
    path = _destination_path(destination)
    document = {
        "schema_version": TRACE_SCHEMA_VERSION,
        "records": [record.as_dict() for record in records],
    }
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(
            document,
            stream,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        stream.write("\n")
    return path


def export_trace_jsonl(
    traces: TraceCollector | Iterable[TraceRecord],
    destination: str | Path,
) -> Path:
    """Write one versioned record per line and return its resolved path."""

    records = _freeze_records(traces)
    path = _destination_path(destination)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(
                json.dumps(
                    record.as_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            stream.write("\n")
    return path


def _freeze_records(
    traces: TraceCollector | Iterable[TraceRecord],
) -> tuple[TraceRecord, ...]:
    if isinstance(traces, TraceCollector):
        return traces.snapshot()
    if isinstance(traces, (str, bytes, bytearray)):
        raise TypeError("traces must be a TraceCollector or iterable")
    try:
        records = tuple(traces)
    except TypeError as error:
        raise TypeError(
            "traces must be a TraceCollector or iterable"
        ) from error
    if not all(isinstance(record, TraceRecord) for record in records):
        raise TypeError("all traces must be TraceRecord instances")
    return records


def _destination_path(destination: str | Path) -> Path:
    if not isinstance(destination, (str, Path)):
        raise TypeError("destination must be a path")
    path = Path(destination).expanduser().resolve()
    if not path.parent.is_dir():
        raise FileNotFoundError(
            f"trace destination directory does not exist: {path.parent}"
        )
    return path


__all__ = ["export_trace_json", "export_trace_jsonl"]
