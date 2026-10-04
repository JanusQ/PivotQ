"""把融合框架的逐电路概率结果适配为项目的 14 维量子特征。"""

from __future__ import annotations

from copy import deepcopy
import inspect
import math
from threading import Lock
import time
from typing import Any, Callable, Mapping, Sequence

import torch

from ...api.contracts import QuantumFeatureRequest, QuantumFeatureResponse
from ...api.quantum import QuantumFeatureAPI
from ...quantum.adapt_water_statevector import (
    ZX14_OBSERVABLES,
    water_symmetric_angle_features,
)
from ...quantum.qiskit_f2 import build_bound_f2_circuit_pair


_MEASUREMENT_QUBITS = (0, 1, 2)
_BITSTRINGS = tuple(f"{value:03b}" for value in range(8))
_PARITY_SUPPORTS = (
    (0,),
    (1,),
    (2,),
    (0, 1),
    (0, 2),
    (1, 2),
    (0, 1, 2),
)


class FusionQPUCircuitFeatureExtractor(QuantumFeatureAPI):
    """每个 H₂O 几何上传 Z/X 两条 Qiskit ``QuantumCircuit``。"""

    def __init__(
        self,
        service: Any,
        *,
        shots: int = 3000,
        physical_qubits: Sequence[str] | None = None,
        request_factory: Callable[..., Any] | None = None,
    ) -> None:
        if isinstance(shots, bool) or int(shots) <= 0:
            raise ValueError("QPU shots 必须是正整数。")
        self._service = service
        self._shots = int(shots)
        self._physical_qubits = (
            None if physical_qubits is None else tuple(str(value) for value in physical_qubits)
        )
        if self._physical_qubits is not None:
            if len(self._physical_qubits) != 3 or any(not value for value in self._physical_qubits):
                raise ValueError("physical_qubits 必须包含三个非空物理比特标识。")
            if len(set(self._physical_qubits)) != 3:
                raise ValueError("physical_qubits 不能包含重复标识。")
        self._request_factory = request_factory
        self._call_index = 0
        self._call_lock = Lock()

    def describe(self) -> dict[str, Any]:
        return {
            "backend_name": "fusion_qpu_circuit_service_v1",
            "api_version": "1.0",
            "framework": "qiskit+pivotq._internal",
            "real_hardware": True,
            "num_qubits": 3,
            "shots_per_measurement_basis": self._shots,
            "measurement_qubits": list(_MEASUREMENT_QUBITS),
            "measurement_basis_count": 2,
            "supported_observables": list(ZX14_OBSERVABLES),
            "result_bit_order": "q0,q1,q2 left-to-right",
            "basis_identity_source": (
                "QuantumCircuitRequest.measurement_basis with matching circuit_id suffix"
            ),
            "measurement_basis_round_trip_required": True,
            "physical_qubits": (
                None if self._physical_qubits is None else list(self._physical_qubits)
            ),
        }

    def extract_features(self, request: QuantumFeatureRequest) -> QuantumFeatureResponse:
        self._validate_request(request)
        started = time.perf_counter()
        angles = water_symmetric_angle_features(
            request.molecular_geometries_A.to(dtype=torch.float64, device="cpu"),
            request.encoding_spec,
        )
        factory = self._request_factory or _load_quantum_circuit_request()
        circuit_requests: list[Any] = []
        expected_ids: list[str] = []
        expected_bases: list[str] = []
        for sample_index, sample_angles in enumerate(angles.tolist()):
            z_circuit, x_circuit = build_bound_f2_circuit_pair(
                sample_angles,
                request.circuit_spec,
            )
            id_prefix = f"{request.request_id}.{sample_index:06d}"
            for basis, circuit in (("Z", z_circuit), ("X", x_circuit)):
                circuit_id = f"{id_prefix}.{basis}"
                expected_ids.append(circuit_id)
                expected_bases.append(basis)
                try:
                    circuit_requests.append(
                        factory(
                            circuit_id=circuit_id,
                            circuit=circuit,
                            measurement_basis=basis,
                        )
                    )
                except TypeError as error:
                    raise RuntimeError(
                        "当前 pivotq._internal.QuantumCircuitRequest 不支持必填的 "
                        "measurement_basis；请部署与最新版 AIMD QPU 接口文档一致的融合框架。"
                    ) from error

        step = self._next_call_index()
        results = self._run_circuits(step=step, circuits=circuit_requests)
        normalized = _validate_results(
            results,
            expected_ids,
            expected_bases,
            self._shots,
        )
        feature_rows: list[list[float]] = []
        variance_rows: list[list[float]] = []
        for sample_index in range(len(request.sample_ids)):
            z_result = normalized[2 * sample_index]
            x_result = normalized[2 * sample_index + 1]
            z_values = _parity_expectations(z_result["probabilities"])
            x_values = _parity_expectations(x_result["probabilities"])
            values = z_values + x_values
            feature_rows.append(values)
            variance_rows.append(
                [max(0.0, 1.0 - value * value) / float(self._shots) for value in values]
            )

        features = torch.tensor(feature_rows, dtype=torch.float64)
        variances = torch.tensor(variance_rows, dtype=torch.float64)
        return QuantumFeatureResponse(
            request_id=request.request_id,
            sample_ids=request.sample_ids,
            feature_names=ZX14_OBSERVABLES,
            features=features,
            feature_variances=variances,
            execution_metrics={
                "batch_size": len(request.sample_ids),
                "circuit_evaluations": len(request.sample_ids),
                "measurement_basis_count": 2,
                "measurement_circuit_settings": len(circuit_requests),
                "shots": self._shots,
                "total_physical_executions": len(circuit_requests) * self._shots,
                "qpu_service_step": step,
                "elapsed_seconds": time.perf_counter() - started,
            },
            backend_metadata={
                **self.describe(),
                "encoding": deepcopy(request.encoding_spec),
                "circuit_spec": deepcopy(request.circuit_spec),
                "atomic_numbers": list(request.atomic_numbers or ()),
                "submitted_circuit_ids": expected_ids,
            },
        )

    def _validate_request(self, request: QuantumFeatureRequest) -> None:
        if request.bond_lengths_A is not None or request.molecular_geometries_A is None:
            raise ValueError("F2 QPU 适配层要求 molecular_geometries_A。")
        if request.molecular_geometries_A.shape[1:] != (3, 3):
            raise ValueError("H2O geometries 必须为 (B,3,3)。")
        if tuple(request.atomic_numbers or ()) != (8, 1, 1):
            raise ValueError("F2 QPU 适配层要求 atomic_numbers=(8,1,1)。")
        if tuple(request.observables) != ZX14_OBSERVABLES:
            raise ValueError("QPU 返回必须还原为固定顺序的 7Z+7X 共 14 个 Pauli 特征。")
        requested_shots = request.execution_spec.get("shots", self._shots)
        if requested_shots is not None and int(requested_shots) != self._shots:
            raise ValueError("单次 QuantumFeatureRequest 的 shots 必须与 QPU 适配层配置一致。")

    def _next_call_index(self) -> int:
        with self._call_lock:
            step = self._call_index
            if step > 999_999:
                raise RuntimeError("本次 AIMD run 的 QPU 调用次数超过融合接口上限 999999。")
            self._call_index += 1
            return step

    def _run_circuits(self, *, step: int, circuits: Sequence[Any]) -> list[Mapping[str, Any]]:
        method = self._service.run_quantum_circuits
        parameters = inspect.signature(method).parameters
        arguments: dict[str, Any] = {
            "step": step,
            "circuits": circuits,
            "shots": self._shots,
        }
        if "measurement_qubits" in parameters:
            arguments["measurement_qubits"] = list(_MEASUREMENT_QUBITS)
        if "physical_qubits" in parameters:
            if self._physical_qubits is None:
                raise ValueError(
                    "当前融合框架接口要求 physical_qubits；请在 qpu.execution.physical_qubits "
                    "配置三个由 QPU 侧确认的物理比特标识。"
                )
            arguments["physical_qubits"] = list(self._physical_qubits)
        return list(method(**arguments))


def _load_quantum_circuit_request():
    try:
        from pivotq._internal.qpu_integration import QuantumCircuitRequest
    except ImportError as error:
        raise RuntimeError(
            "融合 QPU 运行需要 pivotq._internal.qpu_integration.QuantumCircuitRequest。"
        ) from error
    return QuantumCircuitRequest


def _validate_results(
    results: Sequence[Mapping[str, Any]],
    expected_ids: Sequence[str],
    expected_bases: Sequence[str],
    requested_shots: int,
) -> list[dict[str, Any]]:
    if len(results) != len(expected_ids):
        raise ValueError(
            f"QPU 返回 {len(results)} 条结果，但本批提交了 {len(expected_ids)} 条电路。"
        )
    normalized: list[dict[str, Any]] = []
    for index, (raw, expected_id, expected_basis) in enumerate(
        zip(results, expected_ids, expected_bases)
    ):
        if not isinstance(raw, Mapping):
            raise TypeError(f"QPU result[{index}] 必须是字典。")
        circuit_id = raw.get("circuit_id")
        if circuit_id != expected_id:
            raise ValueError(
                f"QPU result[{index}] circuit_id 顺序错误：期望 {expected_id!r}，收到 {circuit_id!r}。"
            )
        measurement_basis = raw.get("measurement_basis")
        if measurement_basis != expected_basis:
            raise ValueError(
                f"QPU result[{index}] measurement_basis 应为 {expected_basis!r}，"
                f"收到 {measurement_basis!r}。"
            )
        shots = raw.get("shots")
        if isinstance(shots, bool) or shots != requested_shots:
            raise ValueError(
                f"QPU result[{index}] shots 必须等于请求值 {requested_shots}。"
            )
        measurement_qubits = raw.get("measurement_qubits")
        if list(measurement_qubits or ()) != list(_MEASUREMENT_QUBITS):
            raise ValueError(f"QPU result[{index}] measurement_qubits 必须为 [0, 1, 2]。")
        raw_probabilities = raw.get("probabilities")
        if not isinstance(raw_probabilities, Mapping):
            raise TypeError(f"QPU result[{index}].probabilities 必须是字典。")
        if set(raw_probabilities) != set(_BITSTRINGS):
            raise ValueError(
                f"QPU result[{index}] 必须包含 000 到 111 的全部八个三比特状态。"
            )
        probabilities = {key: float(raw_probabilities[key]) for key in _BITSTRINGS}
        if any(not math.isfinite(value) or value < 0.0 or value > 1.0 for value in probabilities.values()):
            raise ValueError(f"QPU result[{index}] 包含非法概率。")
        if not math.isclose(sum(probabilities.values()), 1.0, abs_tol=1.0e-6, rel_tol=1.0e-6):
            raise ValueError(f"QPU result[{index}] 概率和不为 1。")
        normalized.append(
            {
                "circuit_id": circuit_id,
                "measurement_basis": measurement_basis,
                "shots": shots,
                "measurement_qubits": list(_MEASUREMENT_QUBITS),
                "probabilities": probabilities,
            }
        )
    return normalized


def _parity_expectations(probabilities: Mapping[str, float]) -> list[float]:
    """按融合接口的直接位序 ``q0 q1 q2`` 计算七个非空 parity。"""

    values: list[float] = []
    for support in _PARITY_SUPPORTS:
        expectation = 0.0
        for bitstring in _BITSTRINGS:
            parity = sum(int(bitstring[qubit]) for qubit in support) % 2
            expectation += (-1.0 if parity else 1.0) * probabilities[bitstring]
        values.append(expectation)
    return values


__all__ = ["FusionQPUCircuitFeatureExtractor"]
