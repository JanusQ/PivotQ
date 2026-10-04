---
title: 运行时与结果引用
description: Runtime 的任务提交、结果读取、等待、资源快照和关闭接口。
---

```python
from pivotq import Runtime, ResultRef
```

Ray 执行器负责在 Worker 中运行任务并按依赖调度；量子任务使用的后端由程序另行选择。教程见[经典任务](../../classical-tasks/)与[混合程序](../../hybrid-programs/)。

## Runtime

```python
Runtime(executor="local", *, address=None, max_workers=4,
        trace=False, trace_max_records=10000)
```

| 参数 | 约定 |
| --- | --- |
| `executor` | `"ray"` 使用 Ray；默认 `"local"` 使用本地线程池，适合调试 |
| `address` | Ray 地址；`None` 启动或复用本机连接，`"auto"` 连接已有集群；仅 Ray 模式可指定 |
| `max_workers` | 本地线程池最大工作线程数，默认 4；仅本地模式可调整 |
| `trace` | 是否保留完成调用的执行记录，默认关闭 |
| `trace_max_records` | 启用追踪时最多保留的记录数，默认 10000 |

构造 Runtime 不启动执行器；进入 `with` 或调用需要执行器的接口时启动。推荐使用 `with Runtime(executor="ray") as runtime:` 管理资源。只读属性 `executor`、`max_workers`、`closed` 返回配置及关闭状态。

## submit

```python
runtime.submit(fn, /, *args, num_cpus=1, kwargs=None) -> ResultRef
```

提交同步 Python 函数。业务位置参数放入 `args`，业务关键字参数通过字典 `kwargs` 传递。`num_cpus` 为正的 CPU 资源请求，表达调度配额，不限制函数实际使用的 CPU 时间。

相同函数及 CPU 配置复用组件注册，每次调用产生独立结果引用。函数不应捕获 Runtime 或已打开的设备连接；业务参数和返回值需要可序列化。

## ResultRef

`ResultRef` 由提交接口返回，表示尚未取回的业务值，不由用户直接构造。可直接传给后续任务，也可嵌套在普通 `list`、`tuple` 和 `dict` 的值中。

引用只能交给创建它的 Runtime，不能用作字典键、放入循环容器或隐藏在自定义对象中。需要 Python 条件判断时，先通过 `get` 取得业务值。

## get

```python
runtime.get(ref) -> Any
```

等待单个引用完成并返回业务值；失败时抛出结构化异常。可重复取值，`get` 不释放结果。

## wait

```python
runtime.wait(refs, *, num_returns=1, timeout=None) -> (ready, pending)
```

等待至少 `num_returns` 个调用完成；`ready` 与 `pending` 均为引用元组。失败结果也算 ready。`timeout` 单位为秒，`None` 表示持续等待，`0` 表示立即查询。超时可以返回不足目标数量的 ready，不取消任务，也不取回业务值。

## status

```python
runtime.status(ref) -> InvocationStatus
```

返回 `pending/succeeded/failed/cancelled/timed_out`；`pending` 包括排队与运行。枚举约定见[状态与执行报告](../observability/#invocationstatus)。

## resources

```python
runtime.resources() -> dict
```

返回 `executor`、`capacity_kind`、CPU 节点列表 `nodes` 和已配置的 `quantum_backends`。这是逻辑总容量快照，不是当前空闲容量或设备健康探测；关闭后返回最后保存的快照。

## release

```python
runtime.release(*refs) -> None
```

在完成最后一次使用后释放已完成结果。它不会隐式调用 `get`，也不表示取消任务。已释放引用不可继续取值或作为依赖；一轮程序结束时应同时释放中间结果。

## close

```python
runtime.close() -> None
```

清理 Runtime 拥有的组件、引用和连接，允许重复调用。关闭后不能继续提交或读取结果；执行报告仍可通过 [`report`](../observability/#report) 读取。

调用者预先创建的 Ray 连接由调用者管理。SDK 创建并共享的 Ray 连接在最后一个使用者退出时关闭。上下文管理器在正常退出和异常退出时都会清理 Runtime。
