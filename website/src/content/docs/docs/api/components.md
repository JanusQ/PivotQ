---
title: 组件与 Actor
description: CPU 组件声明、方法白名单、常驻 Actor 和组件句柄接口。
---

```python
from pivotq import ComponentSpec, ComponentHandle
```

Task 组件每次调用构造业务实例，Actor 复用实例状态。完整示例见[组件与 Actor 教程](../../components-actors/)。

## ComponentSpec

```python
ComponentSpec(name, methods, execution="task", num_cpus=1,
              max_concurrency=None, timeout_seconds=None, metadata=())
```

| 参数 | 约定 |
| --- | --- |
| `name` | 当前 Runtime 内唯一的非空组件名 |
| `methods` | 非空、无重复的方法名序列；只允许公开同步业务方法，不包含 `close/describe` |
| `execution` | `"task"` 或 `"actor"` |
| `num_cpus` | 正的 CPU 资源请求，默认 1 |
| `max_concurrency` | 仅 Actor 可设置的正整数并发上限；未设置时串行 |
| `timeout_seconds` | 正的执行超时秒数；`None` 表示不设置 |
| `metadata` | 字符串键值标签，可用字典或键值对序列；不保存业务载荷与凭据 |

超时由执行器实现：本地执行在依赖解析后开始计时，Ray 执行包含依赖等待时间。`spec.metadata_dict()` 返回元数据字典副本。

## register

```python
runtime.register(spec, factory) -> ComponentHandle
```

`factory()` 返回实现白名单方法的普通业务对象，无需实现内部描述接口。注册时不构造业务实例；实例提供 `close()` 时由框架清理调用。

## actor

```python
runtime.actor(constructor, /, *args, methods, name=None,
              num_cpus=1, max_concurrency=1, timeout_seconds=None,
              metadata=None, kwargs=None) -> ComponentHandle
```

便捷注册一个常驻 Actor，首次调用时构造实例。构造参数为普通可序列化值，通过 `args` 与 `kwargs` 传递；方法参数可以使用结果引用。省略 `name` 时自动生成名称。

默认同一实例串行执行。需要保证状态更新之间的依赖时，应显式传递前次结果；工作流会为绑定到同一串行 Actor 的节点补充构图顺序依赖。

## ComponentHandle

```python
component.submit(method, /, *args, kwargs=None) -> ResultRef
component.describe() -> ComponentSpec
component.spec -> ComponentSpec
```

`submit` 仅接受声明过的方法名。参数可直接包含结果引用，或将引用放入普通列表、元组和字典值中。句柄属于创建它的 Runtime，不能跨 Runtime 使用或作为业务载荷序列化。组件实例由 Runtime 统一关闭。
