---
title: 量子后端与结果
description: 电路与参数入口、QuantumBackend 的创建与提交，以及 QuantumResult 结果约定。
---

```python
from pivotq import QuantumBackend, QuantumResult
```

量子后端将电路执行接入 Runtime 的依赖调度。未连接 QPU 时可选 CPU 模拟后端；设备接入使用统一的 [Provider 协议](../providers/)。操作教程见[量子后端](../../quantum-backends/)。

## 电路构造与参数

```python
from pivotq import QuantumCircuit, Parameter
from pivotq.circuit import (
    QuantumRegister, ClassicalRegister,
    ParameterExpression, ParameterVector,
    transpile, qasm3, qpy,
)

theta = Parameter("theta")
circuit = QuantumCircuit(1)
circuit.ry(theta, 0)
bound = circuit.assign_parameters({theta: 0.7})
```

`pivotq.circuit` 提供以下公开入口；`QuantumCircuit` 和 `Parameter` 也可以从此模块导入。

| 入口 | 用途 |
| --- | --- |
| `QuantumCircuit`、`QuantumRegister`、`ClassicalRegister` | 构造电路与量子、经典寄存器 |
| `Parameter`、`ParameterExpression`、`ParameterVector` | 符号参数、参数表达式与参数向量 |
| `transpile` | 电路编译；参数与返回值遵循 Qiskit |
| `qasm3` | Qiskit OpenQASM 3 模块，例如 `qasm3.dumps(circuit)` |
| `qpy` | Qiskit QPY 模块，例如 `qpy.dump(circuit, file)` 与 `qpy.load(file)` |

这些入口直接导出 Qiskit 原始对象，保留原有类型身份、调用签名、方法和返回值，不创建电路子类或修改模拟行为。原生 Qiskit 电路与通过 PivotQ 构造的电路可以混用，参数绑定、编译和序列化继续遵循 Qiskit 的规则及可选依赖要求。量子信息工具等未列出的接口仍可从 Qiskit 导入。

顶层采用按需加载：普通 `import pivotq` 不加载 Qiskit、不初始化 Ray 或设备；导入电路入口时才加载相应对象。构造电路与执行电路是不同操作，实际执行位置由 `runtime.quantum_backend(...)` 选择的后端决定。

## quantum_backend

```python
runtime.quantum_backend(name, **config) -> QuantumBackend
```

`name` 使用 `"simulator"` 或当前 Runtime 注册的后端名称。`config` 传给对应的 Provider 工厂，必须可序列化，并符合 Provider 构造函数的参数要求。创建后端不会构造 Provider 或连接设备，首次执行请求时才构造。

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

`circuit_or_ref` 为 `QuantumCircuit` 或返回该电路的结果引用；通过 PivotQ 或 Qiskit 构造的电路均可使用。`shots` 为正整数。`seed` 仅适用于声明支持种子的模拟后端，真实 QPU 不接受种子。用 `runtime.get(ref)` 获取 `QuantumResult`。

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

模拟器返回采样计数和频率；有限次采样得到的频率不保证等于理想概率。`counts=None` 表示设备未提供计数，不代表零计数。量子任务失败不会自动切换模拟器；执行状态未知时保留原请求信息，见[异常与错误处理](../errors/)。
