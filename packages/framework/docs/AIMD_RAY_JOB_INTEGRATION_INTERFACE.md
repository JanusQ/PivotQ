# AIMD 程序接入融合编程框架接口说明

## 1. 文档目的

本文说明 AIMD 程序如何以“一次 Ray Job 提交”的方式接入融合编程框架，并在集群侧的 AIMD coordinator 中动态提交框架组件调用。

目标运行形态如下：

```text
本地启动程序
  └── 只提交一次 Ray Job
        └── 集群侧 Driver
              ├── 创建 RayExecutor 和 FusionFramework
              ├── 调用 AIMD 提供的组件注册函数
              └── 调用 AIMD 提供的 runner/coordinator
                    ├── 动态提交 Task 组件
                    ├── 动态调用 Actor 组件
                    ├── 获取并检查结果
                    └── 及时释放调用 handle
```


## 2. 先理解四个对象

### 2.1 本地提交程序

本地提交程序通常是 `submit_job.py`。它运行在开发机、登录节点或其他能访问 Ray Jobs API 的机器上，只负责：

- 构造 `RayJobSpec`；
- 对一次逻辑 AIMD 运行调用一次 `RayJobClient.submit()`；
- 查询状态和日志；
- 必要时请求停止；
- Job 进入终态后按需删除 Jobs 服务元数据。

它不执行 AIMD 时间循环，也不创建融合框架组件。

### 2.2 集群侧 Driver

Driver 是融合框架提供的入口：

```text
python -m pivotq.jobs.driver
```

Ray Jobs 在集群中启动它。Driver 负责连接当前 Ray 集群、创建 Registry/Executor/Framework、导入 AIMD 的注册函数和 runner，并在结束时清理自己拥有的对象。AIMD 团队通常不修改 Driver 源码。

### 2.3 AIMD 接入包

“AIMD 接入包”不是新的第三方依赖，而是 AIMD 项目中新增的一小组 Python 胶水代码。例如：

```text
aimd_project/
├── existing_aimd/          # AIMD 已有科学代码
└── fusion_integration/     # AIMD 接入包
    ├── __init__.py
    ├── components.py
    ├── registration.py
    ├── runner.py
    └── submit_job.py
```

它负责把 AIMD 已有代码连接到融合框架，但不要求重写 AIMD 算法，也不要求发布到 PyPI。目录名称可以自行决定。

### 2.4 框架组件（需要独立调度的计算代码）

本文所说的“外部执行单元”更准确地讲是“需要通过融合框架注册和调度的组件”。“外部”是相对于 Framework 核心和 AIMD coordinator 而言，不表示它一定在另一台物理机器，也不表示必须是 HTTP API。

判断一段代码是否应成为组件，可以依次询问：

1. 它是否需要由 Ray 调度到特定 CPU/GPU/其他资源？
2. 它是否应与 AIMD coordinator 运行在不同进程或节点？
3. 它是否需要复用长期模型、连接、缓存或会话？
4. 它的输入和返回值是否能形成清晰、可序列化的调用边界？

如果这些答案都是“否”，普通 Python 控制逻辑可以继续留在 runner 中，不必为了使用框架而拆成组件。

当前 QPU 接口为三比特 X/Y/Z 与完整八状态概率，由框架服务器上的客户端 Actor 导出 QASM3。
设备通信协议尚未配置，不能描述为真机已经接入。详见 [当前客户端说明](QPU_QASM3_CLIENT.md)。

## 3. 双方交付边界

### 3.1 AIMD 程序需要提供

AIMD 接入包至少需要提供可导入的 runner：

```python
def run_aimd(
    framework: FusionFramework,
    context: RayJobDriverContext,
) -> None:
    ...
```

当前 QPU 组件的注册入口已经由融合框架提供：

```text
pivotq._internal.qpu_integration.registration:register_components
```

如果 AIMD 只调用该 QPU 组件，不需要再编写 QPU 注册函数。如果 AIMD 还要注册其他 CPU/GPU 组件，可以提供一个应用级组合注册函数，在其中调用 QPU 注册入口并注册其他组件。AIMD 科学循环本身不负责注册或创建 Actor。

此外，AIMD 团队需要确定：

- 要通过框架调度哪些外部执行单元；
- 每个执行单元的 `component_id`、允许调用的方法和输入/返回类型；
- 每个组件采用 Task 还是 Actor；
- 每个组件需要的 CPU、GPU 或其他已确认的 Ray 资源；
- AIMD runner 的配置、输出文件、失败策略和停止检查点；
- 所有集群进程需要安装的 Python 依赖及版本。

### 3.2 融合框架负责

- 通过 Ray Jobs 接收一次完整应用提交；
- 在集群侧建立 Driver；
- 创建 `ComponentRegistry -> RayExecutor -> FusionFramework`；
- 按注册信息创建 Ray Task 或 Ray Actor；
- 根据 `ResourceRequest` 施加 Ray 资源约束；
- 传递可序列化参数、结果依赖和返回值；
- 提供 Job 状态、日志、停止和终态元数据删除接口；
- 在 Driver 退出时关闭 Framework、Registry、Actor 和自己建立的 Ray 连接；
- 在显式启用时采集不包含业务 payload 的有界 Trace。


## 4. AIMD 接入包建议结构

以下只是文件组织建议，模块名可以由 AIMD 团队自行确定：

```text
aimd_integration/
├── __init__.py
├── components.py      # 外部执行单元的薄包装或 factory
├── registration.py    # register_components(framework)
├── runner.py          # run_aimd(framework, context)
└── submit_job.py      # 本地一次提交和 Job 管理
```

Driver 使用 `模块路径:属性路径` 导入两个入口，例如：

```text
aimd_integration.registration:register_components
aimd_integration.runner:run_aimd
```

两个函数必须能够被集群侧 Python 环境导入，并且都必须正常返回 `None`。

使用当前独立 QPU 接口且没有其他自定义组件时，注册入口直接使用框架提供的目标，AIMD 项目只需要实现 runner：

```text
pivotq._internal.qpu_integration.registration:register_components
aimd_integration.runner:run_aimd
```

Driver 对这两个入口所做的事情可以简化理解为：

```python
register_components = load_target(registration_target)
run_aimd = load_target(runner_target)
register_components(framework)
run_aimd(framework, context)
```

因此，以下写法不能作为 Driver 入口：

```python
class Integration:
    # 缺少无需实例即可导入和调用的顶层入口。
    def register_components(self, framework):
        ...
```

可以把类方法包装成顶层函数，但传给 Driver 的最终目标仍应满足规定签名。

## 5. 组件接口

### 5.1 组件对象的最小要求

每个注册组件至少需要：

1. 一个不带参数即可调用的 factory；
2. 一个 `describe()` 方法；
3. 注册配置中 `allowed_methods` 列出的所有方法；
4. 可选的 `close()` 方法。

接口骨架如下：

```python
class ExternalComponentAdapter:
    def __init__(self) -> None:
        # 在实际执行进程中初始化外部库或连接。
        ...

    def describe(self) -> dict[str, object]:
        # 不要在这里返回凭据或大体积业务数据。
        return {"name": "external-component"}

    def execute(self, request: object) -> object:
        # 调用 AIMD 选定的真实外部实现。
        ...

    def close(self) -> None:
        # 如有连接、模型或文件句柄，在这里释放。
        ...
```

注册时传入的 factory 只能负责构造一个组件实例，不能要求框架提供业务参数：

```python
def build_external_component() -> ExternalComponentAdapter:
    # 可从部署配置或环境读取非敏感初始化参数。
    return ExternalComponentAdapter()
```

推荐使用模块顶层的类或 factory，避免使用不能稳定序列化的局部函数或闭包。

### 5.2 Task 与 Actor

| 模式 | 生命周期 | 适用情况 |
|---|---|---|
| `ExecutionMode.TASK` | 每次调用构造一个组件实例；调用结束后执行可选 `close()` | 无状态、单次计算 |
| `ExecutionMode.ACTOR` | 一个注册组件复用一个长期实例；Framework 关闭时回收 | 需要复用模型、连接、缓存或会话状态 |

有状态组件必须使用 Actor。Actor 的 `max_concurrency` 默认是 `1`；若外部实现没有经过并发安全验证，不要提高该值。

### 5.3 注册入口示例

下面的组件 ID 和方法名都只是结构示例，不代表框架预设任何 AIMD 业务角色：

```python
from pivotq._internal.framework import (
    ComponentSpec,
    ExecutionMode,
    FusionFramework,
    ResourceRequest,
)

from .components import (
    StatefulComponentAdapter,
    StatelessComponentAdapter,
)


def register_components(framework: FusionFramework) -> None:
    framework.register(
        ComponentSpec(
            component_id="aimd-stateless-step",
            execution=ExecutionMode.TASK,
            resources=ResourceRequest(num_cpus=1),
            allowed_methods=("execute",),
            timeout_seconds=300,
        ),
        StatelessComponentAdapter,
    )

    framework.register(
        ComponentSpec(
            component_id="aimd-stateful-session",
            execution=ExecutionMode.ACTOR,
            resources=ResourceRequest(num_cpus=1),
            allowed_methods=("execute",),
            stateful=True,
            max_concurrency=1,
            timeout_seconds=300,
        ),
        StatefulComponentAdapter,
    )
```

注册函数只执行注册，不要在其中启动 AIMD 循环，也不要显式调用 `ray.init()`。

### 5.4 资源含义

`ComponentSpec.resources` 约束的是该组件实际执行所需的资源，而不是整个 AIMD Job 的资源：

```python
ResourceRequest(
    num_cpus=1,
    num_gpus=0,
    custom_resources={},
)
```

Driver/coordinator 的资源通过 `RayJobDriverResources` 单独配置。不要为了让 coordinator 能提交某种组件，就把该组件资源同时声明给 Driver。

当前预研组件内部暂时声明逻辑 `QPU:1`，但该资源名和容量尚不是正式设备契约。AIMD 不应在自己的 runner 中重复声明或依赖该资源；P8.1 获得真实部署契约后，由 `qpu_integration` 包内部调整。

### 5.5 组件 factory 和配置

框架注册的是零参数 factory：

```python
framework.register(component_spec, component_factory)
```

如果组件需要配置，不要给 factory 增加 Driver 无法提供的位置参数。可选择：

- factory 从部署环境变量读取连接配置；
- factory 从工作目录或配置服务读取配置；
- 使用模块顶层的已配置 factory；
- 把每次调用都会变化的业务参数放到 `framework.submit()`，不要放到 factory。

凭据不能写入源码、Job metadata、Trace 或普通日志。具体的凭据注入方式需与部署环境共同确认。

### 5.6 注册时和第一次调用时会发生什么

`framework.register()` 只验证并保存 factory，不会立即构造组件。因此：

- 注册成功不代表外部库、模型或硬件已经连接成功；
- Task 组件在每次执行调用时构造；
- Actor 组件在首次需要时创建并复用；
- 真正的初始化错误通常会在第一次调用结果中体现；
- AIMD 联调应至少包含一次真实组件健康调用，而不能只测试注册函数。

## 6. AIMD runner 接口

### 6.1 函数签名与所有权

```python
from pivotq._internal.framework import FusionFramework
from pivotq._internal.jobs import RayJobDriverContext


def run_aimd(
    framework: FusionFramework,
    context: RayJobDriverContext,
) -> None:
    ...
```

Driver 已经创建并拥有 Framework、Registry、RayExecutor，以及由 Driver 建立的 Ray 连接。因此 runner：

- 不调用 `ray.init()` 或 `ray.shutdown()`；
- 不调用 `framework.close()`；
- 不关闭 Registry；
- 正常完成时返回 `None`；
- 失败时抛出异常，由 Driver 记录失败状态并执行清理。

`context` 提供：

| 属性/方法 | 含义 |
|---|---|
| `context.run_id` | 本次运行的稳定 ID |
| `context.output_dir` | Driver 已创建的绝对输出目录 |
| `context.stop_requested` | 是否收到 cooperative stop 请求 |
| `context.raise_if_stop_requested()` | 收到停止请求时立即退出 runner |
| `context.trace_collector` | 显式启用 Trace 时的有界 Collector，否则为 `None` |

### 6.2 动态循环模板

下面展示一次 Job 内动态提交 Task 和调用 Actor 的控制结构，不包含 AIMD 科学计算：

```python
from pivotq._internal.framework import FusionFramework
from pivotq._internal.jobs import RayJobDriverContext


def run_aimd(
    framework: FusionFramework,
    context: RayJobDriverContext,
) -> None:
    total_steps = load_total_steps_from_config()

    for step in range(total_steps):
        context.raise_if_stop_requested()

        request = build_step_request(step)
        task_handle = framework.submit(
            "aimd-stateless-step",
            "execute",
            request,
            invocation_id=f"{context.run_id}.task.{step:06d}",
        )

        task_terminal = False
        try:
            task_result = framework.result(task_handle)
            task_terminal = True
            if not task_result.succeeded:
                raise RuntimeError(task_result.error.to_record())

            actor_handle = framework.submit(
                "aimd-stateful-session",
                "execute",
                task_result.value,
                invocation_id=f"{context.run_id}.actor.{step:06d}",
            )

            actor_terminal = False
            try:
                actor_result = framework.result(actor_handle)
                actor_terminal = True
                if not actor_result.succeeded:
                    raise RuntimeError(actor_result.error.to_record())

                update_aimd_state(step, actor_result.value)
            finally:
                if actor_terminal:
                    framework.release(actor_handle)
        finally:
            if task_terminal:
                framework.release(task_handle)
```

模板中的 `load_total_steps_from_config()`、`build_step_request()` 和 `update_aimd_state()` 都由 AIMD 程序实现。

基本调用规则是：

```text
submit() -> result() -> 检查 succeeded -> 使用 value -> release()
```

长时间循环必须及时 `release()` 已经进入终态的 handle，不能把所有 handle 一直保留到 Job 结束。

### 6.3 直接传递组件结果依赖

如果下游组件直接使用上游组件的返回值，可以把上游 handle 作为参数传给下游调用：

```python
upstream = framework.submit(
    "component-a",
    "execute",
    request,
    invocation_id=f"{context.run_id}.upstream.{step:06d}",
)

downstream = framework.submit(
    "component-b",
    "execute",
    upstream,
    invocation_id=f"{context.run_id}.downstream.{step:06d}",
)
```

框架会把依赖结果值注入下游调用。在 Ray 模式下，这条路径不要求 AIMD Driver 先手工搬运中间业务值。下游进入终态并且结果不再使用后，应先释放下游 handle，再释放上游 handle。

### 6.4 输入和返回值约束

- 所有调用参数和组件返回值必须可被 Python `pickle` 序列化；
- 框架把业务对象视为不透明数据，不解释其科学含义；
- `invocation_id` 必须唯一，最长 128 个字符；
- ID 必须以字母或数字开头，只能包含字母、数字、`_`、`-`、`.`；
- 组件方法必须出现在注册时的 `allowed_methods` 中；
- `framework.result()` 返回结构化终态结果，失败时不会把原始业务异常直接作为成功值返回；
- 必须检查 `result.succeeded`，成功值位于 `result.value`，失败信息位于 `result.error`。

如果 `invocation_id` 由 `run_id` 加阶段/时间步后缀生成，应给后缀预留长度。最小模板追加的最长后缀为 `.actor.000000`，所以模板把 `submission_id/run_id` 限制为最多 115 字符。

### 6.5 为什么要使用 handle

`framework.submit()` 返回 `InvocationHandle`，它只代表一次已提交调用的身份和底层引用，不等于计算结果。推荐生命周期为：

```text
创建 handle
  -> result(handle) 等待终态
  -> 检查 result.succeeded
  -> 使用 result.value 或记录结构化错误
  -> release(handle)
```

`framework.invoke()` 虽然可以提交并同步等待，但不把 handle 返回给应用，长时间 AIMD 循环难以显式释放结果，因此优先使用 `submit/result/release`。

### 6.6 串行、依赖图和并发

融合框架支持动态逐步提交，也支持先构造依赖调用：

- 科学上必须等待上一结果时，逐步 `result()` 是正确的串行控制；
- 下游只依赖上游返回值时，可以把上游 handle 直接传给下游；
- 多个调用相互独立时，可以先提交多个 handle，再分别取结果；
- 并发量必须受 Ray 资源容量、外部服务并发限制和内存容量约束。

一次 Ray Job 提交不代表 Job 内所有组件调用自动并行，也不保证均匀分布到所有节点。实际放置由资源声明、依赖、Actor 生命周期和 Ray 调度共同决定。

### 6.7 Framework API 速查

| 调用 | AIMD 应在何时使用 | 返回值/注意事项 |
|---|---|---|
| `framework.register(spec, factory)` | runner 开始前，由 registration 入口调用 | 返回注册记录；不构造组件 |
| `framework.describe(component_id)` | 检查框架保存的静态注册配置 | 不调用组件自己的 `describe()` |
| `framework.submit(component_id, method, ..., invocation_id=...)` | 动态提交一次组件方法 | 返回 `InvocationHandle`，不代表已完成 |
| `framework.result(handle)` | 等待调用终态 | 返回 `InvocationResult`，必须检查 `succeeded` |
| `framework.reference(handle)` | 显式构造下游结果占位符 | 普通场景直接传 handle 即可 |
| `framework.submit_graph(invocations)` | 已知完整 DAG 且希望提交前整体校验 | 结构错误会在任何节点提交前拒绝；执行提交不是事务 |
| `framework.release(handle)` | 终态结果不再使用时 | 释放执行器结果和 façade 记账 |
| `framework.close()` | 由 Driver 负责 | AIMD runner 不调用 |

`ComponentSpec.timeout_seconds` 是组件调用的默认 timeout。若 AIMD 需要绝对时间门限，也可以在 `submit()` 中传入带时区的 UTC `deadline`。timeout/cancel 是框架终态语义，不应被解释成真实外部设备一定已经取消。

### 6.8 暴露给 AIMD 的 QPU 公共接口

公共名称保持 QuantumCircuitRequest、CircuitResult、QPUCircuitService；
run_quantum_circuits(step, circuits, shots=3000) 保持同步调用。
measurement_basis 扩展为 X/Y/Z，measurement_qubits 固定 [0,1,2]；
probabilities 按 000 到 111 包含全部八个状态，零概率显式为 0.0，位序 q0q1q2；完整性须经设备适配层确认。

输入输出、错误和迁移要求统一见 [AIMD QPU 接口](AIMD_QPU_CIRCUIT_INTERFACE.md)。
客户端由框架注册，按 CPU 调度到计算服务器；当前集群各节点均具备运行条件，无需服务器专属标记。
真机包 AIMD 提交脚本与注册入口已适配，Driver 和应用组件保留 CPU/GPU 请求。

## 7. 本地一次提交接口

### 7.1 Ray Jobs 与 Ray Client 不是同一个入口

| 用途 | 地址示例 | 当前接口 |
|---|---|---|
| Ray Client | `ray://<private-head>:10001` | 让 Python Driver 通过 Ray Client 协议连接集群 |
| Ray Jobs API | `http://<private-head>:8265` | 提交、查询、停止和删除一个完整应用 |

任务的“一次提交 + 集群侧 coordinator”使用 Ray Jobs API，不使用 `ray.init(address="ray://...")` 作为本地提交接口。若本地无法直接访问 Head 的 Jobs 端口，需要由部署方提供私网、SSH 隧道或经过认证的 HTTPS 入口。

框架客户端只允许对回环或私网地址使用 HTTP。公网 Jobs 地址必须使用 HTTPS 并验证证书。

### 7.2 提交代码模板

```python
from __future__ import annotations

import shlex
import time

from pivotq._internal.jobs import (
    RayJobClient,
    RayJobDriverResources,
    RayJobRuntimeEnvironment,
    RayJobSpec,
)


def main() -> None:
    submission_id = "aimd-run-0001"
    output_dir = "/persistent/ray-quantum-output"

    entrypoint = shlex.join(
        (
            "python",
            "-m",
            "pivotq._internal.jobs.driver",
            "--run-id",
            submission_id,
            "--registration",
            "aimd_integration.registration:register_components",
            "--runner",
            "aimd_integration.runner:run_aimd",
            "--namespace",
            "aimd",
            "--output-dir",
            output_dir,
            "--trace-max-records",
            "10000",
            "--trace-event-max-records",
            "10000",
        )
    )

    spec = RayJobSpec(
        submission_id=submission_id,
        entrypoint=entrypoint,
        runtime_environment=RayJobRuntimeEnvironment(
            # 该路径由执行 submit_job.py 的机器读取并交给 Ray 打包；
            # 目录中需要包含 AIMD 接入包。pivotq 可以位于同一
            # 部署目录，也可以预装在集群环境中。
            working_dir="/path/to/deployment-directory",
            env_vars={
                "PYTHONPATH": "src:.",
                "AIMD_CONFIG": "configs/run-0001.yaml",
            },
        ),
        metadata={
            "application": "aimd",
            "interface_version": "1",
        },
        # 这里只为 Driver/coordinator 预留 CPU，不是组件资源。
        driver_resources=RayJobDriverResources(num_cpus=0.2),
    )

    client = RayJobClient("http://<private-head>:8265")

    # 对这个 AIMD 运行只调用一次 submit()。
    handle = client.submit(spec)

    while True:
        status = client.status(handle)
        if status.is_terminal:
            break
        time.sleep(1)

    print(f"submission_id={handle.submission_id}")
    print(f"status={status.value}")

    if status.value != "succeeded":
        # 日志可能包含外部程序自行打印的内容，输出前按项目规则脱敏。
        print(client.logs(handle))
        raise RuntimeError(f"AIMD Job ended as {status.value}")


if __name__ == "__main__":
    main()
```

部署时必须将占位地址、工作目录、解释器命令和配置路径替换为实际值。若集群要求固定虚拟环境，应把 entrypoint 中的 `python` 替换为集群侧绝对解释器路径。

本地目录形式的 `working_dir` 必须能被执行提交代码的机器读取，Ray 会把它打包上传；也可以使用当前锁定 Ray 2.31.0 支持的远程 URI。它不是 Driver 制品的持久目录。`--output-dir` 必须是集群侧绝对路径；是否位于共享盘或持久卷由部署方负责。

### 7.3 Job 管理方法

```python
handle = client.submit(spec)       # 提交一个完整应用
status = client.status(handle)     # pending/running/stopped/succeeded/failed
logs = client.logs(handle)         # Ray Jobs 原始日志文本
accepted = client.stop(handle)     # 请求停止 Job 进程
deleted = client.delete(handle)    # 只允许终态后删除 Jobs 服务元数据
```

`stop()` 只表示请求停止 Ray Job/Driver，不等同于取消已经被外部设备接受的作业。QPU 取消和状态对账需要等待实际设备契约。

必须为每次逻辑运行生成稳定且唯一的 `submission_id`。若 `submit()` 因网络异常返回“不确定是否已提交”，应先按同一个 `submission_id` 查询/对账，不能盲目换 ID 重复提交。

### 7.4 工作目录和依赖部署

提交前需要保证以下代码对 Ray Jobs 可用：

- AIMD 接入包；
- AIMD runner 会导入的科学代码；
- 组件 adapter/factory；
- `pivotq` 包；
- 所有 Worker/Actor 需要的第三方依赖。

常见部署方式有两种：

1. `pivotq` 和稳定依赖预装在集群虚拟环境中，`working_dir` 上传 AIMD 应用代码；
2. `working_dir` 同时包含 `pivotq._internal` 和 AIMD 接入代码，并通过 `PYTHONPATH` 暴露。

不要默认 Head 上存在的本地文件也能被 Worker 直接看到。应用代码依靠 runtime environment 分发；大型数据、模型和输出应通过明确的共享存储或对象存储处理。

### 7.5 一次逻辑运行的 ID 建议

推荐让 `submission_id` 与 Driver `run_id` 相同，便于跨 Job、manifest、Trace 和 AIMD 输出关联：

```text
submission_id = aimd-20260812-run001
run_id        = aimd-20260812-run001
invocation_id = aimd-20260812-run001.step.000123.quantum
```

不要在 ID 中放凭据、坐标、线路内容或其他业务 payload。

## 8. Driver 制品、Trace 与错误

### 8.1 Driver manifest

Driver 会在 `output_dir` 写入：

```text
<run_id>.manifest.json
```

主要字段为：

```json
{
  "schema_version": 1,
  "run_id": "aimd-run-0001",
  "status": "succeeded",
  "exit_code": 0,
  "started_at": "...",
  "finished_at": "...",
  "namespace": "aimd",
  "process_id": 12345,
  "cleanup": {
    "framework_closed": true,
    "registry_closed": true,
    "ray_disconnected": true,
    "succeeded": true
  },
  "failure_type": null
}
```

manifest 不保存 AIMD 科学结果。runner 如需保存轨迹、最终状态或审计信息，应自行写入 `context.output_dir` 下独立命名的文件，或写入已约定的外部存储。

### 8.2 可选 Trace

`--trace-max-records N` 启用原有 schema v1 终态 Trace Collector。Collector 在内存中
有界，容量不足时会记录 dropped 数量，不应把它当作无限日志缓冲区。

runner 可以在结束前导出 Trace：

```python
from pivotq._internal.observability import export_trace_jsonl


collector = context.trace_collector
if collector is not None:
    export_trace_jsonl(
        collector,
        context.output_dir / f"{context.run_id}.trace.jsonl",
    )
```

`--trace-event-max-records N` 则显式启用默认关闭的 Trace v2 增量事件。Driver 在
`output_dir` 写入：

```text
<run_id>.trace-v2.jsonl
<run_id>.trace-v2.manifest.json
```

当前框架记录 `submitted`、`started`、`finished` 和 `result_observed`。JSONL 使用单调
cursor，manifest 记录记录数、丢弃数、截断状态、完成状态、文件大小和 SHA-256。该功能由
Driver 所在节点的零 CPU Ray Actor 持有；未传该参数时不创建事件 Actor 或文件。

两种 Trace 都只记录组件/调用 ID、资源、时间、终态和 Ray task/actor/node ID 等框架事实，
不保存业务 payload。调用方传入的 `trace_context` 也只能放短字符串标识，不能放坐标、
量子线路、凭据或模型数据。Trace v2 是 fail-open 的诊断记录，不替代 Ray Job、设备服务或
真实 QPU 的权威状态。

### 8.3 状态层次

不要混用以下三种状态：

| 层次 | 标识 | 典型状态 |
|---|---|---|
| 整个应用 | `submission_id` / `RayJobHandle` | pending、running、stopped、succeeded、failed |
| Driver 制品 | `run_id` / manifest | starting、stop_requested、succeeded、failed |
| 单次组件调用 | `invocation_id` / `InvocationHandle` | succeeded、failed、cancelled、timed_out |

一个 Job 成功表示 runner 正常返回且 Driver 清理成功，不自动证明 AIMD 科学结果正确。科学正确性和结果验收由 AIMD 程序负责。

### 8.4 AIMD 自己的输出

Framework 不规定 AIMD 科学结果 schema。AIMD runner 应自行约定：

- 运行配置快照；
- 初态/终态或轨迹文件；
- 数值单位和 schema 版本；
- 中断恢复所需 checkpoint；
- 科学错误和收敛状态；
- 输出的原子写入或外部持久化方式。

这些制品不能与 Driver manifest 混为一谈。manifest 只说明应用生命周期和框架清理结果。

## 9. 停止、失败和清理要求

- runner 应在每个 AIMD 时间步和长阶段边界调用 `context.raise_if_stop_requested()`；
- 不要捕获并吞掉停止信号；普通业务错误可以写入脱敏审计后重新抛出；
- 每个已经进入终态且不再使用的 handle 都要 `release()`；
- 组件若持有连接、模型或文件句柄，应实现幂等 `close()`；
- runner 抛出异常后，Driver 会尝试关闭 Framework、Registry、Actor 和自己建立的 Ray 连接；
- 强制停止整个 Ray 集群时，Driver 可能来不及把 manifest 从 `starting` 更新为终态；
- 外部系统可能已接受请求时，不得仅凭 Driver 超时或连接中断盲目重试。

对失败调用，AIMD runner 至少应记录以下不敏感信息：

- `run_id` 和 `invocation_id`；
- 组件 ID 和调用阶段；
- `result.status`；
- `result.error.to_record()` 中的结构化字段；
- AIMD 是否停止、重试或进入恢复流程。

不要为了调试把完整坐标、量子线路、凭据或模型输入打印到 Job 日志。

### 9.1 推荐的异常结构

组件调用失败时，推荐保留结构化错误，而不是只拼接自由文本：

```python
result = framework.result(handle)
if not result.succeeded:
    error_record = result.error.to_record()
    raise RuntimeError(
        f"component invocation failed: "
        f"run_id={context.run_id}, "
        f"invocation_id={handle.invocation_id}, "
        f"error={error_record}"
    )
```

如果 AIMD 需要区分“本步可重试”“整条轨迹失败”或“进入 checkpoint 恢复”，应在 AIMD 应用层显式制定策略。不要默认对所有异常自动重试。

### 9.2 runner 成功退出的最低条件

建议 AIMD runner 仅在以下条件全部满足时正常返回 `None`：

- 预期时间步或明确的提前终止条件已完成；
- 所有必须调用的组件均进入已检查的终态；
- 所有不再使用的 handle 已释放；
- AIMD 输出或 checkpoint 已成功持久化；
- 没有尚未对账的外部设备作业；
- 可选 Trace/应用审计已经完成写出。

否则应抛出异常，使 Driver manifest 和 Ray Job 保持失败语义，而不是打印错误后正常返回。

## 10. 可直接运行的最小模板

仓库提供：

```text
examples/aimd_integration_template/
```

模板包含：

- `registration.py`：标准注册入口；
- `runner.py`：标准 runner/coordinator 入口；
- `local_preflight.py`：不连接 Ray 的本地预检；
- `submit_job.py`：在已有 Ray Jobs 集群上只提交一次；
- `README.md`：运行命令和替换清单。

开箱演示模式使用 `tests/fixtures/aimd_template_components.py` 中的无科学含义 Task/Actor。它的作用是验证文件组织、导入、生命周期和部署，不是 AIMD 计算。

模板的详细替换步骤见 [`examples/aimd_integration_template/README.md`](../examples/aimd_integration_template/README.md)。
