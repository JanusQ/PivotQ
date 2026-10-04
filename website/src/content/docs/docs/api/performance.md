---
title: 性能模型与预测
description: 独立 Workload 模型、CPU/QPU 硬件配置、预测器与预测结果接口。
---

```python
from pivotq.performance import (
    Workload, Hardware, CPUProfile, QPUProfile, LinkProfile,
    Predictor, PredictionResult,
)
```

性能模型由用户独立编写，不自动分析 Python 程序，也不要求正在运行的 Ray 集群或 QPU。建模方法见[硬件性能模型](../../hardware-profiles/)，运行示例见[性能预测](../../performance/)。

## Workload

```python
workload = Workload(name="workload")
```

以下方法返回节点名称，用于 `depends_on` 依赖列表。名称在模型内唯一；`job_id` 标记不同作业；`target` 可指定 `cpu0`、`qpu1` 等实例，省略时由预测调度器选择。

### cpu

```python
workload.cpu(name, *, duration_seconds=None, ops=None,
             input_bytes=0, output_bytes=0, depends_on=(),
             target=None, job_id="job0") -> str
```

提供正的显式耗时，或提供操作量与访存字节数模型。`duration_seconds` 与 `ops` 不能同时指定。输入输出大小不自动生成通信节点。

### qpu

```python
workload.qpu(name, *, qubits, shots, circuit_count=1,
             input_bytes=0, output_bytes=0, depends_on=(),
             target=None, job_id="job0") -> str
```

根据电路数、shots、有效 shot 吞吐与提交延迟预测量子阶段。`qubits`、`shots`、`circuit_count` 均为正整数。

### transfer

```python
workload.transfer(name, *, source, target, bytes,
                  depends_on=(), job_id="job0") -> str
```

显式声明设备实例间的数据传输，需要硬件中相应的链路。`bytes` 为正整数，`source` 与 `target` 必须不同。未声明通信节点时不自动添加传输耗时。

`workload.nodes` 返回节点副本；`to_dict()` 与 `Workload.from_dict(value)` 用于保存和恢复模型。`preview/predict` 校验完整图的依赖、无环性及设备绑定。

## Hardware

```python
Hardware(cpu=CPUProfile(), qpu=None, links=())
```

同一 CPU 或 QPU 资源池使用相同规格，不同型号通过独立方案比较。`device_ids` 返回实例标识；`to_dict()` 与 `Hardware.from_dict(value)` 支持配置保存和恢复。

### CPUProfile

```python
CPUProfile(count=1, cores_per_node=1,
           peak_flops_tflops_per_node=None,
           memory_bandwidth_gbps_per_node=None,
           source="Caller supplied; no measured calibration asserted",
           calibrated=False)
```

`count` 为节点数，`cores_per_node` 为每节点核心数；计算速率单位为每节点 TFLOP/s，内存带宽为 Gb/s（十亿比特/秒）。操作量或访存模型需要对应速率参数；显式耗时模型可省略。

### QPUProfile

```python
QPUProfile(qubits, shot_rate, count=1, submit_latency_seconds=0.0,
           source="Caller supplied; no measured calibration asserted",
           calibrated=False)
```

`qubits` 为容量，`shot_rate` 为有效 shots/秒，`count` 为同规格实例数。`source` 与 `calibrated` 记录 CPU/QPU 参数来源，不会自动进行硬件标定。

### LinkProfile

```python
LinkProfile(source, target, bandwidth_gbps, latency_seconds=0.0)
```

描述从 `source` 到 `target` 的有向链路，带宽单位为 Gb/s。存在显式通信节点时，链路配置须覆盖所需路径并连接所有硬件实例。

## Predictor

```python
Predictor(*, library=None, native_runtime=None, timeout=180)
```

默认使用包内原生引擎，`library` 可覆盖其路径，`native_runtime` 指定兼容运行环境。构造不加载原生库，也不自动下载系统运行库。

| 方法 | 返回与行为 |
| --- | --- |
| `availability()` | 返回可用性、失败原因及可用时的引擎信息；探测最多 10 秒 |
| `preview(workload, hardware)` | 只做 Python 校验，返回 `scenario`、`scenario_yaml`、`task_graph`、`model`、摘要和模型说明的字典；不运行引擎 |
| `predict(workload, hardware, *, output_dir=None)` | 在隔离子进程中预测，返回 `PredictionResult`；默认超时 180 秒 |
| `compare(models, *, output_dir=None)` | 接收“方案名 → `(workload, hardware)`”映射，返回同名预测结果字典 |

指定 `output_dir` 时，该目录必须不存在或为空，输入、日志与原生结果会保留；省略时使用临时目录并在解析后清理。失败、超时或完成率不足时抛出结构化异常。

## PredictionResult

| 属性 | 含义 |
| --- | --- |
| `latency_seconds` / `simulated_time_seconds` | 全部作业完成的预计时间 |
| `mean_job_latency_seconds` / `jobs` | 平均作业时延与逐作业结果 |
| `throughput_jobs_per_hour` | 每小时作业吞吐，未提供时为 `None` |
| `phase_seconds` / `communication` / `main_bottleneck` | 阶段累计耗时、通信结果与主要瓶颈 |
| `parameter_sources` / `hardware` | 参数来源与输入硬件配置 |
| `validation_scope` / `scope_notes` | 验证及建模说明 |
| `engine_version` / `simulator_sha256` / `model_sha256` | 引擎版本、原生库摘要与模型摘要 |
| `simulator_wall_seconds` | 模拟器自身运行耗时，与目标程序预计耗时不同 |
| `output_dir` | 保留结果的目录；使用临时目录时为 `None` |

`to_dict()` 返回可保存的结果字典。并行阶段的累计时间不可直接相加作为总时延。预测不包含外部平台排队、量子噪声或科学精度，`scientific_quality_predicted` 为 `False`。
