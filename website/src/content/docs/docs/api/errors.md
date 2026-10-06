---
title: 异常类型
description: 结构化执行错误、作业与工作流提交异常，以及请求状态核实约定。
---

```python
from pivotq.errors import (
    PivotQError, ValidationError, UnavailableError, ExecutionError,
    SubmissionError, TimeoutError, CancellationError, ResultUnknownError,
    ErrorCategory, RetryAdvice, SubmissionDisposition,
)
```

## PivotQError

任务执行失败时，`runtime.get(ref)` 会抛出相应异常。结构化异常包含 `code`、`category`、`retry_advice`，以及可选的 `device_id`、`framework_job_id`、`backend_job_id`、`backend_code`。

`error.to_record(include_message=False)` 返回适合记录或导出的字典；默认省略自由文本消息，必要时可显式包含。

## 执行错误

| 类型 | 含义 |
| --- | --- |
| `ValidationError` | 非法请求、引用或不支持的电路 |
| `UnavailableError` | Runtime 已关闭，或后端在接受任务前不可用 |
| `SubmissionError` | 提交失败，通过 `disposition` 区分已知提交状态 |
| `ExecutionError` | 任务执行失败 |
| `TimeoutError` | 执行或外部操作超时 |
| `CancellationError` | 取消相关操作失败 |
| `ResultUnknownError` | 设备可能已经执行，当前无法确认结果 |

普通 Python 参数类型与范围校验也可能直接抛出 `TypeError` 或 `ValueError`。不能跨 Runtime 使用引用，不能使用已释放的引用，也不能在 Runtime 关闭后提交新任务；生命周期见[运行时接口](../runtime/)。

## 提交状态与重试建议

`SubmissionDisposition` 包含 `NOT_SUBMITTED="not_submitted"`、`ACCEPTED="accepted"`、`UNKNOWN="unknown"`。

`RetryAdvice` 包含 `NEVER="never"`、`SAFE="safe"`、`RECONCILE_FIRST="reconcile_first"`。这些值供调用者决定处理策略，不触发自动重试。

如果发生故障时量子设备可能已经接受请求，需要先用请求和作业标识核实状态。SDK 不自动重提，不切换模拟器，结构化错误及原标识沿下游依赖传播。

## WorkflowSubmissionError

```python
from pivotq import WorkflowSubmissionError
```

工作流提交中途失败时，`error.partial_run` 为包含已接受引用的 `WorkflowRun`。据此等待或清理已提交节点，避免将整张图重复提交。

## 作业管理错误

```python
from pivotq.jobs import JobSubmissionError, JobServiceError, JobStateError
```

`JobSubmissionError` 保留 `framework_job_id` 与已知的提交状态。`JobServiceError` 表示 Jobs 服务调用失败，`JobStateError` 表示作业状态不允许当前操作。管理操作约定见[集群作业](../jobs/)。
