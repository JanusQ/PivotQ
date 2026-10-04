"""One isolated execution boundary for the SDK and historical adapters."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

from ...errors import ExecutionError, TimeoutError, UnavailableError, ValidationError
from .native import DEFAULT_LIBRARY


class PredictionRunner:
    def __init__(self, library=None, native_runtime=None, timeout=180):
        if type(timeout) not in (int, float) or not 0 < timeout < float("inf"):
            raise ValueError("timeout must be a finite positive number of seconds")
        configured_library = library if library is not None else os.environ.get("QPERFSIM_LIBRARY")
        if configured_library is None and os.environ.get("QPERFSIM_ROOT"):
            root = Path(os.environ["QPERFSIM_ROOT"]).expanduser()
            candidates = (root / "lib/libfusion.so", root / "libfusion.so",
                          root / "native/linux-x86_64/libfusion.so", root / "fusion_dist/libfusion.so")
            configured_library = next((path for path in candidates if path.is_file()), candidates[0])
        self.library = Path(configured_library if configured_library is not None else DEFAULT_LIBRARY).expanduser().resolve()
        configured = native_runtime or os.environ.get("FUSION_QPERFSIM_RUNTIME")
        self.native_runtime = Path(configured).expanduser().resolve() if configured else None
        self.timeout = timeout

    def _command(self):
        if platform.system() != "Linux" or platform.machine().lower() not in ("x86_64", "amd64"):
            raise UnavailableError("The bundled prediction engine requires Linux x86-64")
        command = [sys.executable]
        if self.native_runtime:
            directory = self.native_runtime / "usr/lib/x86_64-linux-gnu"
            loader = directory / "ld-linux-x86-64.so.2"
            if not loader.is_file():
                raise UnavailableError(f"Prediction runtime loader not found: {loader}")
            command = [str(loader), "--library-path", str(directory), sys.executable]
        return command + ["-B", "-m", "pivotq._internal.performance.worker"]

    def _call(self, operation, **payload):
        command = self._command()
        with tempfile.TemporaryDirectory(prefix="pivotq-prediction-worker-") as folder:
            folder = Path(folder)
            request, response = folder / "request.json", folder / "response.json"
            request.write_text(json.dumps({"operation": operation, "library": str(self.library), **payload}, allow_nan=False), encoding="utf-8")
            try:
                process = subprocess.run(command + [str(request), str(response)], capture_output=True, text=True,
                                         timeout=min(self.timeout, 10) if operation == "probe" else self.timeout)
            except subprocess.TimeoutExpired as error:
                self._record_logs(payload, error.stdout, error.stderr, {"ok": False, "category": "timeout", "message": "Worker terminated after timeout"})
                raise TimeoutError(f"Performance prediction exceeded its {self.timeout}s timeout; worker terminated") from error
            except OSError as error:
                self._record_logs(payload, "", str(error), {"ok": False, "category": "unavailable", "message": str(error)})
                raise UnavailableError(f"Cannot start performance prediction worker: {error}") from error
            record, protocol_error, response_text = None, None, ""
            try:
                response_text = response.read_text(encoding="utf-8")
                record = json.loads(response_text)
                if not isinstance(record, dict) or type(record.get("ok")) is not bool:
                    raise ValueError("response must contain a boolean ok field")
                if record["ok"] and ("result" not in record or (operation != "validate" and not isinstance(record["result"], dict))):
                    raise ValueError("response result does not match the requested operation")
            except (OSError, UnicodeError, ValueError) as error:
                protocol_error = f"Invalid performance worker response (exit code {process.returncode}): {error}"
                record = {"ok": False, "category": "execution", "message": protocol_error,
                          "raw_response": response_text, "returncode": process.returncode}
            self._record_logs(payload, process.stdout, process.stderr, record)
            if protocol_error:
                details = (process.stderr or process.stdout)[-4000:].strip()
                raise ExecutionError(protocol_error + (f"; {details}" if details else ""))
            if record["ok"] and process.returncode == 0:
                return record["result"]
            category = record.get("category")
            error_type = {"unavailable": UnavailableError, "validation": ValidationError}.get(category, ExecutionError)
            message = record.get("message")
            raise error_type(message.strip() if isinstance(message, str) and message.strip() else "Performance prediction worker failed")

    @staticmethod
    def _record_logs(payload, stdout, stderr, response):
        if "output" not in payload:
            return
        folder = Path(payload["output"])
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for name, value in (("stdout", stdout), ("stderr", stderr)):
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="replace")
                (folder / f"worker.{name}.log").write_text(value or "", encoding="utf-8")
            (folder / "worker.response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            # Never hide the operation failure when its destination is unwritable.
            pass

    def probe(self):
        try:
            return {"available": True, **self._call("probe"), "reason": None}
        except (UnavailableError, ExecutionError, TimeoutError, ValidationError) as error:
            return {"available": False, "library": str(self.library), "reason": str(error)}

    def run_task(self, scenario_path, output_dir, backend="custom"):
        return self._call("task", scenario=str(Path(scenario_path).resolve()),
                          output=str(Path(output_dir).resolve()), backend=backend)

    def validate(self, scenario_path):
        self._call("validate", scenario=str(Path(scenario_path).resolve()))

    def run_raw(self, scenario_path, output_dir):
        return self._call("raw", scenario=str(Path(scenario_path).resolve()), output=str(Path(output_dir).resolve()))

    def run_h2o(self, case_dir, parameters):
        return self._call("h2o", output=str(Path(case_dir).resolve()), parameters=parameters)
