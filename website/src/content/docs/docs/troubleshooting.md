---
title: 常见问题
description: 定位安装、依赖、量子电路和设备调用中常见的问题。
---

## 无法导入 pivotq

确认 Python 为 3.12，当前终端已激活安装库时的虚拟环境：

```bash
python --version
python -m pip show pivotq
python -c "import pivotq; print(pivotq.__file__)"
```

从源码安装时，安装目录为仓库中的 `packages/framework`。若使用仓库统一环境，请在仓库根目录执行 `uv sync --locked`。

<span id="文档中的示例在哪里"></span>

## 文档中的教程程序在哪里

混合程序教程的完整代码位于 `packages/framework/examples/hybrid_program.py`。快速上手页面展示该文件中的代码；请在仓库根目录运行该程序。网页中的代码块支持复制。

`system_workflow.py`、`custom_backend.py`、`performance_prediction.py` 位于同一目录，分别用于工作流、Provider 扩展和性能预测；对应文档也直接读取这些源码。

## QPU Provider 缺少依赖或配置

按部署方或 Provider 文档安装对应适配器及其客户端依赖，并在 Driver 与执行节点上保持版本一致。创建后端时通过 `runtime.quantum_backend(name, **config)` 传入该 Provider 要求的配置；参数名称由适配器定义。

SDK 不会为用户创建设备服务或自动适配任意 QPU；注册与创建后端不连接设备。接入方法见[接入 QPU 后端](../quantum-backends/#接入-qpu-后端)与[Provider 协议](../providers/)。

## 电路被拒绝

先核对参数是否全部绑定，是否含中途测量、reset、initialize 或经典控制流。用 `backend.describe()` 检查 Provider 声明的比特范围；电路还需符合设备适配器支持的门集和编译要求。提交前可以打印 `circuit.num_qubits`、`circuit.num_parameters` 与电路图。

## 为什么位串看起来反了

Qiskit 把最高编号经典位放在左侧，`"01"` 的 c0 是 1。有显式测量时按 qubit → clbit 映射输出；未测量时按全部 qubit 的 Qiskit 顺序输出。参见[测量与位序](../quantum-backends/#测量与位序)。

## 为什么采样概率会变化

模拟器会实际执行有限次数抽样。设置同一个 `seed` 可复现抽样；增大 `shots` 可减小统计波动。该结果不包含真实 QPU 的噪声。

## QPU 超时或结果状态未知

保留错误中的作业标识，向设备端查询任务状态。超时并不证明硬件任务没有执行，重新提交可能重复计算。当前 SDK 不会自动改用模拟器或重新执行未知状态的硬件任务。

## Ray worker 找不到应用代码

确认所有执行节点安装了相同版本的 `pivotq` 与应用依赖，且可以导入用户函数所在模块。先用本地执行器跑通程序，再核对集群中的 Python、文件路径与环境。

## Actor 已启动，但后续任务一直 pending

检查 Actor 的 `num_cpus` 是否长期占满可用配额。CPU Actor 在 Ray 中存活期间保留资源；为经典 Task 和模拟器 Task 留出容量。`runtime.resources()` 显示逻辑总容量，不表示空闲容量。

## 工作流结果无法释放

`run.release()` 要求全部节点工作结束。某个输出完成时，其他分支仍可能运行；使用 `runtime.wait(run.refs, num_returns=len(run.refs), timeout=...)` 检查。失败引用也要等其执行结束后再释放。

## 第三方 Provider 的分布被拒绝

检查返回位串是否覆盖全部逻辑量子位并遵循 `q[n-1]…q0`，shots 是否经后端确认，counts 总和与概率是否一致。SDK 会自行应用用户的末尾测量映射。真实后端返回无效结果时，任务可能已经执行，只是结果无法确认；此时不应直接重新提交任务。

## 性能模拟器无法加载

先调用 `Predictor().availability()` 查看环境，再检查系统是否为 Linux x86-64、所需运行库是否兼容。较旧系统可显式传入已有的 `native_runtime` 或设置 `FUSION_QPERFSIM_RUNTIME`；SDK 不下载运行库。`preview()` 可独立检查输入模型。

## 集群作业提交结果未知

保留 `JobSubmissionError.framework_job_id`，用 `client.status(id)` 查询该次提交。不要换一个新标识自动重试；停止 Ray 作业也不等于取消其已经发出的物理设备任务。
