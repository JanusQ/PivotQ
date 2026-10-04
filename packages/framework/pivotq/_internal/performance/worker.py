"""Disposable native worker; results use a file protocol separate from native stdout."""
from __future__ import annotations

import ctypes
import csv
import json
from pathlib import Path
import sys
import tempfile

from .common import empty_output, file_sha256, read_json, write_json
from .native import FusionLibrary, native_path


def execute(request):
    library = FusionLibrary(request["library"])
    operation = request["operation"]
    if operation == "probe":
        library._api.fusion_version.argtypes = []
        library._api.fusion_version.restype = ctypes.c_char_p
        return {"version": library._api.fusion_version().decode(), "library": str(library.path),
                "simulator_sha256": file_sha256(library.path), "interface": "c_api"}
    if operation == "validate":
        with tempfile.TemporaryDirectory(prefix="pivotq-native-validation-") as folder:
            library.validate(Path(request["scenario"]), Path(folder) / "validate.log")
        return None
    folder = Path(request["output"])
    if operation == "raw":
        empty_output(folder)
        handle = library._api.fusion_create(native_path(request["scenario"]))
        if not handle:
            raise ValueError(library._last_error())
        try:
            if library._api.fusion_run_simulation(handle, native_path(folder)) != 0:
                raise ValueError(library._last_error())
            library._api.fusion_simulated_time_us.argtypes = [ctypes.c_void_p]
            library._api.fusion_simulated_time_us.restype = ctypes.c_uint64
            library._api.fusion_wall_clock_s.argtypes = [ctypes.c_void_p]
            library._api.fusion_wall_clock_s.restype = ctypes.c_double
            csv_files = {}
            for path in folder.glob("*.csv"):
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    csv_files[path.name] = list(csv.DictReader(stream))
            summary = csv_files.get("summary.csv", [])
            if not summary or float(summary[0].get("task_completion_ratio", 0)) != 1:
                raise RuntimeError("Simulation did not complete every task; inspect the raw CSV and simulation time limit")
            return {"files": sorted(csv_files), "csv": csv_files, "interface": "c_api",
                    "simulated_time_us": int(library._api.fusion_simulated_time_us(handle)),
                    "wall_clock_s": float(library._api.fusion_wall_clock_s(handle))}
        finally:
            library._api.fusion_destroy(handle)
    if operation == "task":
        from .task import prepare_task, execute_task
        empty_output(folder)
        prepared = prepare_task(library, Path(request["scenario"]), folder)
        return execute_task(library, prepared, request.get("backend", "custom"))
    if operation == "h2o":
        from .h2o import TaskGraph, execute_case
        graph = TaskGraph("h2o")
        graph.nodes = read_json(folder / "task_graph.json")["nodes"]
        return execute_case(library, folder, graph, read_json(folder / "request.json"), request["parameters"])
    raise ValueError(f"Unknown prediction operation: {operation}")


def main():
    request_path, response_path = map(Path, sys.argv[1:])
    try:
        result = execute(read_json(request_path))
        write_json(response_path, {"ok": True, "result": result})
        return 0
    except Exception as error:
        message = str(error)
        unavailable = any(text in message for text in ("Shared library not found", "Cannot load shared library", "is missing fusion_"))
        execution_failure = any(text in message for text in ("did not complete", "Incomplete task event timeline",
            "Duplicate node", "Invalid node event", "Invalid job timeline", "timeline does not match", "fusion_run_simulation failed"))
        write_json(response_path, {"ok": False, "message": message,
                   "category": "unavailable" if unavailable else "execution" if execution_failure else "validation" if isinstance(error, ValueError) else "execution"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
