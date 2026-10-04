---
title: 量子后端与结果
description: QuantumBackend 的创建、提交、能力查询和 QuantumResult 结果约定。
---

```python
from pivotq import QuantumBackend, QuantumResult
```

量子后端将电路执行接入 Runtime 的依赖调度。未连接 QPU 时可选 CPU 模拟后端；设备接入使用统一的 [Provider 协议](../providers/)。操作教程见[量子后端](../../quantum-backends/)。

## quantum_backend

```python
runtime.quantum_backend(name, **config) -> QuantumBackend
```

`name` 使用 `"simulator"` 或当前 Runtime 注册的后端名称。`config` 传给对应 Provider 工厂，必须可序列化且符合其构造参数。创建后端不会构造 Provider 或连接设备，首次执行请求时才构造。

内置模拟器配置为 `runtime.quantum_backend("simulator", max_qubits=20)`。它使用 Qiskit Statevector 并进行有限次数采样，默认最多 20 比特，可调整上限。

## describe

```python
backend.describe() -> BackendCapabilities
backend.name -> str
```

`describe` 返回后端声明的静态能力，不探测设备。比特范围、是否模拟及是否支持 seed 的含义见 [`BackendCapabilities`](../providers/#backendcapabilities)。`name` 为创建后端时使用的名称。

## submit

```python
backend.submit(circuit_or_ref, *, shots=1024, seed=None) -> ResultRef
```

`circuit_or_ref` 为 Qiskit `QuantumCircuit` 或返回该电路的结果引用；`shots` 为正整数。`seed` 仅适用于声明支持种子的模拟后端，真实 QPU 不接受种子。用 `runtime.get(ref)` 获取 `QuantumResult`。

电路需绑定全部参数，包含幺正操作及可选的末尾测量；支持部分测量与测量位重排。拒绝中途测量、重复测量映射、`reset`、`initialize` 和动态控制流。SDK 使用副本保存并转换测量映射，不修改输入电路。

## QuantumResult

| 属性 | 含义 |
| --- | --- |
| `probabilities` | 位串到概率的字典；若后端返回计数，为对应采样频率 |
| `counts` | 后端提供的实际计数字典；只有概率时为 `None` |
| `backend` | 实际使用的量子后端名称 |
| `is_simulated` | 是否来自模拟计算 |
| `shots` | 模拟采样次数或设备确认的重复次数 |
| `bit_order` | 本次输出使用的经典位或量子位排列说明 |
| `metadata` | 后端来源、请求及设备作业标识等诊断信息 |

显式测量时，位串按跨寄存器展平后的经典位从高到低排列，未测量的经典位为零；无测量时，默认测量全部量子位，按量子位从高到低排列。此约定遵循 Qiskit。

模拟器返回采样计数和频率，有限次采样不保证等于理想概率。`counts=None` 表示设备未提供计数，不代表零计数。量子任务失败不会自动切换模拟器；执行状态未知时保留原请求信息，见[异常与错误处理](../errors/)。
