"""Optional device timing metadata; all durations normalize to seconds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from numbers import Real

from .qasm3_export import QASM3Circuit


RECEIVED = "接受任务时刻"
INITIALIZED = "QPU控制端初始化完毕时刻"
UPLOADED = "各量子电路波形上传QPU时刻"
RETURNED = "各量子电路波形结果接收时刻"
FINISHED = "任务结束时刻"
RESET_DURATION = "单次量子电路前置0初始化时间"
READOUT_DURATION = "单次量子电路读取波形时间"
WAVEFORM_DURATIONS = "各量子电路单次计算波形总时间"
_UNIT_SECONDS = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "μs": 1e-6, "ns": 1e-9}


class _TimingError(ValueError):
    pass


def response_device_timing(record: Mapping[str, object]) -> object:
    """Read the deployed HTTP schema, retaining the initial timing alias.

    A non-null extra.time_info is authoritative even if malformed, so an
    invalid device report cannot be silently replaced with other telemetry.
    """
    extra = record.get("extra")
    if isinstance(extra, Mapping) and extra.get("time_info") is not None:
        return extra["time_info"]
    return record.get("timing")


def decode_device_timing(
    value: object, *, circuits: Sequence[QASM3Circuit],
    request_id: str, job_id: str | int,
) -> dict[str, object] | None:
    """Interpret the selected timing object without changing scientific results.

    Arrays follow the upload order of this HTTP batch, not the order of
    probability rows or the order of the returned file manifest. Timestamps
    share the device's Unix clock; they are never subtracted from Ray clocks.
    Invalid optional telemetry is recorded explicitly rather than retried.
    """
    if value is None:
        return None
    report: dict[str, object] = {
        "schema_version": "qpu-device-timing-v1",
        "source": "device_reported",
        "timestamp_clock": "device_unix_seconds",
        "duration_unit": "s",
        "request_id": request_id,
        "job_id": job_id,
    }
    try:
        if not isinstance(value, Mapping):
            raise _TimingError("timing must be a JSON object")
        received = _number(value.get(RECEIVED), RECEIVED)
        initialized = _number(value.get(INITIALIZED), INITIALIZED)
        finished = _number(value.get(FINISHED), FINISHED)
        if not received <= initialized <= finished:
            raise _TimingError("task timestamps must satisfy received <= initialized <= finished")
        uploads = _array(value.get(UPLOADED), UPLOADED, len(circuits))
        returns = _array(value.get(RETURNED), RETURNED, len(circuits))
        waveforms = _array(value.get(WAVEFORM_DURATIONS), WAVEFORM_DURATIONS, len(circuits))
        reset = _duration(value.get(RESET_DURATION), RESET_DURATION)
        readout = _duration(value.get(READOUT_DURATION), READOUT_DURATION)
        circuit_timings = []
        for index, circuit in enumerate(circuits):
            uploaded = _number(uploads[index], f"{UPLOADED}[{index}]")
            returned = _number(returns[index], f"{RETURNED}[{index}]")
            if not initialized <= uploaded <= returned <= finished:
                raise _TimingError(
                    f"circuit timing[{index}] must satisfy initialized <= uploaded <= returned <= finished"
                )
            circuit_timings.append({
                "circuit_id": circuit.circuit_id,
                "filename": circuit.filename,
                "upload_index": index,
                "waveform_uploaded_at": uploaded,
                "waveform_result_received_at": returned,
                # Includes device-side overhead/waiting, not pure gate time.
                "upload_to_result_seconds": returned - uploaded,
                "initialization_seconds_per_execution": reset,
                "readout_seconds_per_execution": readout,
                "waveform_seconds_per_execution": _duration(waveforms[index], f"{WAVEFORM_DURATIONS}[{index}]"),
            })
        report.update({
            "status": "valid",
            "job": {
                "received_at": received,
                "control_initialized_at": initialized,
                "finished_at": finished,
                "control_initialization_seconds": initialized - received,
                "job_elapsed_seconds": finished - received,
            },
            "circuits": circuit_timings,
        })
    except _TimingError as error:
        report.update({"status": "invalid", "error": str(error)})
    return report


def circuit_timing_metadata(report: dict[str, object] | None) -> dict[str, dict[str, object]]:
    """Create compact per-circuit metadata without repeating other circuits."""
    if report is None or report["status"] != "valid":
        return {}
    shared = {key: value for key, value in report.items() if key != "circuits"}
    return {
        circuit["circuit_id"]: {**shared, **circuit}
        for circuit in report["circuits"]
    }


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise _TimingError(f"{name} must be a finite nonnegative number")
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise _TimingError(f"{name} must be a finite nonnegative number") from None
    if not math.isfinite(number) or number < 0:
        raise _TimingError(f"{name} must be a finite nonnegative number")
    return number


def _array(value: object, name: str, count: int) -> list:
    if not isinstance(value, list) or len(value) != count:
        raise _TimingError(f"{name} must contain exactly {count} entries in upload order")
    return value


def _duration(value: object, name: str) -> float:
    if not isinstance(value, Mapping):
        raise _TimingError(f"{name} must be an object with value and unit")
    unit = value.get("unit")
    if not isinstance(unit, str) or unit not in _UNIT_SECONDS:
        raise _TimingError(f"{name}.unit must be s, ms, us, µs, μs or ns")
    number = _number(value.get("value"), f"{name}.value") * _UNIT_SECONDS[unit]
    if not math.isfinite(number):
        raise _TimingError(f"{name} is outside the supported duration range")
    return number
