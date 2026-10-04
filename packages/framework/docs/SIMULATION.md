# 缺失硬件时的 CPU 模拟

`FusionFramework(executor, simulation=False)` 默认使用原组件和资源。
`simulation=True` 允许把不存在或未配置的硬件请求交给显式注册的 CPU 实现。
Ray 检查存活节点的总容量，已安装但繁忙的设备继续走原路径排队。
设备配置或执行出错不会自动转为模拟重试。

每次运行使用独立的 `ComponentRegistry`。选择在首次执行或调用
`resolve_execution(component_id)` 时固定，Task 和 Actor 都不在运行中更换后端。
通用 GPU 替代需要应用提供兼容的 CPU factory；框架不改写任意 CUDA 代码。

## QPU 电路接口

`register_qpu_client(framework)` 在模拟模式下注册内置的 `StatevectorQPUComponent`
作为候选替代实现。QPU 可用性依据 `QPU_DEVICE_CONFIG_FILE` / `QPU_DEVICE_ID` 或
`QPU_DEVICE_URL`，只读取配置、不探测网络。已配置的设备保留真实执行路径；原资源请求中
显式的节点和 QPU token 也必须能匹配一个存活节点。

以下本地示例假定没有配置 QPU 设备。若已有设备配置，`simulation=True` 不会强制覆盖它：

```python
from types import SimpleNamespace
from qiskit import QuantumCircuit
from pivotq._internal.executors import LocalExecutor
from pivotq._internal.framework import ComponentRegistry, FusionFramework
from pivotq._internal.qpu_integration import QPUCircuitService, QuantumCircuitRequest
from pivotq._internal.qpu_integration.component import register_qpu_client

registry = ComponentRegistry()
try:
    with FusionFramework(LocalExecutor(registry), simulation=True) as framework:
        register_qpu_client(framework)
        context = SimpleNamespace(
            run_id="local-simulation", raise_if_stop_requested=lambda: None,
        )
        circuit = QuantumCircuit(3)
        circuit.x(0)
        results = QPUCircuitService(framework, context).run_quantum_circuits(
            step=0,
            circuits=[QuantumCircuitRequest("example.Z", circuit, "Z")],
            shots=3000,
        )
        assert results[0]["probabilities"]["100"] == 1.0
        report = framework.execution_report()
finally:
    registry.close()
```

CPU 组件直接对原始 Qiskit `QuantumCircuit` 计算理想 statevector，不经历 QASM 导出再解析。
目前接受已绑定参数、无测量或其他随机/动态操作的三比特酉电路。设备噪声不在此模式中模拟。

返回契约保留 circuit ID、请求顺序、测量基标识以及 `measurement_qubits=[0,1,2]`。
`probabilities` 始终包含 `000` 到 `111` 八个键，包括明确的零概率；字符从左到右代表
`q0,q1,q2`，框架已经转换 Qiskit 的数组索引位序。
`measurement_basis` 只是元数据，X/Y 测量所需换基由应用在输入电路中完成，模拟器不重复施加。

## 精确概率和 shots

当前内置 QPU 模拟只有 `exact_probabilities` 模式。改变请求的 shots 不改变计算出的概率。

| 字段 | 精确模拟中的含义 |
| --- | --- |
| 电路结果 `shots` | 回显请求值，兼容现有调用方的匹配校验 |
| `simulation.requested_shots` | 用户请求的 shots，作为审计信息保留 |
| `simulation.effective_shots` | `null`，没有进行有限次采样 |
| `simulation.total_physical_executions` | `0`，没有物理 QPU 执行 |
| `simulation.real_hardware` | `false` |

这些字段不能解释为在真机执行了对应次数的 shots。H₂O bridge 进一步把量子特征估计方差
设为零，把特征响应中的 `shots` 和 `shots_per_measurement_basis` 设为 `None`，并保留
`requested_shots`；科学应用的有限差分、模型参数和积分算法不变。

## 可选 H₂O bridge

框架的可选入口为：

```python
registration_target = "pivotq._internal.integrations.h2o:register_components"
runner_target = "pivotq._internal.integrations.h2o:run"
```

在 `RayJobDriverConfig` 中设置 `simulation=True`，或在
`python -m pivotq.jobs.driver` 命令中传入 `--simulation`，并使用这两个入口。
仅导入 `pivotq._internal.integrations.h2o` 不加载 AIMD 或 Torch；实际调用入口时才需要已安装
`single_h20_aimd` 及其科学计算依赖。

该 bridge 使用原 AIMD 注册流程和 `execute_aimd_run_task` 的现有注入接口。应用继续声明
GPU/QPU 目标，框架的 CPU 包装器在组件边界适配设备参数。量子 GPU Task 复用原 CPU
statevector worker；经典 GPU Actor 复用原模型会话；QPU 路径复用原 F2 电路和 14 维特征，
通过框架的 QPU 电路服务计算精确概率。关闭模拟时，bridge 委托原 AIMD runner。

在统一仓库根目录，可以使用现成的本地 Ray 启动入口：

```bash
uv run --locked python -B tests/integration/run_cpu_aimd.py --steps 1000
uv run --locked python -B tests/integration/run_cpu_aimd.py --quantum-target gpu --steps 10
```

第一条保留 QPU 量子请求和 GPU 经典推理请求，使用独立的本地 CPU Ray 集群进行模拟。
第二条验证 GPU 量子 Task 的替代路线。具体产物与科学验收见仓库
[`tests/integration/README.md`](../../../tests/integration/README.md)。

## 执行事实与计数范围

应用的硬件目标保存在 `requested_execution`；框架的 `runtime_execution` 和 Trace
记录请求设备、实际设备、替代后端和实际 Ray 资源。Trace 的 `resources` 是实际调度资源，
`trace_context` 下的 `simulation.*` 保留原资源和设备声明。CPU 计时表示本次模拟的运行时间，
不表示被替代硬件的性能。

H₂O 模拟器的执行计数覆盖整个 runner 生命周期，包括轨迹开始前的初始力、力一致性检查和
其他预检。因此证据中的 `scope=entire_run_including_preflight` 表示“包括预检的整次运行”，
不是“仅 MD 积分阶段”。`total_batches` 是特征提取批次数；`total_circuit_evaluations`
统计处理过的几何数；`total_measurement_circuit_settings` 统计 Z/X 电路设置数，为几何数的
两倍。这些是 CPU 上的逻辑工作量，`total_physical_executions` 始终为零。框架摘要不得把这些
总数直接当作 MD 步数或真机执行次数。
