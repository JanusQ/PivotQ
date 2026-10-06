---
title: GPU 与异构资源
description: 了解量超智融合系统中 CPU、GPU、QPU 的资源声明，运行 GPU 组件所需的环境，以及 GPU 性能预测入口。
---

PivotQ 的量超智融合流程可以连接 CPU 通用计算、GPU 加速计算与 QPU 量子计算。用户为组件声明资源，框架通过 Ray 组织依赖和执行；应用代码负责使用 CUDA 等工具，在分配到的 GPU 上运行模型推理或其他加速算法。

## 选择接入方式

| 入口 | 资源与能力 |
| --- | --- |
| 公开 Python SDK | `Runtime.submit()`、组件与 Actor 接口目前提供 `num_cpus`；量子计算通过后端与 Provider 接入。 |
| 仓库中的应用桥接与 Ray 组件 | 内部 `ResourceRequest` 支持 `num_gpus` 与自定义资源，Ray Task / Actor 按声明请求 GPU。运行应用前，需部署所需的软件与硬件环境。 |
| 性能模拟器 | 可以描述 CPU/GPU/QPU 目标场景。GPU 场景使用 QPerfSim 的 YAML/JSON 任务图接口或工作台。 |

公开 SDK 的签名见[运行时与结果引用](../api/runtime/)和[组件与 Actor](../api/components/)。当前不能给这些公开接口直接添加 `num_gpus` 参数。仓库内的 GPU 验证程序使用内部应用集成接口，开发独立 SDK 程序时应先确认所选入口支持的资源配置。

## GPU 组件如何执行

仓库中的 [CPU → GPU → QPU 客户端验证教程](https://github.com/JanusQ/PivotQ/tree/main/packages/framework/examples/hybrid_cpu_gpu_qpu_fake) 展示了一条完整数据依赖链：

1. CPU Task 生成 `-1`。
2. GPU Task 使用 PyTorch CUDA 计算 `acos(-1)=π`，并把角度传回调用方。
3. Driver 在 CPU 侧通过 `pivotq.QuantumCircuit` 用角度构造电路，QPU 客户端导出 QASM3 并调用测试适配器。
4. 测试适配器返回固定 counts，客户端整理为完整概率数组并保存执行记录。

其中 GPU 阶段确实调用 CUDA；QPU 测试适配器返回的是固定数据，不连接真实设备，也不计算量子电路的数值测量结果。

以下是该教程的程序在 `registration.py` 中使用的内部资源声明：

```python
from pivotq._internal.framework import ResourceRequest

gpu_resources = ResourceRequest(num_cpus=0, num_gpus=1)
```

这一声明由仓库内的组件注册代码交给 Ray 执行器。`num_gpus=1` 用于申请 GPU 资源；组件本身仍需显式创建 CUDA 张量并执行 GPU 算法。声明资源不会自动把普通 Python 或 CPU 张量运算迁移到 GPU。

运行该验证程序前，需要准备 Ray Jobs 服务、带 `CPU_HEAD` 资源标记的 Head、至少一份可分配的 GPU 资源，以及兼容的 GPU 驱动、CUDA 和 PyTorch。该教程的程序还使用仓库测试夹具，必须从完整源码目录运行。提交入口及参数在同目录的 `submit_job.py`；它支持设置服务地址、工作目录、远程 Python 路径、独立作业 ID 和输出目录，并设置 300 秒提交侧超时。

CUDA 不可用时，教程中的程序会明确报错。应根据执行记录中的设备名称、CUDA 可用性和资源分配情况，确认任务是否实际在 GPU 上执行；不能仅凭任务名称或目标配置认定已经使用 GPU。

## GPU 性能预测

QPerfSim 接收场景 YAML 和任务图 JSON。场景描述 CPU/GPU/QPU 规格、设备数量、链路带宽与时延；任务图描述步骤、工作量、数据传输及依赖。预测本身无需连接真实 GPU 或 QPU。

先按[安装说明](../installation/)安装 `pivotq`。从仓库根目录进入性能模拟器目录，使用自带的 GPU 演示场景：

```bash
cd packages/perf-sim
python scripts/predict_task.py \
  --scenario examples/generic_quantum/gpu/scenario.yaml \
  --out results/task_gpu
```

输出目录必须不存在或为空。该命令会保存 `prediction.json`、输入副本与原生预测结果；教程采用的设备参数属于演示配置，替换硬件或任务时应更新参数和工作量。场景格式及 GPU/QPU 方案比较见 [QPerfSim 使用说明](https://github.com/JanusQ/PivotQ/blob/main/packages/perf-sim/README.md)。

公开 `pivotq.performance` 的 `Workload` / `Hardware` 构建器目前直接支持 CPU、QPU 和通信链路，没有 `GPUProfile`、`Workload.gpu` 或 `Hardware.gpu`。使用 GPU 场景时，请选择上述场景接口。

## 目标配置与实际执行

工作台的 GPU 目标配置用于选择应用支持的资源或预测场景；实际后端由部署模式和任务提交路径决定。默认本地数值模式会在 CPU 上执行，资源列表中的 GPU 型号不能证明本次任务使用了 GPU。

[水分子动力学模拟工作台教程](../aimd/)保留已采集的 CPU/QPU 目标配置与 CPU 数值模拟截图。历史 GPU 运行结果按其原始记录保留；不能直接将目标硬件的预测耗时与其他后端实测耗时之间的差异视为预测误差。
