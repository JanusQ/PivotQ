"""Unit tests for pure Ray Job contracts."""

from __future__ import annotations

import pickle
import unittest

from pivotq._internal.jobs import (
    RayJobDriverResources,
    RayJobHandle,
    RayJobRuntimeEnvironment,
    RayJobSpec,
    RayJobStatus,
)


class RayJobModelTest(unittest.TestCase):
    def test_spec_is_pickleable_and_builds_fresh_ray_arguments(self) -> None:
        runtime_environment = RayJobRuntimeEnvironment(
            working_dir=".",
            pip_packages=["example-package==1.2.3"],
            env_vars={"ACCESS_TOKEN": "do-not-log", "RUN_MODE": "test"},
        )
        resources = RayJobDriverResources(
            num_cpus=0.5,
            num_gpus=0,
            memory_bytes=1024,
            custom_resources={"driver_slot": 1},
        )
        spec = RayJobSpec(
            submission_id="framework-run-001",
            entrypoint="python run.py --token do-not-log",
            runtime_environment=runtime_environment,
            metadata={"owner": "test"},
            driver_resources=resources,
        )

        restored = pickle.loads(pickle.dumps(spec))

        self.assertEqual(restored, spec)
        runtime_dict = spec.runtime_environment.as_ray_dict()
        self.assertEqual(runtime_dict["working_dir"], ".")
        self.assertEqual(runtime_dict["pip"], ["example-package==1.2.3"])
        self.assertEqual(runtime_dict["env_vars"]["RUN_MODE"], "test")  # type: ignore[index]
        runtime_dict["pip"].append("changed")  # type: ignore[union-attr]
        self.assertEqual(spec.runtime_environment.pip_packages, ("example-package==1.2.3",))
        self.assertEqual(
            resources.as_submit_arguments(),
            {
                "entrypoint_num_cpus": 0.5,
                "entrypoint_num_gpus": 0.0,
                "entrypoint_memory": 1024,
                "entrypoint_resources": {"driver_slot": 1.0},
            },
        )

    def test_representations_do_not_expose_entrypoint_or_environment_values(self) -> None:
        runtime_environment = RayJobRuntimeEnvironment(
            env_vars={"ACCESS_TOKEN": "secret-value"}
        )
        spec = RayJobSpec(
            "run-001",
            "python run.py --token secret-value",
            runtime_environment=runtime_environment,
            metadata={"private": "secret-value"},
        )

        self.assertNotIn("secret-value", repr(runtime_environment))
        self.assertNotIn("secret-value", repr(spec))
        self.assertIn("ACCESS_TOKEN", repr(runtime_environment))
        self.assertIn("entrypoint=<redacted>", repr(spec))

    def test_invalid_job_contracts_are_rejected(self) -> None:
        invalid_calls = [
            lambda: RayJobSpec("bad id", "python run.py"),
            lambda: RayJobSpec("run-001", " python run.py"),
            lambda: RayJobSpec("run-001", "python run.py\nrm -rf x"),
            lambda: RayJobSpec("run-001", "python run.py", runtime_environment={}),  # type: ignore[arg-type]
            lambda: RayJobRuntimeEnvironment(working_dir="https://user:secret@example/code.zip"),
            lambda: RayJobRuntimeEnvironment(working_dir="https:///code.zip"),
            lambda: RayJobRuntimeEnvironment(working_dir="ftp://example/code.zip"),
            lambda: RayJobRuntimeEnvironment(env_vars={"BAD-NAME": "value"}),
            lambda: RayJobRuntimeEnvironment(pip_packages="ray==2.31.0"),
            lambda: RayJobDriverResources(num_cpus=-1),
            lambda: RayJobDriverResources(num_gpus=float("nan")),
            lambda: RayJobDriverResources(memory_bytes=1.5),  # type: ignore[arg-type]
            lambda: RayJobDriverResources(custom_resources={"CPU": 1}),
            lambda: RayJobHandle("bad id"),
        ]

        for call in invalid_calls:
            with self.subTest(call=call), self.assertRaises((TypeError, ValueError)):
                call()

    def test_job_status_is_distinct_and_terminal_states_are_explicit(self) -> None:
        self.assertFalse(RayJobStatus.PENDING.is_terminal)
        self.assertFalse(RayJobStatus.RUNNING.is_terminal)
        self.assertTrue(RayJobStatus.STOPPED.is_terminal)
        self.assertTrue(RayJobStatus.SUCCEEDED.is_terminal)
        self.assertTrue(RayJobStatus.FAILED.is_terminal)


if __name__ == "__main__":
    unittest.main()
