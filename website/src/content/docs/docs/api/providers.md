---
title: Provider 协议
description: 第三方量子后端的能力声明、请求、结果与生命周期协议。
---

```python
from pivotq.providers import (
    BackendCapabilities, QuantumRequest, ProviderResult, QuantumProvider,
)
```

Provider 将设备编译、连接和结果读取封装为同步接口，供 PivotQ 调度。完整适配示例见[扩展量子后端](../../providers/)。

## register_quantum_backend

```python
runtime.register_quantum_backend(
    name, factory, *, capabilities, execution=None, num_cpus=None,
) -> None
```

注册仅在当前 Runtime 生效。`name` 为未使用的后端名；`factory(**config)` 返回实现协议的 Provider，`config` 来自 `runtime.quantum_backend(name, **config)`。注册和创建后端不构造客户端。

模拟后端默认采用 Task、请求 1 CPU，可显式选择 Task 或 Actor，并用 `num_cpus` 配置正的 CPU 请求。真实 QPU 固定使用独立串行 Actor、请求 0 CPU。

## BackendCapabilities

```python
BackendCapabilities(max_qubits, is_simulated, min_qubits=1, supports_seed=False)
```

| 字段 | 含义 |
| --- | --- |
| `min_qubits` / `max_qubits` | 支持的电路比特范围，均为正整数且下限不大于上限 |
| `is_simulated` | 是否为模拟 Provider |
| `supports_seed` | 是否支持采样种子；真实设备必须为 `False` |

该声明用于提交前校验，不构成设备在线状态。当前协议接收已绑定的幺正电路及末尾测量，SDK 统一处理测量映射。

## QuantumRequest

| 字段 | 含义 |
| --- | --- |
| `circuit` | 独立的 Qiskit 电路副本，已绑定参数并去掉末尾测量 |
| `shots` | 请求的重复次数 |
| `seed` | 模拟采样种子；未指定时为 `None` |
| `request_id` | 本次调用的稳定标识，建议关联远端作业记录 |

由 SDK 创建并传入 `run`。Provider 执行电路后，返回全部逻辑量子位的 Z 测量分布；设备编译导致的布局置换需由 Provider 还原。

## ProviderResult

```python
ProviderResult(shots, source, probabilities=None, counts=None, metadata={})
```

`shots` 为后端确认的重复次数，`source` 标识数据来源。`probabilities` 与 `counts` 至少提供一项；若两者同时提供，概率须等于计数频率。只提供概率的设备无需伪造计数。

分布键使用全部逻辑量子位的 `q[n-1]...q0` 顺序，不含寄存器分隔符。SDK 校验位宽、归一化及计数，再转换为用户请求的测量分布。

`metadata` 为可序列化字典，每个实例默认独立空字典。可记录 `backend_job_id`、`device_id`，便于核实异常请求；不包含凭据。

## QuantumProvider

```python
provider.run(request: QuantumRequest) -> ProviderResult
provider.close() -> None
```

工厂与方法均为同步调用。`close` 清理客户端资源，必须允许重复调用。已知失败使用 `pivotq.errors` 的结构化异常；设备可能已接受任务后发生的不确定失败，应抛出 `ResultUnknownError` 并保留设备作业标识。

SDK 不自动重试或替换后端。Provider 在执行进程中构造，用户类与所需依赖必须在 Ray Worker 环境中可用。
