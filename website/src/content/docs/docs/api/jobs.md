---
title: 集群作业
description: Ray Jobs 作业规格、提交、状态、日志、停止和删除接口。
---

```python
from pivotq.jobs import JobClient, JobSpec, JobHandle, JobStatus
```

通过作业管理接口提交整个 Python 程序，再由程序内部的 Runtime 调度各项任务。操作教程见[集群作业](../../jobs/)。

## JobSpec

```python
JobSpec(entrypoint, submission_id=<自动生成>, working_dir=None,
        pip_packages=(), env_vars=(), num_cpus=0, metadata=())
```

| 参数 | 约定 |
| --- | --- |
| `entrypoint` | 命令参数序列，例如 `["python", "main.py"]`，由 SDK 进行命令引用处理 |
| `submission_id` | 提交标识，省略时自动生成 |
| `working_dir` | 本地目录或 Ray 支持的远程归档地址 |
| `pip_packages` | Worker 运行环境需要的依赖序列 |
| `env_vars` / `metadata` | 字符串字典或键值对序列 |
| `num_cpus` | Driver 的 CPU 资源配额，默认为 0；Worker 配额由任务声明 |

Driver 和 Worker 需要安装相同版本的 `pivotq`。保留作业入口 `python -m pivotq.jobs.driver`。

## JobClient

```python
JobClient(address, *, headers=None, cookies=None, verify=True)
```

`address` 为 Ray Jobs HTTP 服务地址；可通过 `headers`、`cookies` 传递认证配置，`verify` 配置 TLS 验证。构造客户端不联网、不启动集群。

## submit

```python
client.submit(spec) -> JobHandle
```

提交一次作业，返回 `JobHandle`，其 `submission_id` 为查询标识。提交失败时 `JobSubmissionError.framework_job_id` 保留原标识，用于核实是否已经接受请求；SDK 不自动重提。

## status

```python
client.status(job) -> JobStatus
```

`job` 可为 `JobHandle` 或提交标识字符串；以下管理接口同样支持这两种形式。

## logs

```python
client.logs(job) -> str
```

返回当前可用的作业日志文本。

## stop

```python
client.stop(job) -> bool
```

请求停止作业进程。停止作业不代表远端 QPU 请求已经确认取消。

## delete

```python
client.delete(job) -> bool
```

删除已进入终态的作业记录；运行中作业应先停止并确认状态。

## JobStatus

取值为 `PENDING="pending"`、`RUNNING="running"`、`STOPPED="stopped"`、`SUCCEEDED="succeeded"`、`FAILED="failed"`。`is_terminal` 对 `STOPPED/SUCCEEDED/FAILED` 返回 `True`。

作业错误类型 `JobSubmissionError`、`JobServiceError`、`JobStateError` 由 `pivotq.jobs` 导出，见[异常类型](../errors/)。
