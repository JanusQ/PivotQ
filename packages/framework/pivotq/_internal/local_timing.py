"""Opt-in local spans. No network, CUDA synchronization, or per-span file I/O."""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from functools import wraps
import json
import os
from pathlib import Path
import threading
import time

_context = ContextVar("local_timing_context", default={})
_active = ContextVar("local_timing_active", default=None)
_records = []
_lock = threading.Lock()
_dropped = 0
_sequence = 0
_flush_sequence = 0
_LIMIT = 100_000


def enabled():
    return bool(os.environ.get("AIMD_LOCAL_TIMING_DIR"))


@contextmanager
def scope(**fields):
    if not enabled():
        yield
        return
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)


class _Span:
    def __init__(self, stage, fields):
        self.stage, self.fields = stage, fields

    def __enter__(self):
        global _sequence
        self.parent = _active.get()
        self.child_ns = 0
        self.cpu_child_ns = 0
        with _lock:
            _sequence += 1
            self.id = f"{os.getpid()}:{_sequence}"
        self.token = _active.set(self)
        self.cpu_start = time.thread_time_ns()
        self.start = time.perf_counter_ns()
        return self.fields

    def __exit__(self, typ, value, traceback):
        global _dropped
        end = time.perf_counter_ns()
        cpu_end = time.thread_time_ns()
        duration = end - self.start
        cpu_duration = cpu_end - self.cpu_start
        _active.reset(self.token)
        if self.parent is not None:
            self.parent.child_ns += duration
            self.parent.cpu_child_ns += cpu_duration
        record = {"schema_version": "qpu-local-span-v1", "span_id": self.id,
                  "parent_span_id": self.parent.id if self.parent else None,
                  "stage": self.stage, "pid": os.getpid(), "thread_id": threading.get_ident(),
                  "clock": "process_perf_counter_ns", "started_ns": self.start, "finished_ns": end,
                  "duration_ns": duration, "exclusive_duration_ns": max(0, duration-self.child_ns),
                  "thread_cpu_duration_ns": cpu_duration,
                  "exclusive_thread_cpu_duration_ns": max(0, cpu_duration-self.cpu_child_ns),
                  "status": "failed" if typ else "succeeded",
                  "fields": {**_context.get(), **self.fields}}
        if typ:
            record["error_type"] = typ.__name__
        with _lock:
            if len(_records) < _LIMIT:
                _records.append(record)
            else:
                _dropped += 1
        return False


def span(stage, **fields):
    return _Span(stage, fields) if enabled() else nullcontext({})


def timed(stage):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with span(stage):
                return fn(*args, **kwargs)
        return wrapped
    return decorate


def flush():
    """Write once at a logical call boundary. Telemetry I/O cannot fail science."""
    global _flush_sequence
    directory = os.environ.get("AIMD_LOCAL_TIMING_DIR")
    if not directory:
        return False
    with _lock:
        if not _records:
            return True
        records = list(_records)
        _records.clear()
        _flush_sequence += 1
        sequence = _flush_sequence
    try:
        path = Path(directory)
        if not path.is_absolute():
            raise ValueError("timing directory must be absolute")
        path.mkdir(parents=True, exist_ok=True)
        target = path / f"local-{os.getpid()}-{sequence:06d}.json"
        payload = {"schema_version": "qpu-local-timing-v1", "pid": os.getpid(),
                   "dropped_records": _dropped, "records": records,
                   "measurement_policy": "Host wall time and calling-thread CPU time; no GPU sync, no pure-kernel claim; exclusive durations exclude nested spans on this context"}
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temporary.replace(target)
        return True
    except (OSError, TypeError, ValueError):
        # The run's post-check detects missing spans. Keep the original result
        # and exception behavior if optional telemetry storage is unavailable.
        with _lock:
            _records[:0] = records[:max(0, _LIMIT-len(_records))]
        return False
