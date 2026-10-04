import ctypes
import os
import sys
from pathlib import Path

from .common import ROOT, empty_output, require


LIBRARY_NAME = ("QPerfSim.dll" if sys.platform == "win32" else
                "libfusion.dylib" if sys.platform == "darwin" else "libfusion.so")
LIBRARY_CANDIDATES = tuple(ROOT / folder / LIBRARY_NAME for folder in ("lib", "build", "build/Release"))
DEFAULT_LIBRARY = next((path for path in LIBRARY_CANDIDATES if path.is_file()), LIBRARY_CANDIDATES[0])


def native_path(path):
    encoded = os.fsencode(Path(path).resolve())
    require(b"\0" not in encoded, f"Path contains a null byte: {path}")
    return encoded


class FusionLibrary:
    def __init__(self, path):
        self.path = Path(path).resolve()
        require(self.path.is_file(),
                f"Shared library not found: {self.path}; build target fusion or supply --library")
        try:
            self._api = ctypes.CDLL(str(self.path))
        except OSError as error:
            raise ValueError(f"Cannot load shared library {self.path}; check the OS, architecture "
                             f"and runtime dependencies: {error}") from error
        self._bind_functions()

    @property
    def version(self):
        self._api.fusion_version.argtypes = []
        self._api.fusion_version.restype = ctypes.c_char_p
        return self._api.fusion_version().decode("utf-8")

    def _bind_functions(self):
        pointer, string, integer = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
        signatures = {
            "fusion_version": ([], string),
            "fusion_validate": ([string], integer),
            "fusion_create": ([string], pointer),
            "fusion_destroy": ([pointer], None),
            "fusion_run_simulation": ([pointer, string], integer),
            "fusion_export_trace": ([pointer, string], integer),
            "fusion_last_error": ([], pointer),
            "fusion_free_string": ([pointer], None),
            "fusion_simulated_time_us": ([pointer], ctypes.c_uint64),
            "fusion_wall_clock_s": ([pointer], ctypes.c_double),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self._api, name, None)
            require(function is not None,
                    f"Shared library {self.path} is missing {name}; use the library supplied with these scripts")
            function.argtypes = arguments
            function.restype = result

    def _last_error(self):
        pointer = self._api.fusion_last_error()
        if not pointer:
            return "Native library did not provide error details"
        try:
            return ctypes.string_at(pointer).decode("utf-8", errors="replace")
        finally:
            self._api.fusion_free_string(pointer)

    def _check(self, success, operation, scenario, log):
        message = (f"{operation} succeeded: {scenario}" if success else
                   f"{operation} failed for {scenario}: {self._last_error()}")
        log.write_text(message + "\n", encoding="utf-8")
        require(success, f"{message}; inspect {log}")

    def validate(self, scenario, log):
        status = self._api.fusion_validate(native_path(scenario))
        self._check(status == 1, "fusion_validate", scenario, log)

    def _execute(self, operation, scenario, output, log):
        scenario_path, output_path = native_path(scenario), native_path(output)
        empty_output(output)
        handle = self._api.fusion_create(scenario_path)
        if not handle:
            self._check(False, "fusion_create", scenario, log)
        try:
            status = getattr(self._api, operation)(handle, output_path)
            self._check(status == 0, operation, scenario, log)
        finally:
            self._api.fusion_destroy(handle)

    def export_trace(self, scenario, output, log):
        self._execute("fusion_export_trace", scenario, output, log)

    def run(self, scenario, output, log):
        self._execute("fusion_run_simulation", scenario, output, log)
