"""P8.1 offline active-wheel content and cold-import gate."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import venv
import zipfile

from setuptools.build_meta import build_wheel


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class CleanCorePackageTest(unittest.TestCase):
    def test_offline_wheel_install_and_cold_import_are_application_neutral(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ray-quantum-p81-baseline-") as root_text:
            root = Path(root_text)
            project = root / "project"
            source = project
            distribution = root / "dist"
            project.mkdir()
            distribution.mkdir()
            shutil.copy2(_REPOSITORY_ROOT / "pyproject.toml", project)
            shutil.copy2(_REPOSITORY_ROOT / "README.md", project)
            shutil.copy2(_REPOSITORY_ROOT / "setup.py", project)
            shutil.copy2(_REPOSITORY_ROOT / "MANIFEST.in", project)
            shutil.copytree(
                _REPOSITORY_ROOT / "pivotq",
                source / "pivotq",
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", "*.pyo", "*.zip"
                ),
            )
            # Test exclusion with a sentinel, without reading/copying history.
            historical = source / "ray_quantum_ir"
            historical.mkdir()
            (historical / "__init__.py").write_text("raise RuntimeError('excluded')\n")

            previous = Path.cwd()
            try:
                os.chdir(project)
                wheel_name = build_wheel(str(distribution))
            finally:
                os.chdir(previous)
            wheel_path = distribution / wheel_name
            self.assertTrue(wheel_path.is_file())
            self.assertTrue(wheel_name.endswith("-py3-none-linux_x86_64.whl"))

            with zipfile.ZipFile(wheel_path) as archive:
                names = tuple(archive.namelist())
                self.assertIn("pivotq/__init__.py", names)
                self.assertIn("pivotq/jobs/driver.py", names)
                self.assertIn("pivotq/_internal/__init__.py", names)
                self.assertIn("pivotq/_internal/performance/lib/libfusion.so", names)
                self.assertIn("pivotq/_internal/performance/include/fusion_api.h", names)
                self.assertIn("pivotq/_internal/performance/examples/h2o/prediction_parameters.json", names)
                self.assertFalse(any(name.startswith("ray_quantum/") for name in names))
                self.assertIn("pivotq/_internal/jobs/driver.py", names)
                self.assertIn("pivotq/_internal/observability/events.py", names)
                self.assertIn("pivotq/_internal/qpu_integration/service.py", names)
                self.assertIn(
                    "pivotq/_internal/qpu_integration/device_adapter.py",
                    names,
                )
                self.assertFalse(
                    any(name.startswith("ray_quantum_ir/") for name in names)
                )
                self.assertFalse(
                    any(
                        name.startswith("pivotq/_internal/ir/")
                        or name.startswith("pivotq/_internal/source/")
                        for name in names
                    )
                )
                self.assertFalse(
                    any(
                        "__pycache__" in name
                        or name.endswith((".pyc", ".pyo", ".zip"))
                        for name in names
                    )
                )
                metadata_name = next(
                    name for name in names if name.endswith(".dist-info/METADATA")
                )
                metadata = archive.read(metadata_name).decode("utf-8")
                wheel_metadata = archive.read(next(name for name in names if name.endswith(".dist-info/WHEEL"))).decode()
                self.assertIn("Root-Is-Purelib: false", wheel_metadata)
                self.assertIn("Tag: py3-none-linux_x86_64", wheel_metadata)
                lowered = metadata.lower()
                self.assertNotIn("requires-dist: ase", lowered)
                self.assertNotIn("requires-dist: aimd", lowered)
                self.assertNotIn("requires-dist: m" + "lir", lowered)
                self.assertNotIn("requires-dist: l" + "lvm", lowered)
                self.assertNotIn("provides-extra: openqasm3", lowered)
                self.assertNotIn("qiskit-qasm3-import", lowered)

            environment = root / "venv"
            venv.EnvBuilder(with_pip=False).create(environment)
            python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            located = subprocess.run(
                (
                    str(python),
                    "-c",
                    "import sysconfig; print(sysconfig.get_paths()['purelib'])",
                ),
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(located.returncode, 0, located.stderr)
            installed = Path(located.stdout.strip())
            with zipfile.ZipFile(wheel_path) as archive:
                archive.extractall(installed)

            script = """
import importlib.util
from pathlib import Path
import sys

import pivotq
import pivotq.performance
import pivotq.components
import pivotq.workflow
import pivotq.observability
import pivotq.providers
from pivotq.jobs import JobClient, JobSpec
from pivotq.performance import Predictor, Workload, Hardware
import pivotq.jobs.driver
import pivotq._internal
import pivotq._internal.jobs
import pivotq._internal.observability
import pivotq._internal.qpu_integration
import pivotq._internal.qpu_integration.qasm3_export
import pivotq._internal.qpu_integration.device_adapter

installed = Path(pivotq._internal.__file__).resolve()
assert "site-packages" in installed.parts, installed
assert importlib.util.find_spec("pivotq._internal.ir") is None
assert importlib.util.find_spec("pivotq._internal.source") is None
assert importlib.util.find_spec("ray_quantum_ir") is None
assert importlib.util.find_spec("ray_quantum") is None
assert pivotq.Runtime is not None
assert pivotq.QuantumResult is not None
# Pure validation/preview works without any optional runtime dependencies.
client = JobClient("http://127.0.0.1:8265")
predictor = Predictor(library="/not-present/libfusion.so")
workload = Workload()
workload.cpu("prepare", duration_seconds=0.001)
assert len(predictor.preview(workload, Hardware())["task_graph"]["nodes"]) == 1
assert "libfusion.so" not in Path("/proc/self/maps").read_text()
assert not any(name == "ray" or name.startswith("ray.") for name in sys.modules)
assert not any(name == "qiskit" or name.startswith("qiskit.") for name in sys.modules)
assert not any(name == "pyqos" or name.startswith("pyqos.") for name in sys.modules)
assert "ase" not in sys.modules
assert not any(name == "aimd" or name.startswith("aimd.") for name in sys.modules)
print(installed)
"""
            clean_environment = dict(os.environ)
            clean_environment.pop("PYTHONPATH", None)
            clean_environment["PYTHONNOUSERSITE"] = "1"
            imported = subprocess.run(
                (str(python), "-c", script),
                cwd=root,
                env=clean_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(imported.returncode, 0, imported.stderr)
            self.assertTrue(imported.stdout.strip().startswith(str(installed)))


if __name__ == "__main__":
    unittest.main()
