---
title: 状态与执行报告
description: 等待任务、查看逻辑资源，并导出不含计算输入输出的实测记录。
---

## 等待与状态

```python
ready, pending = runtime.wait(refs, num_returns=1, timeout=10)
for ref in ready:
    print(runtime.status(ref))
    result = runtime.get(ref)
```

`wait()` 返回已结束任务和尚未结束任务的引用；已结束的任务可能成功，也可能失败。超时返回仍未完成的引用，不取消任务。`status()` 返回 `pending`、`succeeded`、`failed`、`cancelled` 或 `timed_out`；`pending` 同时覆盖排队和正在运行。

## 记录与导出

```python
import pivotq as pq

with pq.Runtime(trace=True, trace_max_records=10000) as runtime:
    ref = runtime.submit(sum, [1, 2, 3])
    print(runtime.get(ref))
    runtime.release(ref)

report = runtime.report()
report.export("execution.json")
report.export("execution.jsonl")
```

`report()` 生成快照，结果释放和 Runtime 关闭后仍可读取。默认 `trace=False`；需要每次调用的记录时显式开启。超过记录上限后，`dropped_records` 标明未保留的数量，报告不保证包含全部历史。

记录包含调用标识、执行状态、逻辑 CPU 请求、时间、依赖、后端名称及工作流节点标签；不会导出业务参数和返回值。组件 metadata 是用户可见的报告标签，不能放凭据。

JSONL 第一行是报告元信息，之后每行是一条调用记录。导出目标的父目录须已存在。

## 解释耗时

执行耗时来自实际执行记录。`observation_delay_seconds` 包含 Driver 观察到结果前的延迟，不能当作精确网络传输时间。工作流节点可能并行，因此各节点的耗时之和不一定等于整段程序的耗时。

[性能预测](../performance/)给出基于目标硬件模型的耗时估计；执行报告记录本次在实际后端上的运行情况。两者应保留各自的来源、后端与参数，不能用 CPU 量子模拟耗时冒充真实 QPU 耗时。

## 查看资源

`runtime.resources()` 返回执行器可见的逻辑 CPU 总容量和已配置量子后端的能力。其中的 CPU 总容量不代表当前空闲容量；该接口也不会探测量子设备的健康状态。量子后端本身的 `describe()` 同样仅返回静态能力说明。
