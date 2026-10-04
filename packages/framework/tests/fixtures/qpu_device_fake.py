"""Explicit non-hardware fixture: records uploads and returns fixed counts.

This fixture does not simulate a quantum circuit or establish scientific
correctness. The fixed response is used only to test transport contracts.
"""

from pivotq._internal.qpu_integration.device_adapter import QPUDeviceAdapter, DeviceCircuitResult


class RecordingDeviceAdapter(QPUDeviceAdapter):
    def __init__(self):
        self.exchanges = []
        self.close_count = 0
        self.failure = None

    def _exchange(self, circuits, *, shots, request_id):
        self.exchanges.append((tuple(circuits), shots, request_id))
        if self.failure is not None:
            raise self.failure
        return [
            DeviceCircuitResult(
                circuit.circuit_id, shots, (0, 1, 2), complete=True,
                counts={"100": shots, "000": 0},
            )
            for circuit in circuits
        ]

    def _decode(self, raw, *, request_id):
        return raw

    def close(self):
        self.close_count += 1
