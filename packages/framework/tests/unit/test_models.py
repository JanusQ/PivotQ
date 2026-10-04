"""Unit tests for vendor-neutral domain models."""

from __future__ import annotations

import unittest
import pickle
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from pivotq._internal.models import (
    BackendJobHandle,
    BackendJobStatus,
    BackendSelector,
    CancelOutcome,
    CapabilitySnapshot,
    ConnectionMode,
    DeviceDescriptor,
    DeviceHealth,
    HealthSnapshot,
    OpaquePayload,
    QuantumJobRequest,
    QuantumResult,
    StringMetadata,
)


OBSERVED_AT = datetime(2026, 7, 19, 1, 0, tzinfo=timezone.utc)


def _program() -> OpaquePayload:
    return OpaquePayload(format="openqasm3", version="3.0", data=b"OPENQASM 3;")


class StringMetadataTest(unittest.TestCase):
    def test_mapping_is_frozen_and_sorted(self) -> None:
        metadata = StringMetadata.from_mapping({"vendor": "acme", "region": "test"})

        self.assertEqual(metadata.items, (("region", "test"), ("vendor", "acme")))
        copied = metadata.as_dict()
        copied["region"] = "changed"
        self.assertEqual(metadata.as_dict()["region"], "test")
        with self.assertRaises(FrozenInstanceError):
            metadata.items = ()  # type: ignore[misc]

    def test_invalid_metadata_is_rejected(self) -> None:
        invalid_items = [
            (("duplicate", "a"), ("duplicate", "b")),
            ((" spaced ", "value"),),
            (("key", 1),),
        ]
        for items in invalid_items:
            with self.subTest(items=items), self.assertRaises((TypeError, ValueError)):
                StringMetadata(items)  # type: ignore[arg-type]

        with self.assertRaises(TypeError):
            StringMetadata.from_mapping([("key", "value")])  # type: ignore[arg-type]


class PayloadAndDescriptorTest(unittest.TestCase):
    def test_payload_copies_mutable_bytes(self) -> None:
        source = bytearray(b"circuit")
        payload = OpaquePayload(format="vendor-ir", version="1", data=source)
        source[0] = ord("X")

        self.assertEqual(payload.data, b"circuit")
        self.assertIsInstance(payload.data, bytes)

    def test_invalid_payload_is_rejected(self) -> None:
        invalid_arguments = [
            {"format": "", "version": "1", "data": b"x"},
            {"format": "ir", "version": " 1", "data": b"x"},
            {"format": "ir", "version": "1", "data": b""},
            {"format": "ir", "version": "1", "data": "text"},
            {"format": "ir", "version": "1", "data": b"x", "schema_version": 0},
        ]
        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments), self.assertRaises((TypeError, ValueError)):
                OpaquePayload(**arguments)  # type: ignore[arg-type]

    def test_device_descriptor_preserves_stable_identity(self) -> None:
        descriptor = DeviceDescriptor(
            device_id="qpu-01",
            vendor="acme",
            model="mock-v1",
            connection_mode=ConnectionMode.MOCK,
            hardware_group_id="rack-01",
            metadata=StringMetadata.from_mapping({"site": "ci"}),
        )

        self.assertEqual(descriptor.device_id, "qpu-01")
        self.assertEqual(descriptor.connection_mode, ConnectionMode.MOCK)

    def test_invalid_descriptor_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            DeviceDescriptor("qpu-01", "acme", "v1", "mock")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            DeviceDescriptor(" qpu-01", "acme", "v1", ConnectionMode.MOCK)
        with self.assertRaises(TypeError):
            DeviceDescriptor("qpu-01", "acme", "v1", ConnectionMode.MOCK, metadata={})  # type: ignore[arg-type]


class SnapshotTest(unittest.TestCase):
    def test_capability_snapshot_normalizes_and_expires(self) -> None:
        observed_in_china = datetime(2026, 7, 19, 9, 0, tzinfo=timezone(timedelta(hours=8)))
        snapshot = CapabilitySnapshot(
            device_id="qpu-01",
            observed_at=observed_in_china,
            ttl_seconds=30,
            qubit_count=3,
            native_gates=["x", "cx"],  # type: ignore[arg-type]
            coupling_map=[(0, 1), [1, 2]],  # type: ignore[list-item]
            max_shots=4096,
            supports_cancel=True,
        )

        self.assertEqual(snapshot.observed_at, OBSERVED_AT)
        self.assertEqual(snapshot.native_gates, ("x", "cx"))
        self.assertEqual(snapshot.coupling_map, ((0, 1), (1, 2)))
        self.assertFalse(snapshot.is_stale(OBSERVED_AT + timedelta(seconds=29)))
        self.assertTrue(snapshot.is_stale(OBSERVED_AT + timedelta(seconds=30)))

    def test_invalid_capability_snapshot_is_rejected(self) -> None:
        valid = {
            "device_id": "qpu-01",
            "observed_at": OBSERVED_AT,
            "ttl_seconds": 30,
            "qubit_count": 3,
        }
        invalid_overrides = [
            {"observed_at": datetime(2026, 7, 19, 1, 0)},
            {"ttl_seconds": 0},
            {"ttl_seconds": float("nan")},
            {"ttl_seconds": float("inf")},
            {"qubit_count": 0},
            {"qubit_count": True},
            {"native_gates": ("x", "x")},
            {"coupling_map": ((0, 0),)},
            {"coupling_map": ((0, 3),)},
            {"coupling_map": ((0, 1), (0, 1))},
            {"max_shots": 0},
            {"supports_cancel": 1},
        ]
        for override in invalid_overrides:
            arguments = valid | override
            with self.subTest(override=override), self.assertRaises((TypeError, ValueError)):
                CapabilitySnapshot(**arguments)

    def test_health_snapshot_keeps_dynamic_state_separate(self) -> None:
        snapshot = HealthSnapshot(
            device_id="qpu-01",
            observed_at=OBSERVED_AT,
            ttl_seconds=5,
            status=DeviceHealth.DEGRADED,
            available_qubits=[0, 2],  # type: ignore[arg-type]
            queue_depth=2,
            message="calibration drift",
        )

        self.assertEqual(snapshot.available_qubits, (0, 2))
        self.assertTrue(snapshot.is_stale(OBSERVED_AT + timedelta(seconds=5)))

    def test_invalid_health_snapshot_is_rejected(self) -> None:
        valid = {
            "device_id": "qpu-01",
            "observed_at": OBSERVED_AT,
            "ttl_seconds": 5,
            "status": DeviceHealth.ONLINE,
        }
        invalid_overrides = [
            {"status": "online"},
            {"available_qubits": (0, 0)},
            {"available_qubits": (-1,)},
            {"queue_depth": -1},
            {"message": " padded "},
        ]
        for override in invalid_overrides:
            with self.subTest(override=override), self.assertRaises((TypeError, ValueError)):
                HealthSnapshot(**(valid | override))


class JobModelTest(unittest.TestCase):
    def test_request_handle_and_result_form_a_stable_chain(self) -> None:
        selector = BackendSelector(vendor="acme", min_qubits=2, required_gates=["x", "cx"])  # type: ignore[arg-type]
        request = QuantumJobRequest(
            framework_job_id="framework-job-01",
            idempotency_key="request-01",
            program=_program(),
            shots=1024,
            selector=selector,
            deadline=OBSERVED_AT + timedelta(minutes=10),
        )
        handle = BackendJobHandle(
            framework_job_id=request.framework_job_id,
            idempotency_key=request.idempotency_key,
            backend_job_id="backend-job-01",
            device_id="qpu-01",
            submitted_at=OBSERVED_AT,
        )
        result = QuantumResult(
            framework_job_id=handle.framework_job_id,
            backend_job_id=handle.backend_job_id,
            device_id=handle.device_id,
            completed_at=OBSERVED_AT + timedelta(seconds=3),
            payload=OpaquePayload(format="counts-json", version="1", data=b'{"0": 1024}'),
            shots=request.shots,
        )

        self.assertEqual(request.selector.required_gates, ("x", "cx"))
        self.assertEqual(handle.idempotency_key, request.idempotency_key)
        self.assertEqual(result.backend_job_id, handle.backend_job_id)

    def test_invalid_job_models_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BackendSelector(min_qubits=0)
        with self.assertRaises(ValueError):
            BackendSelector(required_gates=("x", "x"))
        with self.assertRaises(TypeError):
            QuantumJobRequest("job", "key", _program(), True)
        with self.assertRaises(TypeError):
            QuantumJobRequest("job", "key", b"program", 10)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            QuantumJobRequest("job", "key", _program(), 10, deadline=datetime(2026, 7, 19))
        with self.assertRaises(ValueError):
            BackendJobHandle("job", "key", "backend", "qpu", datetime(2026, 7, 19))
        with self.assertRaises(TypeError):
            QuantumResult("job", "backend", "qpu", OBSERVED_AT, b"result", 10)  # type: ignore[arg-type]

    def test_unknown_and_reconciling_states_are_explicit(self) -> None:
        self.assertEqual(BackendJobStatus.RECONCILING.value, "reconciling")
        self.assertEqual(BackendJobStatus.RESULT_UNKNOWN.value, "result_unknown")
        self.assertEqual(CancelOutcome.TOO_LATE.value, "too_late")

    def test_models_are_serializable_for_future_ray_transport(self) -> None:
        request = QuantumJobRequest("job-01", "key-01", _program(), 100)

        restored = pickle.loads(pickle.dumps(request))

        self.assertEqual(restored, request)


if __name__ == "__main__":
    unittest.main()
