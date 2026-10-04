"""Payload-free public execution reports and coarse invocation states."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any


class InvocationStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def is_terminal(self) -> bool:
        return self is not InvocationStatus.PENDING


@dataclass(frozen=True)
class ExecutionReport:
    """A detached snapshot of completed calls; tracing has bounded retention.

    ``observation_delay_seconds`` includes time until the driver observes a
    finished result. It is not a measurement of network transfer time.
    """

    runtime_id: str
    executor: str
    closed: bool
    trace_enabled: bool
    records: tuple[dict[str, Any], ...]
    dropped_records: int
    resources: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        # A JSON round trip also detaches nested maps from this snapshot.
        return json.loads(json.dumps({
            "schema_version": 1, "runtime_id": self.runtime_id,
            "executor": self.executor, "closed": self.closed,
            "trace_enabled": self.trace_enabled,
            "coverage": "retained terminal invocation records",
            "dropped_records": self.dropped_records,
            "resources": self.resources, "records": self.records,
        }))

    def export(self, destination: str | Path, *, format: str | None = None) -> Path:
        """Export JSON or JSONL (one report metadata row followed by call rows)."""
        path = Path(destination).expanduser().resolve()
        format = format or ("jsonl" if path.suffix == ".jsonl" else "json")
        if format not in ("json", "jsonl"):
            raise ValueError("format must be 'json' or 'jsonl'")
        document = self.as_dict()
        with path.open("w", encoding="utf-8") as stream:
            if format == "json":
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            else:
                records = document.pop("records")
                stream.write(json.dumps({"type": "report", **document}, ensure_ascii=False) + "\n")
                for record in records:
                    stream.write(json.dumps({"type": "invocation", **record}, ensure_ascii=False) + "\n")
        return path


def _public_trace(trace: Any) -> dict[str, Any]:
    record = trace.as_dict()
    resources = record.pop("resources")
    record["resources"] = {"num_cpus": resources["num_cpus"]}
    durations = record["durations_seconds"]
    record["observation_delay_seconds"] = durations.pop("transfer")
    # Metadata is explicitly supplied by the SDK/component author, never captured
    # from business arguments or provider connection configuration.
    return record


__all__ = ["InvocationStatus", "ExecutionReport"]
