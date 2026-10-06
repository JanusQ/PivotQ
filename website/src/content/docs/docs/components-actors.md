---
title: 组件与 Actor
description: 用组件封装业务方法，用 CPU Actor 保留模型和迭代状态。
---

普通函数适合独立计算。需要跨调用保留模型、缓存或优化器状态时，可以把业务类注册为 Actor。用户声明允许调用的方法；实例在执行进程中创建。

## 创建并调用 Actor

```python
import pivotq as pq

class Accumulator:
    def __init__(self, initial=0):
        self.value = initial

    def add(self, amount):
        self.value += amount
        return self.value

with pq.Runtime() as runtime:
    counter = runtime.actor(Accumulator, 10, methods=("add",), name="counter")
    first = counter.submit("add", 2)
    print(runtime.get(first))  # 12
    second = counter.submit("add", 3)
    print(runtime.get(second))  # 15
    runtime.release(first, second)
```

`methods` 明确列出业务方法，`close` 与 `describe` 为保留名称。Actor 默认串行；需要确定状态更新次序时，等待前一次结果或显式传递依赖。提高 `max_concurrency` 后，业务类须自行管理共享状态。

## 显式注册组件

```python
spec = pq.ComponentSpec(
    name="accumulator",
    methods=("add",),
    execution="actor",
    num_cpus=1,
    timeout_seconds=30,
)

with pq.Runtime() as runtime:
    component = runtime.register(spec, Accumulator)
    result = component.submit("add", 5)
    print(runtime.get(result))
```

`factory` 是一个无参数的可调用对象。注册不会调用 factory。`execution="task"` 每次调用创建实例并在结束后清理；`"actor"` 复用实例，退出 Runtime 时调用可选的 `close()`。

业务方法的关键字参数通过 `component.submit("method", kwargs={...})` 传入。构造 Actor 的关键字参数通过 `runtime.actor(..., kwargs={...})` 传入，构造参数须可序列化，不能包含运行时结果引用。

## CPU 配额与生命周期

`num_cpus` 是逻辑资源声明。在 Ray 中，Actor 在存活期间保留 CPU 配额；为后续经典任务和模拟器任务预留足够的容量。`max_workers` 只控制本地工作线程数。

超时表示软件侧停止等待或报告失败，并不意味着外部设备上的任务已经停止。关闭 Runtime 会清理它拥有的组件；调用者预先建立的 Ray 连接继续归调用者管理。

组件也可以作为可复用[工作流](../workflows/)的绑定对象。量子设备通过[量子 Provider](../providers/)接入，CPU 组件接口不接收任意量子设备资源配置。
