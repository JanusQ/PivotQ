"""通过设备 HTTP API 上传已绑定 QASM3，并解析逐电路概率结果。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import logging
import math
from numbers import Real
import os
from pathlib import Path
import time
from urllib.parse import quote

from pivotq._internal.local_timing import scope, span, timed
from .contracts import CircuitResult
from .job_journal import JobJournal, JobJournalError
from .device_timing import decode_device_timing, circuit_timing_metadata, response_device_timing
from .qasm3_export import QASM3Circuit


MEASUREMENT_QUBITS = (0, 1, 2)
_PROBABILITY_STATES = tuple(f"{state:03b}" for state in range(8))
DEVICE_URL_ENV = "QPU_DEVICE_URL"
DEVICE_API_KEY_ENV = "QPU_DEVICE_API_KEY"
_LOG = logging.getLogger(__name__)


class DeviceProtocolNotConfiguredError(NotImplementedError):
    """连接配置、SDK 或结果转换尚未准备好。"""


class DeviceClientError(RuntimeError):
    """客户端或临时文件处理失败。"""


class DeviceResultError(ValueError):
    """结果不符合 AIMD 的三比特概率约定。"""


class DeviceExecutionUnknownError(RuntimeError):
    """设备可能已经执行，需核实任务编号，不能直接重提。"""


@dataclass(frozen=True, slots=True)
class DeviceCircuitResult:
    circuit_id: str
    shots: int
    measurement_qubits: tuple[int, ...]
    complete: bool = False
    probabilities: Mapping[str, float] | None = None
    counts: Mapping[str, int] | None = None
    device_timing: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class DeviceJobResponse:
    request_id: str
    job_id: str | int
    requested_shots: int  # 请求元数据，不能作为实际采样次数的依据。
    circuits: tuple[QASM3Circuit, ...] = field(repr=False)
    result: Mapping[str, object] = field(repr=False)


class QPUDeviceAdapter:
    def __init__(
        self, *, server_url: str | None = None, api_key: str | None = None,
        probability_source: str | None = None,
        journal_dir: str | None = None,
        timeout_seconds: float = 600.0,
        archive_dir: str | None = None,
        use_environment: bool = True,
    ) -> None:
        # 不传参数时，通信函数会读取计算节点的环境变量。
        self._server_url = server_url
        self._api_key = api_key
        self._use_environment = use_environment
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 86400:
            raise DeviceProtocolNotConfiguredError('QPU timeout_seconds must be between 1 and 86400')
        self._timeout_seconds = float(timeout_seconds)
        self._journal = JobJournal(journal_dir) if journal_dir else None
        self._probability_source = (
            probability_source if probability_source is not None
            else os.environ.get("QPU_PROBABILITY_SOURCE", "expr_prob") if use_environment else "expr_prob"
        )
        if self._probability_source not in {"expr_prob", "ideal_prob"}:
            raise DeviceProtocolNotConfiguredError(
                "QPU_PROBABILITY_SOURCE must be expr_prob or ideal_prob"
            )
        if self._journal and self._probability_source != "expr_prob":
            raise ValueError("Durable real-QPU training requires expr_prob")
        archive = archive_dir if archive_dir is not None else (
            os.environ.get("QPU_RESULT_ARCHIVE_DIR") if use_environment else None
        )
        self._archive_dir = Path(archive) if archive else None
        if self._archive_dir is not None:
            if not self._archive_dir.is_absolute():
                raise DeviceProtocolNotConfiguredError("QPU_RESULT_ARCHIVE_DIR must be absolute")
            self._archive_dir.mkdir(parents=True, exist_ok=True)

    def execute_batch(
        self, circuits: Sequence[QASM3Circuit], *, shots: int, request_id: str,
    ) -> list[CircuitResult]:
        circuits = tuple(circuits)
        exchange = self._exchange(circuits, shots=shots, request_id=request_id)
        # Preserve the raw-response hook used by explicitly injected adapters.
        if not isinstance(exchange, Iterator):
            decoded = self._decode(exchange, request_id=request_id)
            return normalize_results(decoded, circuits=circuits, shots=shots)
        decoded = []
        # Validate each device batch before submitting the next one. An error
        # stops the logical request; previously executed batches are not retried.
        with closing(exchange) as batches:
            for raw in batches:
                try:
                    with scope(request_id=raw.request_id, job_id=raw.job_id):
                        batch_results = self._decode(raw, request_id=raw.request_id)
                        normalize_results(batch_results, circuits=raw.circuits, shots=shots)
                except DeviceResultError as error:
                    raise DeviceResultError(
                        f"{error}; request_id={raw.request_id!r}, job_id={raw.job_id!r}; "
                        "remaining batches were not submitted"
                    ) from None
                decoded.extend(batch_results)
        return normalize_results(decoded, circuits=circuits, shots=shots)

    def _exchange(
        self, circuits: Sequence[QASM3Circuit], *, shots: int, request_id: str,
    ) -> Iterator[DeviceJobResponse]:
        url = self._server_url if self._server_url is not None else (
            os.environ.get(DEVICE_URL_ENV) if self._use_environment else None
        )
        key = self._api_key if self._api_key is not None else (
            os.environ.get(DEVICE_API_KEY_ENV) if self._use_environment else None
        )
        if not isinstance(url, str) or not url.strip():
            raise DeviceProtocolNotConfiguredError(
                f"Set {DEVICE_URL_ENV} or pass server_url; see device_adapter.py"
            )
        if key is not None and not isinstance(key, str):
            raise DeviceProtocolNotConfiguredError("api_key must be a string or None")
        try:
            import httpx
        except ImportError:
            raise DeviceProtocolNotConfiguredError(
                "Install httpx on the compute node; see device_adapter.py"
            ) from None

        circuits = tuple(circuits)
        if not circuits or type(shots) is not int or shots <= 0:
            raise DeviceClientError("a nonempty circuit batch and positive integer shots are required")
        uploads = []
        names: set[str] = set()
        ids: set[str] = set()
        for circuit in circuits:
            name = circuit.filename
            if not name or name in {".", ".."} or any(c in name for c in "/\\:"):
                raise DeviceClientError("QASM upload filename must be a local basename")
            if name in names or not circuit.circuit_id or circuit.circuit_id in ids:
                raise DeviceClientError("QASM upload filenames and circuit IDs must be unique")
            names.add(name)
            ids.add(circuit.circuit_id)
            uploads.append(("files", (name, circuit.content.encode("utf-8"), "application/octet-stream")))

        headers = {"Authorization": f"Bearer {key}"} if key and key.strip() else {}
        job_id = None
        submitted = False
        stage = "health"
        active_request_id = request_id
        try:
            with httpx.Client(
                base_url=url.strip().rstrip("/"), headers=headers, timeout=70, trust_env=False,
            ) as client:
                response = client.get("/health", timeout=5)
                response.raise_for_status()
                health = response.json()
                if not isinstance(health, Mapping) or health.get("status") != "ok" or "backend" not in health:
                    raise DeviceClientError("QPU service health check failed")
                if health.get("backend") == "mock":
                    raise DeviceClientError("mock backend cannot provide real QPU results")
                if health.get("auth_required") and not headers:
                    raise DeviceProtocolNotConfiguredError(f"QPU service requires {DEVICE_API_KEY_ENV}")
                limits = health.get("limits", {})
                if not isinstance(limits, Mapping):
                    raise DeviceClientError("QPU health limits must be an object")
                max_circuits = limits.get("max_circuits", 32)
                max_file_bytes = limits.get("max_file_bytes", 1048576)
                if type(max_circuits) is not int or max_circuits <= 0:
                    raise DeviceClientError("QPU max_circuits must be a positive integer")
                if type(max_file_bytes) is not int or max_file_bytes <= 0:
                    raise DeviceClientError("QPU max_file_bytes must be a positive integer")
                # Check every file before any batch can start executing.
                if any(len(upload[1][1]) > max_file_bytes for upload in uploads):
                    raise DeviceClientError(
                        f"QASM file exceeds device max_file_bytes={max_file_bytes}; "
                        "no circuits were submitted"
                    )
                # X/Y 换基由输入电路提供；设备负责最终 Z 基读出。
                # 其他参数（包括 theta）不覆盖设备默认值，多扫描点由解码器拒绝。
                for batch_index, start in enumerate(range(0, len(circuits), max_circuits)):
                    batch_circuits = circuits[start:start + max_circuits]
                    active_request_id = (
                        request_id if len(circuits) <= max_circuits
                        else f"{request_id}.batch-{batch_index:06d}"
                    )
                    job_id = None
                    stage = "submit"
                    submitted = True
                    result = None
                    if self._journal is not None:
                        journal_path, journal_record, result = self._journal.prepare(
                            active_request_id, server_url=url.strip().rstrip("/"),
                            shots=shots, circuits=batch_circuits,
                        )
                    if result is None:
                        with span("qpu.http_submit", request_id=active_request_id):
                            def submit_http():
                                return client.post(
                                "/v1/jobs", files=uploads[start:start + max_circuits],
                                data={"parameters": json.dumps({"reps": shots, "measure_base": "Z"})},
                                )
                            response = (self._journal.call_http(journal_path, journal_record, "submit", submit_http)
                                        if self._journal is not None else submit_http())
                            if self._journal is not None:
                                result = self._journal.read_http_response(journal_path, journal_record, response)
                            else:
                                response.raise_for_status()
                                result = response.json()
                    job_id = result.get("job_id") if isinstance(result, Mapping) else None
                    if type(job_id) not in (str, int) or not str(job_id).strip():
                        raise DeviceExecutionUnknownError(
                            f"QPU submit returned no usable job_id; request_id={active_request_id!r}; "
                            "reconcile before resubmitting"
                        )
                    _LOG.info(
                        "QPU submitted request_id=%r job_id=%r circuits=%d",
                        active_request_id, job_id, len(batch_circuits),
                    )
                    deadline = time.monotonic() + self._timeout_seconds
                    while True:
                        if not isinstance(result, Mapping) or result.get("job_id") != job_id:
                            raise DeviceExecutionUnknownError(f"QPU response job_id mismatch; job_id={job_id!r}")
                        status = result.get("status")
                        if status == "succeeded":
                            break
                        if status in {"failed", "interrupted"}:
                            details = result.get("error")
                            # Only expose short diagnostic identifiers, never a
                            # response body, circuit content, or request headers.
                            codes = []
                            if isinstance(details, Mapping):
                                for label in ("code", "type"):
                                    value = details.get(label)
                                    if isinstance(value, str) and 0 < len(value) <= 80 and all(
                                        c.isascii() and (c.isalnum() or c in "_.-") for c in value
                                    ):
                                        codes.append(f"{label}={value}")
                            raise DeviceClientError(
                                f"QPU job {status}; request_id={active_request_id!r}, job_id={job_id!r}; "
                                + "; ".join(codes)
                                + "; inspect the job record; remaining batches were not submitted"
                            )
                        if status not in {"queued", "running"}:
                            raise DeviceExecutionUnknownError(f"QPU returned unknown status; job_id={job_id!r}")
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise DeviceExecutionUnknownError(
                                f"QPU wait timed out; request_id={active_request_id!r}, job_id={job_id!r}; "
                                "query this job to resume; do not resubmit"
                            )
                        # 与独立客户端一致，短查询兼容设备的 wait_seconds 上限。
                        stage = "poll"
                        with span("qpu.http_poll", request_id=active_request_id, job_id=job_id):
                            def poll_http():
                                return client.get(
                                f"/v1/jobs/{quote(str(job_id), safe='')}",
                                params={"wait_seconds": 0}, timeout=min(10, remaining),
                                )
                            response = (self._journal.call_http(journal_path, journal_record, "poll", poll_http)
                                        if self._journal is not None else poll_http())
                            if self._journal is not None:
                                result = self._journal.read_http_response(journal_path, journal_record, response)
                            else:
                                response.raise_for_status()
                                result = response.json()
                        if isinstance(result, Mapping) and result.get("status") in {"queued", "running"}:
                            with span("qpu.poll_sleep", request_id=active_request_id, job_id=job_id):
                                time.sleep(min(1, max(0, deadline - time.monotonic())))
                    if self._archive_dir is not None and self._journal is None:
                        archive_id = hashlib.sha256(active_request_id.encode()).hexdigest()
                        with (self._archive_dir / f"{archive_id}.json").open("x") as handle:
                            json.dump({
                                "request_id": active_request_id,
                                "probability_source": self._probability_source,
                                "device_timing": decode_device_timing(
                                    response_device_timing(result), circuits=batch_circuits,
                                    request_id=active_request_id, job_id=job_id,
                                ),
                                "response": result,
                                "circuits": [
                                    {"circuit_id": c.circuit_id, "filename": c.filename,
                                     "measurement_basis": c.measurement_basis,
                                     "sha256": hashlib.sha256(c.content.encode()).hexdigest(),
                                     "qasm": c.content}
                                    for c in batch_circuits
                                ],
                            }, handle, ensure_ascii=False, indent=2)
                    yield DeviceJobResponse(active_request_id, job_id, shots, batch_circuits, result)
        except (DeviceClientError, DeviceExecutionUnknownError, DeviceProtocolNotConfiguredError):
            raise
        except JobJournalError as exc:
            raise DeviceExecutionUnknownError(str(exc)) from None
        except httpx.HTTPStatusError as exc:
            error = DeviceExecutionUnknownError if submitted else DeviceClientError
            raise error(
                f"QPU HTTP {exc.response.status_code}; stage={stage}; "
                f"request_id={active_request_id!r}, job_id={job_id!r}; do not automatically resubmit"
            ) from None
        except Exception as exc:
            error = DeviceExecutionUnknownError if submitted else DeviceClientError
            raise error(
                f"QPU HTTP client failed ({type(exc).__name__}); stage={stage}; "
                f"request_id={active_request_id!r}, job_id={job_id!r}; do not automatically resubmit"
            ) from None

    @timed("qpu.decode_probabilities")
    def _decode(
        self, raw: object, *, request_id: str,
    ) -> Sequence[DeviceCircuitResult]:
        if not isinstance(raw, DeviceJobResponse) or raw.request_id != request_id:
            raise DeviceResultError("response request_id mismatch")
        record = raw.result
        if record.get("job_id") != raw.job_id or record.get("status") != "succeeded" or record.get("error") is not None:
            raise DeviceResultError(f"invalid successful job record; job_id={raw.job_id!r}")
        if record.get("backend") != "circuit":
            raise DeviceResultError("expected circuit backend result")
        parameters = record.get("parameters")
        if not isinstance(parameters, Mapping) or parameters.get("measure_base") != "Z":
            raise DeviceResultError("device must confirm Z readout for the supplied basis-rotated circuits")
        # 设备示例将 reps 定义为每点重复次数。此处使用成功记录中的 reps，
        # 不从 requested_shots 补值；它仍是设备报告值，不是独立采样计数证明。
        reps = parameters.get("reps")
        if type(reps) is not int or reps <= 0 or reps != raw.requested_shots:
            raise DeviceResultError("reported reps must equal requested shots")
        table = record.get("result")
        if not isinstance(table, Mapping):
            raise DeviceResultError("missing result table")
        columns, rows = table.get("columns"), table.get("data")
        if not isinstance(columns, list) or not all(isinstance(c, str) for c in columns) or len(set(columns)) != len(columns):
            raise DeviceResultError("result columns must be unique strings")
        probability_prefix = self._probability_source + "_P"
        probability_columns = {probability_prefix + state for state in _PROBABILITY_STATES}
        if {c for c in columns if c.startswith(probability_prefix)} != probability_columns or "circuit" not in columns:
            raise DeviceResultError(f"result must contain circuit and all eight {self._probability_source} probabilities")
        if not isinstance(rows, list) or len(rows) != len(raw.circuits):
            raise DeviceResultError("expected one row per bound circuit; missing results or theta scans are unsupported")
        extra = record.get("extra")
        if isinstance(extra, Mapping):
            if "row_count" in extra and (type(extra["row_count"]) is not int or extra["row_count"] != len(rows)):
                raise DeviceResultError("extra.row_count differs from result data")
            if "measure_base" in extra and extra["measure_base"] != "Z":
                raise DeviceResultError("extra.measure_base must be Z")
        files = record.get("files")
        expected = {c.filename: c for c in raw.circuits}
        if not expected or len(expected) != len(raw.circuits) or not isinstance(files, list) or len(files) != len(expected):
            raise DeviceResultError("uploaded file manifest mismatch")
        by_index = {}
        seen_names = set()
        for item in files:
            if not isinstance(item, Mapping):
                raise DeviceResultError("invalid file manifest entry")
            index, name = item.get("index"), item.get("name")
            if type(index) is not int or index < 0 or index in by_index or not isinstance(name, str) or name not in expected or name in seen_names:
                raise DeviceResultError("unexpected or duplicate file index/name")
            by_index[index] = expected[name]
            seen_names.add(name)
        timing_report = decode_device_timing(
            response_device_timing(record), circuits=raw.circuits,
            request_id=raw.request_id, job_id=raw.job_id,
        )
        per_circuit_timing = circuit_timing_metadata(timing_report)
        if timing_report is not None and timing_report["status"] == "invalid":
            _LOG.warning(
                "QPU timing metadata invalid; request_id=%r job_id=%r: %s; probabilities are validated separately",
                raw.request_id, raw.job_id, timing_report["error"],
            )
        positions = {name: index for index, name in enumerate(columns)}
        decoded = []
        seen_indices = set()
        # 当前协议约定状态字符串从左到右为逻辑 q0,q1,q2；不会根据
        # dataset_name 猜测物理位序。上线前须用设备约定/基态电路核实。
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns):
                raise DeviceResultError("result row width differs from columns")
            index = row[positions["circuit"]]
            if isinstance(index, bool) or not isinstance(index, Real) or not math.isfinite(index) or index != int(index) or int(index) not in by_index:
                raise DeviceResultError("invalid result circuit index")
            index = int(index)
            if index in seen_indices:
                raise DeviceResultError("duplicate circuit row; theta scans are unsupported")
            seen_indices.add(index)
            decoded.append(DeviceCircuitResult(
                circuit_id=by_index[index].circuit_id, shots=reps,
                measurement_qubits=MEASUREMENT_QUBITS, complete=True,
                probabilities={state: row[positions[probability_prefix + state]] for state in _PROBABILITY_STATES},
                device_timing=(
                    per_circuit_timing.get(by_index[index].circuit_id)
                    if timing_report is None or timing_report["status"] == "valid"
                    else timing_report
                ),
            ))
        return decoded

    def close(self) -> None:
        # 上面的 with 已负责资源清理；此处不取消设备任务。
        return None


@timed("qpu.validate_probabilities")
def normalize_results(
    results: Sequence[DeviceCircuitResult], *,
    circuits: Sequence[QASM3Circuit], shots: int,
) -> list[CircuitResult]:
    """Validate complete results and return all eight three-bit probabilities."""
    expected = {circuit.circuit_id: circuit for circuit in circuits}
    if not expected or len(expected) != len(circuits):
        raise DeviceResultError("expected circuit IDs must be nonempty and unique")
    by_id: dict[str, CircuitResult] = {}
    for result in results:
        if not isinstance(result, DeviceCircuitResult):
            raise DeviceResultError("decoder must return DeviceCircuitResult items")
        if result.circuit_id not in expected or result.circuit_id in by_id:
            raise DeviceResultError("unexpected or duplicate circuit_id in response")
        if result.complete is not True:
            raise DeviceResultError("device result completeness is unconfirmed")
        if type(result.shots) is not int or result.shots <= 0 or result.shots != shots:
            raise DeviceResultError("actual shots must equal requested shots")
        if (
            tuple(result.measurement_qubits) != MEASUREMENT_QUBITS
            or any(type(qubit) is not int for qubit in result.measurement_qubits)
        ):
            raise DeviceResultError("current interface requires logical qubits [0, 1, 2]")
        if (result.counts is None) == (result.probabilities is None):
            raise DeviceResultError("provide exactly one of counts or probabilities")
        values = result.counts if result.counts is not None else result.probabilities
        if not isinstance(values, Mapping) or not values:
            raise DeviceResultError("distribution must be a nonempty mapping")
        probabilities: dict[str, float] = {}
        count_sum = 0
        for state, value in values.items():
            if not isinstance(state, str) or len(state) != 3 or set(state) - {"0", "1"}:
                raise DeviceResultError("state must be three bits in logical q0,q1,q2 order")
            if result.counts is not None:
                if type(value) is not int or value < 0:
                    raise DeviceResultError("counts must be nonnegative integers")
                count_sum += value
                probability = value / result.shots
            else:
                if isinstance(value, bool) or not isinstance(value, Real):
                    raise DeviceResultError("probabilities must be real numbers")
                probability = float(value)
            if not math.isfinite(probability) or not 0 <= probability <= 1:
                raise DeviceResultError("probabilities must be finite and between zero and one")
            probabilities[state] = probability
        if result.counts is not None and count_sum != result.shots:
            raise DeviceResultError("sum of counts differs from actual shots")
        if not math.isclose(math.fsum(probabilities.values()), 1.0, rel_tol=0, abs_tol=1e-6):
            raise DeviceResultError("probability sum must be one; partial results are rejected")
        by_id[result.circuit_id] = {
            "circuit_id": result.circuit_id,
            "shots": result.shots,
            "measurement_basis": expected[result.circuit_id].measurement_basis,
            "measurement_qubits": list(MEASUREMENT_QUBITS),
            # 上面已确认分布完整性，只能补齐被省略的真实零概率状态；
            # 不完整的设备原始返回会在此前报错。
            "probabilities": {state: probabilities.get(state, 0.0) for state in _PROBABILITY_STATES},
        }
        if result.device_timing is not None:
            if not isinstance(result.device_timing, Mapping):
                raise DeviceResultError("device_timing must be a mapping when provided")
            by_id[result.circuit_id]["device_timing"] = deepcopy(dict(result.device_timing))
    if by_id.keys() != expected.keys():
        raise DeviceResultError("missing circuit result(s)")
    return [by_id[circuit.circuit_id] for circuit in circuits]
