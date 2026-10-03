"""构造可直接交给融合框架的已绑定三比特 F2 Qiskit 电路。"""

from __future__ import annotations

import math
from typing import Any, Sequence


F2_OPERATOR_SEQUENCE = ("IYZ", "YII", "YZI", "IIX", "YII")


def build_bound_f2_circuit_pair(
    encoding_angles: Sequence[float],
    circuit_spec: dict[str, Any],
):
    """返回无经典位、无测量、无未绑定参数的 ``(Z, X)`` 电路。

    Z 电路只包含冻结的 F2 态制备；X 电路在相同态制备后追加逐比特
    X→Z 换基。融合框架负责在电路末尾执行计算基测量。
    """

    try:
        from qiskit import QuantumCircuit
    except ImportError as error:
        raise RuntimeError(
            "QPU 电路适配层需要 qiskit；融合运行环境请安装项目锁定的 Qiskit 版本。"
        ) from error

    angles = tuple(float(value) for value in encoding_angles)
    if len(angles) != 3 or any(not math.isfinite(value) for value in angles):
        raise ValueError("F2 encoding_angles 必须包含三个有限浮点数。")
    _validate_circuit_spec(circuit_spec)
    seed_parameters = tuple(float(value) for value in circuit_spec["seed_parameters"])
    adapt_parameters = tuple(float(value) for value in circuit_spec["adapt_parameters"])
    if any(not math.isfinite(value) for value in seed_parameters + adapt_parameters):
        raise ValueError("F2 冻结量子参数必须全部为有限浮点数。")

    preparation = QuantumCircuit(3, name="h2o_f2a2_z_input")
    for qubit, angle in enumerate(angles):
        preparation.ry(angle, qubit)
    for qubit in range(3):
        preparation.ry(seed_parameters[qubit], qubit)
    preparation.cz(0, 1)
    preparation.cz(1, 2)
    for qubit in range(3):
        _native_rx(preparation, seed_parameters[3 + qubit], qubit)
    for word, angle in zip(F2_OPERATOR_SEQUENCE, adapt_parameters):
        _pauli_rotation(preparation, word, angle)

    preparation.metadata = {
        "model": "H2O_F2A2_R1_DROP_XXX_MLP_ONLY",
        "measurement_basis": "Z",
        "logical_qubit_order": "q0,q1,q2 correspond to Pauli word characters left-to-right",
        "adapt_operators": list(F2_OPERATOR_SEQUENCE),
    }
    x_circuit = preparation.copy(name="h2o_f2a2_x_input")
    for qubit in range(3):
        _native_h(x_circuit, qubit)
    x_circuit.metadata = {**dict(preparation.metadata or {}), "measurement_basis": "X"}
    return preparation, x_circuit


def _validate_circuit_spec(spec: dict[str, Any]) -> None:
    if int(spec.get("num_qubits", 3)) != 3:
        raise ValueError("F2 QPU 电路固定使用三个逻辑比特。")
    if str(spec.get("seed", "native")).lower() != "native":
        raise ValueError("F2 QPU 电路只支持冻结的 native seed。")
    connectivity = tuple(tuple(int(value) for value in edge) for edge in spec.get("connectivity", ()))
    if connectivity != ((0, 1), (1, 2)):
        raise ValueError("F2 QPU 电路固定使用线性连接 (0,1),(1,2)。")
    if str(spec.get("entangler_gate", "cz")).lower() != "cz":
        raise ValueError("F2 QPU 电路固定使用 CZ 纠缠门。")
    if bool(spec.get("data_reuploading", False)):
        raise ValueError("F2 QPU 电路不允许 data re-uploading。")
    operators = tuple(str(value).upper() for value in spec.get("selected_operators", ()))
    if operators != F2_OPERATOR_SEQUENCE:
        raise ValueError("F2 QPU 电路必须使用完整冻结算符序列 IYZ,YII,YZI,IIX,YII。")
    if len(tuple(spec.get("seed_parameters", ()))) != 6:
        raise ValueError("F2 native seed 必须包含六个冻结参数。")
    if len(tuple(spec.get("adapt_parameters", ()))) != 5:
        raise ValueError("F2 ADAPT 电路必须包含五个冻结参数。")


def _native_h(circuit, qubit: int) -> None:
    circuit.rz(math.pi, qubit)
    circuit.ry(math.pi / 2.0, qubit)


def _native_h_inverse(circuit, qubit: int) -> None:
    circuit.ry(-math.pi / 2.0, qubit)
    circuit.rz(-math.pi, qubit)


def _native_rx(circuit, angle: float, qubit: int) -> None:
    circuit.rz(math.pi / 2.0, qubit)
    circuit.ry(angle, qubit)
    circuit.rz(-math.pi / 2.0, qubit)


def _native_rx_inverse(circuit, angle: float, qubit: int) -> None:
    circuit.rz(math.pi / 2.0, qubit)
    circuit.ry(-angle, qubit)
    circuit.rz(-math.pi / 2.0, qubit)


def _native_cnot(circuit, control: int, target: int) -> None:
    _native_h(circuit, target)
    circuit.cz(control, target)
    _native_h(circuit, target)


def _native_cnot_inverse(circuit, control: int, target: int) -> None:
    _native_h_inverse(circuit, target)
    circuit.cz(control, target)
    _native_h_inverse(circuit, target)


def _pauli_rotation(circuit, word: str, angle: float) -> None:
    """与冻结交付电路一致地编译 ``exp(-i angle P/2)``。"""

    support = [qubit for qubit, symbol in enumerate(word) if symbol != "I"]
    if not support:
        raise ValueError("Identity 不能作为参数化算符。")
    if len(support) == 2 and support == [0, 2]:
        raise ValueError("线性连接编译器不允许直接 q0-q2 Pauli rotation。")
    for qubit in support:
        symbol = word[qubit]
        if symbol == "X":
            _native_h(circuit, qubit)
        elif symbol == "Y":
            _native_rx(circuit, math.pi / 2.0, qubit)
        elif symbol != "Z":
            raise ValueError(f"不支持的 Pauli 字符: {symbol}")
    links = list(zip(support[:-1], support[1:]))
    for first, second in links:
        _native_cnot(circuit, first, second)
    circuit.rz(angle, support[-1])
    for first, second in reversed(links):
        _native_cnot_inverse(circuit, first, second)
    for qubit in reversed(support):
        symbol = word[qubit]
        if symbol == "X":
            _native_h_inverse(circuit, qubit)
        elif symbol == "Y":
            _native_rx_inverse(circuit, math.pi / 2.0, qubit)


__all__ = ["F2_OPERATOR_SEQUENCE", "build_bound_f2_circuit_pair"]
