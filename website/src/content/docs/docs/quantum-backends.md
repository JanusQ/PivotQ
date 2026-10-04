---
title: 量子后端
description: 选择 CPU 模拟器或已注册的 QPU Provider，并正确理解采样、测量位序与结果来源。
---

## 选择后端

执行器决定任务如何调度，量子后端决定电路如何执行。下面通过本机 Ray Worker 调用 `simulator`，在 CPU 上模拟电路；接入 QPU 后，Worker 通过对应的 Provider 提交设备请求。

```python
from pivotq import Runtime
from qiskit import QuantumCircuit

circuit = QuantumCircuit(2)
circuit.h(0)
circuit.cx(0, 1)
circuit.measure_all()

with Runtime(executor="ray", address="local") as runtime:
    backend = runtime.quantum_backend("simulator", max_qubits=20)
    ref = backend.submit(circuit, shots=1024, seed=7)
    result = runtime.get(ref)
    print(result.counts)
    print(result.is_simulated)
```

| 后端 | 实际执行 | 宽度 | counts | seed |
| --- | --- | --- | --- | --- |
| `simulator` | CPU 状态向量与有限采样 | 默认上限 20 比特，可显式配置 | 提供采样计数 | 支持 |
| 已注册的 QPU Provider | 由适配器连接相应的量子设备 | 由 `BackendCapabilities` 声明 | 提供原始计数时返回，否则为 `None` | 不支持 |

状态向量内存随比特数指数增长；增加 `max_qubits` 不会增加可用内存。模拟器采样为理想结果，不包含设备噪声。

## 支持的电路

提交已绑定参数的 Qiskit `QuantumCircuit`，或一个最终返回此对象的任务引用。标准幺正门与可分解的幺正电路可被模拟；支持末尾的全量、部分及置换测量。

当前不支持中途测量、reset、initialize、经典条件、控制流和未绑定参数。使用 `assign_parameters()` 绑定参数，再提交电路。执行不会修改输入电路；提交后直到任务完成，请勿修改同一个电路对象。

实际 QPU 支持的门集、连接关系和编译方式由设备及其 Provider 决定。通过公共电路校验不代表任意设备都可以执行该电路；Provider 还需完成设备适配与检查。

## 测量与位序

有显式测量时，返回位串按 `c[n−1]…c0` 排列，多个经典寄存器展平且不插入空格。未被写入的经典位为 0；部分测量只返回所对应的经典位分布。

没有显式测量时，默认测量全部量子比特，位串按 `q[n−1]…q0` 排列。例：两比特电路只有 `x(0)`，不含测量时结果为 `"01"`。

测量置换保持原语义：若 `q0=1, q1=0`，同时 `measure(0, 1)`、`measure(1, 0)`，返回 `"10"`。SDK 不会把这种映射静默改成按 qubit 编号输出。

## 接入 QPU 后端

使用部署方提供的 Provider，或在用户代码中实现[Provider 协议](../providers/)。注册时声明设备能力，创建后端时传入该 Provider 要求的配置：

```python
def register_qpu(runtime, provider_factory, capabilities, **config):
    runtime.register_quantum_backend(
        "qpu", provider_factory, capabilities=capabilities,
    )
    return runtime.quantum_backend("qpu", **config)
```

这里的 `provider_factory`、`capabilities` 和配置来自实际适配器；SDK 不会仅凭设备名称自动完成接入。`BackendCapabilities` 声明最小/最大比特数、是否模拟和是否支持采样种子；`backend.describe()` 返回这些静态信息。

注册与创建后端不构造 Provider，也不连接量子设备。提交后，运行时在执行进程中构造实例并调用 `run()`；电路也可以来自上游 CPU 任务引用。读取结果统一使用 `runtime.get(backend.submit(circuit, shots=1024))`。

Provider 负责原生门编译、物理布局还原及结果读取；SDK 负责保留末尾测量映射并生成统一的 `QuantumResult`。不同测量基需要用户先在电路中加入相应基变换。

## 结果来源与失败

`simulator` 返回采样计数和计数归一化概率。QPU Provider 可以返回设备确认的原始计数或概率；仅提供概率时 `counts=None`，SDK 不会根据概率伪造原始计数。`shots` 记录采样次数或设备确认的重复次数，`metadata.source` 记录 Provider 提供的数据来源。

设备连接、提交或执行失败时会抛出错误，不会自动改用 CPU 模拟。若报错表示任务状态未知，SDK 不会自动重试；任务可能仍在设备执行，需保留作业标识并核实状态后再决定下一步。
