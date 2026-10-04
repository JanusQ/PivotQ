---
title: 执行报告
description: 调用状态枚举、执行追踪快照和 JSON/JSONL 导出接口。
---

```python
from pivotq.observability import InvocationStatus, ExecutionReport
```

通过 `Runtime(executor="ray", trace=True)` 启用有界追踪，`trace_max_records` 控制最多保留的完成记录数。教程见[状态与执行报告](../../observability/)。

## InvocationStatus

| 枚举 | 值 | 含义 |
| --- | --- | --- |
| `PENDING` | `"pending"` | 排队或运行中 |
| `SUCCEEDED` | `"succeeded"` | 成功完成 |
| `FAILED` | `"failed"` | 执行失败 |
| `CANCELLED` | `"cancelled"` | 已取消 |
| `TIMED_OUT` | `"timed_out"` | 执行超时 |

`status.is_terminal` 表示是否进入终态。通过 [`runtime.status`](../runtime/#status) 查询；[`wait`](../runtime/#wait) 将所有终态视为 ready，等待超时本身不把任务变为 `TIMED_OUT`。

## report

```python
runtime.report() -> ExecutionReport
```

读取已保留的完成调用快照，释放结果或关闭 Runtime 后仍可调用。关闭追踪时返回空记录及资源快照。报告不保存业务输入或返回值。

## ExecutionReport

| 属性 | 含义 |
| --- | --- |
| `runtime_id` / `executor` | 运行时标识与执行器名称 |
| `closed` / `trace_enabled` | 生成报告时的关闭状态与追踪配置 |
| `records` | 完成调用记录元组，包含任务、依赖、CPU 配额、后端、耗时与错误 |
| `dropped_records` | 超出保留上限而丢弃的记录数 |
| `resources` | CPU 逻辑总容量与已配置量子后端能力快照 |

记录中的 `observation_delay_seconds` 包括结果完成到 Driver 观测之间的延迟，不是网络传输耗时。

## as_dict

```python
report.as_dict() -> dict
```

返回独立字典，包含报告字段、`schema_version` 和记录覆盖范围说明，适合进一步处理或序列化。

## export

```python
report.export(destination, *, format=None) -> Path
```

`destination` 为文件路径。`format` 可设为 `"json"` 或 `"jsonl"`；省略时，`.jsonl` 后缀使用 JSONL，其他后缀使用 JSON。目标父目录需已存在；同名文件会覆盖。返回输出文件的绝对 `Path`。

JSONL 首行保存报告元数据，后续每行保存一条调用记录。
