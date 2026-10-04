---
title: 工作流
description: Workflow 静态任务图、节点引用、运行时绑定及运行结果接口。
---

```python
from pivotq import Workflow, NodeRef, WorkflowRun, WorkflowSubmissionError
```

`Workflow` 描述可复用的执行依赖图，每次运行可替换输入和组件绑定；循环与条件由图外的 Python 程序控制。教程见[可复用工作流](../../workflows/)。

## Workflow

```python
workflow = Workflow(name="workflow")
```

输入名与节点名在同一工作流内唯一。添加节点时保存普通字面参数的副本；节点只引用已声明输入和较早节点，从构建过程保证无环。首次通过校验的提交冻结图结构，后续仍可重复运行。

## input 与 NodeRef

```python
workflow.input(name) -> NodeRef
```

声明运行时输入。`NodeRef` 表示图中的值，公开属性 `name` 为其名称；它尚未提交，不能用 `runtime.get` 读取或直接作布尔判断。节点参数支持直接引用及普通列表、元组、字典值中的嵌套引用。

## task

```python
workflow.task(fn, /, *args, num_cpus=1, kwargs=None, name=None) -> NodeRef
```

绑定同步 CPU 函数，资源和业务参数约定与 [`runtime.submit`](../runtime/#submit) 一致。省略 `name` 时自动生成节点名。

## component

```python
workflow.component(binding, method, /, *args, kwargs=None, name=None) -> NodeRef
```

`binding` 为逻辑组件别名，运行时绑定到 `ComponentHandle`；`method` 必须在组件的方法白名单中。

## quantum

```python
workflow.quantum(binding, circuit, *, shots=1024, seed=None, name=None) -> NodeRef
```

`binding` 为量子后端逻辑别名。`circuit` 可直接提供电路，也可引用产生电路的输入或节点。种子与电路约束见[量子后端](../quantum/#submit)。

## output

```python
workflow.output(name, ref) -> None
```

声明输出名和对应的计算节点引用；不能直接把输入引用设为输出。每个工作流至少声明一个输出。

## run

```python
runtime.run(workflow, *, inputs=None, bindings=None) -> WorkflowRun
```

`inputs` 的键必须与声明输入完全匹配，值为普通可序列化业务值。`bindings` 的键必须与使用的别名完全匹配，值为同一 Runtime 的组件句柄或量子后端。

提交前校验全部输入、绑定与方法。同一串行 Actor 的节点按构图顺序补充依赖；同一 Actor 跨多轮运行可持续保存状态。每轮产生独立调用 ID。

## WorkflowRun

| 属性或方法 | 含义 |
| --- | --- |
| `run_id` / `name` | 本轮唯一标识与工作流名称 |
| `outputs` | 输出名到 `ResultRef` 的只读映射 |
| `refs` | 本轮全部计算节点的结果引用元组，包含中间结果 |
| `release()` | 释放本轮已完成结果，等价于 `runtime.release(*run.refs)` |

使用 `runtime.get(run.outputs["result"])` 读取业务结果。若提交中途失败，`WorkflowSubmissionError.partial_run` 保留已经接受的引用；不自动重提。参见[异常与错误处理](../errors/)。
