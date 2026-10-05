"""Real HTTP multipart submission and durable reconciliation, no CPU fallback."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import quote

import httpx
import numpy as np

from .hardware import HardwareNotReady, prepare
from .protocol import decode


class ExecutionUnknown(RuntimeError):
    """A POST may have executed, or a known job still needs reconciliation."""


def write_json(path, value):
    temporary = path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n")
    temporary.replace(path)


class QPUClient:
    def __init__(self, profile, journal_dir, *, url=None, timeout_seconds=600, client=None):
        self.profile = profile
        self.journal = Path(journal_dir).resolve()
        self.journal.mkdir(parents=True, exist_ok=True)
        url = url or os.environ.get("QPU_DEVICE_URL")
        if client is None and not url:
            raise HardwareNotReady("Set QPU_DEVICE_URL to the actual device HTTP service")
        key = os.environ.get("QPU_DEVICE_API_KEY", "")
        self.client = client or httpx.Client(base_url=url.rstrip("/"),
             headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=70, trust_env=False)
        if self.client.base_url.username or self.client.base_url.password:
            raise ValueError("Use QPU_DEVICE_API_KEY; credentials must not appear in the device URL")
        if not np.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Bounded positive QPU wait budget required")
        self.timeout_seconds = timeout_seconds
        self.shots = 3000
        self.server_identity = str(self.client.base_url)

    def health(self):
        response = self.client.get("/health", timeout=5)
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict) or value.get("status") != "ok" or value.get("backend") != "circuit":
            raise HardwareNotReady("Actual circuit backend required; mock backend rejected")
        limits = value.get("limits", {})
        if not isinstance(limits, dict):
            raise HardwareNotReady("Invalid service limits")
        for name, default in (("max_circuits", 32), ("max_file_bytes", 1048576)):
            if type(limits.get(name, default)) is not int or limits.get(name, default) <= 0:
                raise HardwareNotReady("Invalid positive device request limit")
        if "max_qubits" in limits and (type(limits["max_qubits"]) is not int or limits["max_qubits"] < 60):
            raise HardwareNotReady("Service does not support a 60-qubit request")
        if value.get("auth_required") and not self.client.headers.get("Authorization"):
            raise HardwareNotReady("Device requires QPU_DEVICE_API_KEY before submission")
        return value

    def _poll(self, record, path):
        job_id = record["job_id"]
        deadline = time.monotonic()+self.timeout_seconds
        current = record.get("response")
        while True:
            if current is None:
                try:
                    response = self.client.get(f"/v1/jobs/{quote(str(job_id), safe='')}", params={"wait_seconds": 0}, timeout=10)
                    response.raise_for_status()
                    current = response.json()
                except Exception as exc:
                    raise ExecutionUnknown(f"Polling failed ({type(exc).__name__}); reconcile job_id={job_id}") from None
            if not isinstance(current, dict) or current.get("job_id") != job_id:
                raise ExecutionUnknown(f"Job identity mismatch; reconcile job_id={job_id}")
            status = current.get("status")
            record.update(status=status, response=current)
            write_json(path, record)
            if status == "succeeded":
                return current
            if status in ("failed", "interrupted"):
                raise RuntimeError(f"Physical QPU job {status}; job_id={job_id}; inspect journal")
            if status not in ("queued", "running"):
                raise ExecutionUnknown(f"Unknown device status; reconcile job_id={job_id}")
            if time.monotonic() >= deadline:
                raise ExecutionUnknown(f"Wait timed out; reconcile job_id={job_id}; do not resubmit")
            time.sleep(min(1, max(0, deadline-time.monotonic())))
            current = None

    def execute(self, requests, shots, request_id):
        requests = tuple(requests)
        if not requests or len({r.circuit_id for r in requests}) != len(requests) or type(shots) is not int or shots <= 0:
            raise ValueError("Nonempty unique requests and positive integer shots required")
        if len({r.filename for r in requests}) != len(requests):
            raise ValueError("Distinct uploaded filenames required")
        for request in requests:
            if Path(request.filename).name != request.filename or not request.filename.endswith(".qasm"):
                raise ValueError("QASM upload filenames must be basenames")
            if request.mapping_version != self.profile.mapping_version or request.basis not in ("X", "Z"):
                raise ValueError("Request profile version or measurement basis mismatch")
            if len(request.logical_readout_labels) != 60 or set(request.logical_readout_labels) != set(self.profile.physical_labels):
                raise ValueError("Request must contain all 60 physical readout labels")
        limits = self.health().get("limits", {})
        if any(len(r.qasm.encode()) > limits.get("max_file_bytes", 1048576) for r in requests):
            raise HardwareNotReady("A QASM exceeds server max_file_bytes; no job submitted")
        maximum = limits.get("max_circuits", 32)
        outputs = []
        for offset in range(0, len(requests), maximum):
            batch = requests[offset:offset+maximum]
            identity = request_id+f".batch-{offset:06d}"
            payload = dict(shots=shots, server_identity=self.server_identity, mapping_version=self.profile.mapping_version,
                           requests=[asdict(r) for r in batch])
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            path = self.journal/(hashlib.sha256(identity.encode()).hexdigest()+".json")
            if path.exists():
                record = json.loads(path.read_text())
                if record.get("payload_sha256") != digest:
                    raise ExecutionUnknown("Journal request ID reused with a changed circuit/mapping/shots")
                if not record.get("job_id"):
                    raise ExecutionUnknown("Previous POST outcome unknown; reconcile manually, never automatically resubmit")
            else:
                record = dict(schema_version=1, request_id=identity, payload_sha256=digest, status="submitting",
                              job_id=None, payload=payload)
                # Exclusive creation and sync BEFORE POST: concurrent callers
                # cannot submit the same logical request twice.
                with path.open("x") as handle:
                    json.dump(record, handle, ensure_ascii=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                parameters = dict(reps=shots, measure_base="Z", use_DD=True, DD_type="X", parallel=True)
                try:
                    response = self.client.post("/v1/jobs", files=[("files", (r.filename, r.qasm.encode(), "application/octet-stream")) for r in batch],
                                                data={"parameters": json.dumps(parameters)})
                    response.raise_for_status()
                    value = response.json()
                    job_id = value.get("job_id") if isinstance(value, dict) else None
                    if type(job_id) not in (str, int) or not str(job_id).strip():
                        raise ValueError("No usable job ID")
                    record.update(job_id=job_id, response=value, status=value.get("status"))
                    write_json(path, record)
                except Exception as exc:
                    raise ExecutionUnknown(f"POST outcome uncertain ({type(exc).__name__}); inspect journal; no automatic retry") from None
            raw = self._poll(record, path)
            outputs.extend(decode(raw, batch, shots, record["job_id"], self.profile.shot_index_base))
        return outputs

    def sample(self, gates, request_id, shots=None):
        shots = self.shots if shots is None else shots
        requests = prepare(gates, self.profile, request_id)
        outputs = self.execute(requests, shots, request_id)
        if [r["basis"] for r in outputs] != ["X", "Z"]:
            raise ValueError("Readout basis association mismatch")
        self.last_metadata = dict(backend="real_qpu_http", real_qpu=True, n_qubits=60, shots=shots,
                                  mapping_version=self.profile.mapping_version, job_ids=[r["job_id"] for r in outputs],
                                  observable_order="X0..X59,Z0..Z59", complete=all(r["complete"] for r in outputs))
        return np.concatenate([r["expectations"] for r in outputs])

    def close(self):
        self.client.close()
