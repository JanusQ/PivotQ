#!/usr/bin/env python3
"""用 PivotQ 构造电路，以 Qiskit 理想态矢量重现页面中的四位置查询。

四个存储位是教学假设；此脚本不提交 PivotQ 任务，也不访问真实 QRAM。
"""

from __future__ import annotations

from pivotq import QuantumCircuit
from qiskit.quantum_info import Statevector


# Qiskit 的三位基态标签按 q2 q1 q0 排列；前两位是地址，末位是数据。
MEMORY = {"00": 1, "01": 0, "10": 1, "11": 1}


def append_query(circuit: QuantumCircuit) -> None:
    """在三量子位电路上追加 |a>|b> -> |a>|b XOR MEMORY[a]> 查询。

    q2、q1 是地址位，q0 是数据位。存储位为 1 时，用受控 X 翻转 q0；
    对地址中的 0 临时加 X，查询后撤销，保留地址和分支间的相位关系。
    """
    for address, stored_bit in MEMORY.items():
        if stored_bit == 0:
            continue
        zero_controls = [wire for bit, wire in zip(address, (2, 1)) if bit == "0"]
        for wire in zero_controls:
            circuit.x(wire)
        circuit.ccx(2, 1, 0)
        for wire in reversed(zero_controls):
            circuit.x(wire)


def fixed_case() -> QuantumCircuit:
    """准备 |10>|0>，追加查询后返回电路。"""
    circuit = QuantumCircuit(3)
    circuit.x(2)
    append_query(circuit)
    return circuit


def superposition_case() -> QuantumCircuit:
    """准备 (|01> + |10>)|0>/sqrt(2)，再追加同一查询。"""
    circuit = QuantumCircuit(3)
    circuit.x(1)
    circuit.h(2)
    circuit.cx(2, 1)
    append_query(circuit)
    return circuit


def show_components(circuit: QuantumCircuit) -> None:
    """打印非零基态振幅及其理想测量概率。"""
    state = Statevector.from_instruction(circuit)
    for basis, amplitude in enumerate(state.data):
        if abs(amplitude) < 1e-10:
            continue
        if abs(amplitude.imag) > 1e-10:
            raise ValueError("本教程中的计算预期只有实数振幅")
        label = f"{basis:03b}"
        print(
            f"|{label[:2]}⟩|{label[2]}⟩  "
            f"振幅 {amplitude.real:+.6f}  概率 {abs(amplitude) ** 2:.0%}"
        )


if __name__ == "__main__":
    print("固定地址 |10⟩|0⟩：")
    show_components(fixed_case())
    print("叠加地址 (|01⟩ + |10⟩)|0⟩ / √2：")
    show_components(superposition_case())
