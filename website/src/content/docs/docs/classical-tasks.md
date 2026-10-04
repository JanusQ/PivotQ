---
title: 经典任务
description: 提交普通 Python 函数，声明 CPU 需求，并在任务之间传递结果引用。
---

## 提交 Python 函数

函数保持普通 Python 写法，不需要装饰器。下面在本机启动 Ray，由 Worker 执行函数。`submit()` 的额外位置参数传给函数，`kwargs` 传递函数关键字参数。

```python
from pivotq import Runtime


def scale(values, *, factor):
    return [value * factor for value in values]


with Runtime(executor="ray", address="local") as runtime:
    ref = runtime.submit(scale, [1, 2, 3], kwargs={"factor": 2})
    print(runtime.get(ref))  # [2, 4, 6]
```

## 连接任务

将前一步引用作为后一步输入，运行时会解析依赖后再调用函数。引用应来自同一个运行时，不能跨 Runtime 混用。

```python
with Runtime(executor="ray", address="local") as runtime:
    prepared = runtime.submit(scale, [1, 2, 3], kwargs={"factor": 2})
    total = runtime.submit(sum, prepared)
    print(runtime.get(total))  # 12
    runtime.release(prepared, total)
```

独立任务可以并发执行；依赖关系决定调用顺序。循环和条件判断使用 Python 自身的语法。

## CPU 资源与执行器

`num_cpus` 是任务的 CPU 资源声明，Ray 按该声明调度资源；它不会自动把普通函数改写成多线程算法。以下写法连接已有 Ray 集群：

```python
with Runtime(executor="ray", address="auto") as runtime:
    ref = runtime.submit(sum, [1, 2, 3], num_cpus=1)
    print(runtime.get(ref))
```

使用 Ray 时，driver 与 worker 需要相同的 `pivotq` 安装及应用依赖。可序列化函数与数据才能跨进程传递；推荐将可复用函数放入可导入的模块中。

调试函数时可选择 `Runtime(executor="local", max_workers=4)`，通过本地线程池执行，不启动 Ray。`max_workers` 控制并发工作线程数；此模式的 `num_cpus` 只作配置校验，不保证为每个任务预留相应数量的 CPU。

## 等待、释放与关闭

`get(ref)` 阻塞到结果就绪，失败时抛出错误。`release(*refs)` 用于释放不再需要的结果，不是取消任务；不要释放尚需交给后续任务的引用。

优先使用 `with Runtime(...)` 管理生命周期。手动创建时，在 `finally` 中调用 `close()`。运行时只关闭自己拥有的资源，不应关闭调用者已有的 Ray 集群。
