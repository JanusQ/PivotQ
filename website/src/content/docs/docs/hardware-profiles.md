---
title: 硬件性能模型
description: 为 CPU、QPU 和通信链路提供明确参数及来源，用于独立性能预测。
---

`pivotq.performance.Hardware` 描述要预测的目标硬件。它不注册物理设备、不预留 Ray 资源，也不改变程序的实际执行后端。

## CPU 与 QPU

```python
from pivotq.performance import CPUProfile, QPUProfile, Hardware

hardware = Hardware(
    cpu=CPUProfile(count=1, cores_per_node=4),
    qpu=QPUProfile(
        qubits=8,
        shot_rate=10000,
        submit_latency_seconds=0.001,
        source="示例假设参数，尚未经真机校准",
        calibrated=False,
    ),
)
```

| 模型 | 参数与单位 |
| --- | --- |
| `CPUProfile` | 节点数 count、每节点核数 cores_per_node；可选每节点 TFLOP/s、每节点内存带宽 Gb/s |
| `QPUProfile` | 每台设备比特数 qubits、每秒有效 shots 数 shot_rate、设备数 count、每批提交延迟（秒） |
| `source` / `calibrated` | 记录来源与是否经过校准；SDK 不自行证明参数已被测量 |

CPU 节点池和 QPU 池各自使用同一种规格。设备标识为 `cpu0`、`cpu1`、`qpu0` 等，可在工作量节点中用 `target` 指定实例。没有 QPU 时省略 `qpu`。

CPU 任务若提供已知的 `duration_seconds`，无需填写计算速率，且不能同时传入 `ops`。按运算量或内存量建模时，需要提供对应速率。正的耗时、提交延迟和链路延迟向上取整到整数微秒。QPU 的 shot_rate 合并采集、测量和复位阶段，不等于量子门时钟频率。

`memory_bandwidth_gbps_per_node` 的 Gb/s 是十亿**比特**每秒；例如 1 GB 数据量在 1 Gb/s 下的理想传输项为 8 秒。按运算量/内存量计算的 CPU 模型还包含当前引擎固有的 20 微秒开销；显式 duration 使用用户给定的时间。

## 通信链路

`LinkProfile(source, target, bandwidth_gbps, latency_seconds=0)` 是有方向的链路，带宽单位为十亿比特/秒。需要双向通信时分别声明两个方向。

```python
from dataclasses import replace
from pivotq.performance import LinkProfile

hardware = replace(hardware, links=(
    LinkProfile("cpu0", "qpu0", bandwidth_gbps=1, latency_seconds=0.001),
    LinkProfile("qpu0", "cpu0", bandwidth_gbps=1, latency_seconds=0.001),
))
```

用 `workload.transfer(...)` 显式描述传输字节数和依赖。仅声明两个节点之间有数据依赖，不会自动估算网络流量。未配置传输时，模型生成的内部结构连接不代表真实网络能力。

## 保存与比较

`hardware.to_dict()` 和 `Hardware.from_dict(...)` 用于保存、恢复参数。`Predictor.compare()` 比较用户提供的工作量与硬件组合，返回每种配置独立的预测。更快的预测不证明两个应用具有相同的科学精度，详见[性能预测](../performance/)。
