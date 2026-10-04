"""Import-level tests for the initial package skeleton."""

from __future__ import annotations

import importlib
import importlib.util
import sys
import unittest


def _loaded_ray_modules() -> set[str]:
    return {
        module_name
        for module_name in sys.modules
        if module_name == "ray" or module_name.startswith("ray.")
    }


class PackageImportTest(unittest.TestCase):
    def test_import_does_not_implicitly_import_ray(self) -> None:
        ray_modules_before = _loaded_ray_modules()

        package = importlib.import_module("pivotq._internal")

        self.assertEqual(_loaded_ray_modules(), ray_modules_before)
        self.assertEqual(package.__version__, "0.1.0.dev0")
        self.assertEqual(package.__all__, ["__version__"])

    def test_jobs_contract_import_does_not_import_ray(self) -> None:
        ray_modules_before = _loaded_ray_modules()

        jobs = importlib.import_module("pivotq._internal.jobs")

        self.assertEqual(_loaded_ray_modules(), ray_modules_before)
        self.assertIn("RayJobClient", jobs.__all__)
        self.assertIn("RayJobDriverConfig", jobs.__all__)
        self.assertIn("RayJobSpec", jobs.__all__)
        self.assertEqual(jobs.RayJobDriverConfig.__name__, "RayJobDriverConfig")
        self.assertEqual(_loaded_ray_modules(), ray_modules_before)

    def test_qpu_integration_public_contract_import_does_not_import_ray(self) -> None:
        ray_modules_before = _loaded_ray_modules()

        qpu_integration = importlib.import_module("pivotq._internal.qpu_integration")

        self.assertEqual(_loaded_ray_modules(), ray_modules_before)
        self.assertEqual(
            qpu_integration.__all__,
            ["CircuitResult", "QPUCircuitService", "QuantumCircuitRequest"],
        )

    def test_activity_namespace_does_not_expose_archived_ir_or_source(self) -> None:
        importlib.import_module("pivotq._internal")

        self.assertIsNone(importlib.util.find_spec("pivotq._internal.ir"))
        self.assertIsNone(importlib.util.find_spec("pivotq._internal.source"))
        self.assertFalse(
            any(
                name == "ray_quantum_ir" or name.startswith("ray_quantum_ir.")
                for name in sys.modules
            )
        )


if __name__ == "__main__":
    unittest.main()
