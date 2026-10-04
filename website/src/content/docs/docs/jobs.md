---
title: 集群作业
description: 通过 Ray Jobs 提交完整 Python 程序，查看状态、日志和停止作业。
---

`Runtime` 组织一个程序内部的任务；`JobClient` 把完整 Python 程序提交给已部署的 Ray Jobs 服务。服务地址通常是 Dashboard 的 HTTP 地址，与 Runtime 连接的 Ray 集群地址用途不同。

## 提交程序

下面示例假定 `my-program/` 包含自己的 `main.py`，且集群节点已安装相同版本的 PivotQ 与应用依赖：

```python
from pivotq.jobs import JobClient, JobSpec

client = JobClient("http://127.0.0.1:8265")
spec = JobSpec(
    entrypoint=["python", "main.py"],
    working_dir="./my-program",
    num_cpus=0,
    metadata={"application": "hybrid-example"},
)
job = client.submit(spec)
print(job.submission_id)
print(client.status(job))
print(client.logs(job))
```

创建 `JobClient` 不联网，也不启动 Ray；首次操作时才建立客户端。`entrypoint` 是参数列表，SDK 负责正确引用参数，不需要拼接 shell 字符串。默认自动生成 `submission_id`，也可以显式指定。

## 部署环境

`working_dir` 支持本地目录或 Ray 支持的远程归档。`pip_packages` 与 `env_vars` 用于作业环境；它们不会替代用户的依赖部署检查。当前不假定 PivotQ 已发布 PyPI，需在集群镜像中预装同版 wheel，或提供集群可访问的 wheel 来源。

`JobSpec.num_cpus` 只预留 Driver 进程的 CPU 资源，默认 0。程序内的 Task、Actor 仍按各自声明申请资源；它不是整个作业的 CPU 总额度。

作业的 `main.py` 使用 `address="auto"` 连接当前作业所在的集群：

```python
from pivotq import Runtime

with Runtime(executor="ray", address="auto") as runtime:
    result = runtime.submit(sum, [1, 2, 3])
    print(runtime.get(result))
```

未初始化 Ray 时，`Runtime(executor="ray")` 默认创建本机 Ray 实例；提交到现有集群的程序应显式使用 `"auto"` 或部署方提供的地址。

## 查询与管理

| 调用 | 作用 |
| --- | --- |
| `client.status(job)` | 返回 pending、running、stopped、succeeded 或 failed |
| `client.logs(job)` | 获取当前日志 |
| `client.stop(job)` | 请求停止作业进程 |
| `client.delete(job)` | 删除已结束作业的记录 |

这些调用也接受 `submission_id` 字符串。停止软件作业不证明其已提交的物理 QPU 任务已取消。

提交故障抛出 `JobSubmissionError`，其中 `framework_job_id` 保留提交标识。若结果是未知状态，先按该标识查询，SDK 不会自动重复提交。

现有应用 Driver 的兼容启动入口仍为 `python -m pivotq.jobs.driver`；普通用户程序直接使用自己的入口文件。集群作业 API 不会将任意程序自动接入网页工作台。
