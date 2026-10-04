"""Immutable, bounded records of local Actor cleanup actions (not release proof)."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

from pivotq._internal.errors import ExecutionError

MAX_ACTOR_RECORDS = 32


def error_type(error: BaseException) -> str:
    name = type(error).__name__
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name) else "CleanupError"


@dataclass(frozen=True, slots=True)
class ActorCleanupRecord:
    component_id: str
    actor_name: str
    cooperative_state: str
    cooperative_error_type: str | None
    timeout_seconds: float
    termination_state: str
    termination_mode: str
    termination_error_type: str | None
    actor_id: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "component_id": self.component_id,
            "actor_name": self.actor_name,
            "actor_id": self.actor_id,
            "cooperative_close": {
                "state": self.cooperative_state,
                "attempt_count": 0 if self.cooperative_state == "not_attempted" else 1,
                "timeout_seconds": self.timeout_seconds,
                "error_type": self.cooperative_error_type,
            },
            "termination": {
                "state": self.termination_state,
                "attempt_count": 0 if self.termination_state == "not_requested" else 1,
                "mode": self.termination_mode,
                "error_type": self.termination_error_type,
            },
        }


@dataclass(frozen=True, slots=True)
class ExecutorCleanupReport:
    records: tuple[ActorCleanupRecord, ...] = ()
    records_complete: bool = False

    @property
    def outcome(self) -> str:
        if not self.records_complete:
            return "failed"
        if any(
            record.cooperative_state not in ("succeeded", "timed_out")
            or record.termination_state != "requested"
            for record in self.records
        ):
            return "failed"
        return (
            "fallback_pending_verification"
            if any(record.cooperative_state == "timed_out" for record in self.records)
            else "clean"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "records_complete": self.records_complete,
            "total": len(self.records),
            "cooperative_succeeded": sum(r.cooperative_state == "succeeded" for r in self.records),
            "cooperative_timed_out": sum(r.cooperative_state == "timed_out" for r in self.records),
            "cooperative_failed": sum(r.cooperative_state == "failed" for r in self.records),
            "termination_requested": sum(r.termination_state == "requested" for r in self.records),
            "termination_failed": sum(r.termination_state == "failed" for r in self.records),
            "records": [record.as_dict() for record in self.records],
        }

    @classmethod
    def completed(cls, records: list[ActorCleanupRecord], *, total: int) -> ExecutorCleanupReport:
        ordered = tuple(sorted(records, key=lambda record: (record.component_id, record.actor_name)))
        valid = total == len(ordered) <= MAX_ACTOR_RECORDS
        valid = valid and len({r.component_id for r in ordered}) == len(ordered)
        valid = valid and len({r.actor_name for r in ordered}) == len(ordered)
        for record in ordered:
            if (
                not 1 <= len(record.component_id) <= 128
                or not 1 <= len(record.actor_name) <= 512
                or re.search(r"[\x00-\x1f\x7f]", record.component_id + record.actor_name)
                or not math.isfinite(record.timeout_seconds)
                or not 0 < record.timeout_seconds <= 30
            ):
                return cls()  # Keep the manifest bounded and explicitly incomplete.
        return cls(ordered[:MAX_ACTOR_RECORDS], valid)


class ExecutorCleanupError(ExecutionError):
    def __init__(self, report: ExecutorCleanupReport) -> None:
        super().__init__("one or more Ray Actor components failed to close cleanly")
        self._cleanup_report = report

    @property
    def cleanup_report(self) -> ExecutorCleanupReport:
        return self._cleanup_report

    def __reduce__(self):
        return (type(self), (self.cleanup_report,))
