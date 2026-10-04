"""No-science external component doubles used only by framework tests."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from typing import Any

from pivotq._internal.errors import CancellationError


_CALL_LOCK = Lock()
_CALL_LOG: list[str] = []


def reset_call_log() -> None:
    with _CALL_LOCK:
        _CALL_LOG.clear()


def call_log() -> tuple[str, ...]:
    with _CALL_LOCK:
        return tuple(_CALL_LOG)


def _record(value: str) -> None:
    with _CALL_LOCK:
        _CALL_LOG.append(value)


def identity_energy(value: object) -> object:
    """Top-level pickleable callable used only to check argument transport."""

    return value


@dataclass(frozen=True, slots=True)
class FakeMarker:
    component: str
    operation: str
    payload: Any = None


class _LifecycleFake:
    created_count = 0
    closed_count = 0
    _counter_lock = Lock()

    def __init__(self) -> None:
        component_type = type(self)
        with component_type._counter_lock:
            component_type.created_count += 1
        self._closed = False
        self._instance_token = uuid.uuid4().hex

    @classmethod
    def reset(cls) -> None:
        with cls._counter_lock:
            cls.created_count = 0
            cls.closed_count = 0

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        component_type = type(self)
        with component_type._counter_lock:
            component_type.closed_count += 1


class RuntimeProbeComponent(_LifecycleFake):
    """Process/lifecycle probe with no scientific computation."""

    def describe(self) -> dict[str, object]:
        return {"fixture": "runtime-probe", "scientific_result": False}

    def instance_token(self) -> str:
        return self._instance_token

    def process_id(self) -> int:
        return os.getpid()

    def capture(self, value: object) -> dict[str, object]:
        """Return an opaque value with placement-only runtime evidence."""

        return {
            "value": value,
            "runtime": self.runtime_environment(),
        }

    def runtime_environment(self) -> dict[str, object]:
        """Describe process placement without performing business computation."""

        node_id: str | None = None
        accelerator_ids: dict[str, list[str]] = {}
        try:
            import ray

            context = ray.get_runtime_context()
            raw_node_id = context.get_node_id()
            hex_method = getattr(raw_node_id, "hex", None)
            node_id = (
                hex_method() if callable(hex_method) else str(raw_node_id)
            )
            accelerator_ids = {
                name: list(values)
                for name, values in context.get_accelerator_ids().items()
            }
        except (ImportError, RuntimeError):
            pass

        nvidia_smi: str | None = None
        executable = shutil.which("nvidia-smi")
        if executable is not None:
            completed = subprocess.run(
                (
                    executable,
                    "--query-gpu=name,driver_version,memory.total",
                    "--format=csv,noheader",
                ),
                check=False,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if completed.returncode == 0:
                nvidia_smi = completed.stdout.strip()

        return {
            "hostname": socket.gethostname(),
            "process_id": os.getpid(),
            "node_id": node_id,
            "accelerator_ids": accelerator_ids,
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "nvidia_smi": nvidia_smi,
        }

    def signal_and_sleep(self, marker_path: str, seconds: float) -> float:
        """Signal an external node-failure harness, then remain in flight."""

        Path(marker_path).write_text("ready\n", encoding="utf-8")
        time.sleep(seconds)
        return seconds

    def sleep(self, seconds: float) -> float:
        time.sleep(seconds)
        return seconds


class ConcurrencyProbeComponent(_LifecycleFake):
    """Measure in-process overlap without external services or algorithms."""

    def __init__(self) -> None:
        super().__init__()
        self._activity_lock = Lock()
        self._active = 0
        self._peak = 0

    def describe(self) -> dict[str, object]:
        return {"fixture": "concurrency-probe", "scientific_result": False}

    def probe(self, seconds: float) -> int:
        with self._activity_lock:
            self._active += 1
            self._peak = max(self._peak, self._active)
        try:
            time.sleep(seconds)
        finally:
            with self._activity_lock:
                self._active -= 1
                peak = self._peak
        return peak


class FakeQuantumComponent(_LifecycleFake):
    """Method-shaped double; it does not construct or execute a circuit."""

    def describe(self) -> dict[str, object]:
        _record("quantum.describe")
        return {"fixture": "quantum", "scientific_result": False}

    def extract_features(self, request: object) -> FakeMarker:
        _record("quantum.extract_features")
        return FakeMarker("quantum", "extract_features", request)


class FakeClassicalComponent(_LifecycleFake):
    """State-recording double with no model, training, or prediction logic."""

    def __init__(self, *, loaded_from: str | None = None) -> None:
        super().__init__()
        self.loaded_from = loaded_from
        self.fit_request: object | None = None

    def describe(self) -> dict[str, object]:
        _record("classical.describe")
        return {
            "fixture": "classical",
            "fitted": self.fit_request is not None,
            "scientific_result": False,
        }

    def fit(self, request: object) -> FakeMarker:
        _record("classical.fit")
        self.fit_request = request
        return FakeMarker("classical", "fit", request)

    def predict(self, request: object) -> FakeMarker:
        _record("classical.predict")
        return FakeMarker("classical", "predict", request)

    def save_checkpoint(self, path: str | Path) -> Path:
        _record("classical.save_checkpoint")
        return Path(path)

    @classmethod
    def load_checkpoint(
        cls,
        path: str | Path,
        **kwargs: object,
    ) -> FakeClassicalComponent:
        del kwargs
        _record("classical.load_checkpoint")
        return cls(loaded_from=str(path))


class FakeForceComponent(_LifecycleFake):
    """Callable-transport double; it does not calculate a force."""

    def describe(self) -> dict[str, object]:
        _record("force.describe")
        return {"fixture": "force", "scientific_result": False}

    def calculate(
        self,
        payload: object,
        energy_function: object,
    ) -> FakeMarker:
        if not callable(energy_function):
            raise TypeError("energy_function must be callable")
        _record("force.calculate")
        return FakeMarker(
            "force",
            "calculate",
            (payload, energy_function),
        )


class RecordingFakeComponent(_LifecycleFake):
    called = Event()

    @classmethod
    def reset(cls) -> None:
        super().reset()
        cls.called = Event()

    def describe(self) -> dict[str, object]:
        return {"fixture": "recording"}

    def record(self, label: str) -> str:
        _record(label)
        type(self).called.set()
        return label


class FailingFakeComponent(_LifecycleFake):
    def describe(self) -> dict[str, object]:
        return {"fixture": "failing"}

    def fail(self) -> None:
        _record("failing.fail")
        raise RuntimeError("fixture failure")


class CancellingFakeComponent(_LifecycleFake):
    def describe(self) -> dict[str, object]:
        return {"fixture": "cancelling"}

    def cancel(self) -> None:
        _record("cancelling.cancel")
        raise CancellationError("fixture cancellation")


class PassthroughFakeComponent(_LifecycleFake):
    """Return an opaque value unchanged without interpreting it."""

    def describe(self) -> dict[str, object]:
        return {"fixture": "passthrough", "scientific_result": False}

    def echo(self, value: object) -> object:
        _record("passthrough.echo")
        return value


class InvalidFakeComponent(_LifecycleFake):
    describe = "not-callable"


class BlockingFakeComponent(_LifecycleFake):
    started = Event()
    second_started = Event()
    release = Event()
    call_count = 0

    @classmethod
    def reset(cls) -> None:
        super().reset()
        cls.started = Event()
        cls.second_started = Event()
        cls.release = Event()
        cls.call_count = 0

    def describe(self) -> dict[str, object]:
        return {"fixture": "blocking"}

    def run(self, label: str) -> str:
        _record(f"{label}:start")
        with type(self)._counter_lock:
            type(self).call_count += 1
            if type(self).call_count == 2:
                type(self).second_started.set()
        type(self).started.set()
        if not type(self).release.wait(timeout=2.0):
            raise RuntimeError("test fixture release was not signalled")
        _record(f"{label}:end")
        return label


def reset_all_fakes() -> None:
    reset_call_log()
    for component_type in (
        FakeQuantumComponent,
        FakeClassicalComponent,
        FakeForceComponent,
        RecordingFakeComponent,
        FailingFakeComponent,
        CancellingFakeComponent,
        PassthroughFakeComponent,
        InvalidFakeComponent,
        BlockingFakeComponent,
        RuntimeProbeComponent,
        ConcurrencyProbeComponent,
    ):
        component_type.reset()


__all__ = [
    "BlockingFakeComponent",
    "CancellingFakeComponent",
    "ConcurrencyProbeComponent",
    "FailingFakeComponent",
    "FakeClassicalComponent",
    "FakeForceComponent",
    "FakeMarker",
    "FakeQuantumComponent",
    "InvalidFakeComponent",
    "PassthroughFakeComponent",
    "RecordingFakeComponent",
    "RuntimeProbeComponent",
    "call_log",
    "identity_energy",
    "reset_all_fakes",
]
