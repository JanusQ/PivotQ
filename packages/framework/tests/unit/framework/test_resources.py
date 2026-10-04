"""Unit tests for framework-to-Ray resource translation."""

from __future__ import annotations

import unittest

from pivotq._internal.framework import (
    ResourceRequest,
    resource_request_to_ray_options,
)


class RayResourceOptionsTest(unittest.TestCase):
    def test_cpu_gpu_and_custom_resources_are_mapped(self) -> None:
        request = ResourceRequest(
            num_cpus=0.5,
            num_gpus=0.25,
            custom_resources={
                "QPU": 1,
                "qpu_device_test_0": 1,
                "shared_capacity": 0.125,
            },
        )

        options = resource_request_to_ray_options(request)

        self.assertEqual(
            options,
            {
                "num_cpus": 0.5,
                "num_gpus": 0.25,
                "resources": {
                    "QPU": 1.0,
                    "qpu_device_test_0": 1.0,
                    "shared_capacity": 0.125,
                },
            },
        )

    def test_empty_custom_resources_are_omitted_and_copies_are_fresh(self) -> None:
        request = ResourceRequest(num_cpus=0, num_gpus=0)

        first = resource_request_to_ray_options(request)
        second = resource_request_to_ray_options(request)

        self.assertEqual(first, {"num_cpus": 0.0, "num_gpus": 0.0})
        self.assertIsNot(first, second)

    def test_request_type_is_validated(self) -> None:
        with self.assertRaises(TypeError):
            resource_request_to_ray_options(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
