---
title: 编写混合程序
description: 用普通 Python 控制流程组织经典任务与量子任务。
---

## 一个程序，两类调用

经典计算使用 `runtime.submit()`，量子电路使用 `backend.submit()`。两者都返回结果引用；使用同一个 `runtime.get()` 即可取回对应结果，也可以将这些引用继续传给下游任务。

下面使用本机 Ray 调度这两类任务。量子后端默认选择 `simulator`，在未连接 QPU 时用 CPU 模拟电路；接入 QPU 后可替换后端对象，继续沿用相同的任务依赖和控制流程。

```python
from pivotq import QuantumCircuit, Runtime


def build_circuit(angle):
    circuit = QuantumCircuit(1)
    circuit.ry(angle, 0)
    circuit.measure_all()
    return circuit


def expectation(result):
    return result.probabilities.get("0", 0.0) - result.probabilities.get("1", 0.0)


with Runtime(executor="ray", address="local") as runtime:
    backend = runtime.quantum_backend("simulator")
    circuit_ref = runtime.submit(build_circuit, 0.7)
    quantum_ref = backend.submit(circuit_ref, shots=4096, seed=7)
    value_ref = runtime.submit(expectation, quantum_ref)
    print(runtime.get(value_ref))
```

## 循环与参数更新

驱动程序可以读取结果，根据结果确定下一轮参数，再次提交任务。这适用于变分算法、参数扫描和量子特征计算。

```python
with Runtime(executor="ray", address="local") as runtime:
    backend = runtime.quantum_backend("simulator")
    for angle in [0.0, 0.5, 1.0]:
        circuit_ref = runtime.submit(build_circuit, angle)
        quantum_ref = backend.submit(circuit_ref, shots=4096, seed=7)
        value_ref = runtime.submit(expectation, quantum_ref)
        value = runtime.get(value_ref)
        print(angle, value)
        runtime.release(circuit_ref, quantum_ref, value_ref)
```

每次 `get()` 都是显式等待点。参数扫描可先提交互不依赖的任务，再读取结果；依赖上次量子结果的参数更新则需要等待。

## 指定硬件

本页公开 SDK 教程中的经典任务在 CPU 上执行；GPU 计算通过仓库内的应用桥接和 Ray 组件接入，见 [GPU 与异构资源](../gpu-computing/)。量子调用通过后端对象显式选择模拟器或已注册的 QPU Provider；使用 `backend.describe()` 查询声明的比特范围等能力，并按适配器支持的电路范围准备输入。接入方式见[量子后端](../quantum-backends/#接入-qpu-后端)。算法中的数学操作不会因资源声明而自动转成量子电路。

## 选择应用输出

SDK 返回 Python 值与 `QuantumResult`。应用可以把能量、概率、优化轨迹写为 CSV、JSON 或自己的格式，再开发相应视图。可视化工作台提供水分子动力学模拟与受控量子电路教程，尚不会自动展示任意自定义程序的结果。
