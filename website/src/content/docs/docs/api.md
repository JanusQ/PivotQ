---
title: API 参考
description: 按执行编程、系统管理与性能预测查找 PivotQ 公开接口。
---

按模块查阅签名、参数、返回值和生命周期约定。第一次编写程序可先阅读[快速上手](../quickstart/)，完整操作过程位于各主题教程。

常用执行接口与 `QuantumCircuit`、`Parameter` 可从 `pivotq` 顶层导入；完整电路入口、作业管理与性能预测分别从 `pivotq.circuit`、`pivotq.jobs`、`pivotq.performance` 导入。

## 执行与编程

| 模块 | 主要接口 |
| --- | --- |
| <span id="runtime"></span><span id="submit"></span><span id="get"></span><span id="release"></span><span id="close"></span>[运行时与结果引用](./runtime/) | `Runtime`、`ResultRef`、`submit/get/release`、`wait/status/resources` |
| <span id="cpu-组件与-actor"></span>[组件与 Actor](./components/) | `ComponentSpec`、`ComponentHandle`、`register/actor` |
| <span id="workflow"></span>[工作流](./workflows/) | `Workflow`、`NodeRef`、`WorkflowRun`、`Runtime.run` |
| [电路构造与参数](./quantum/#电路构造与参数) | `pivotq.circuit`：电路、寄存器、参数、编译与序列化 |
| <span id="quantum_backend"></span><span id="quantumresult"></span><span id="submit-1"></span>[量子后端与结果](./quantum/) | `QuantumBackend`、`QuantumResult`、`quantum_backend` |
| <span id="第三方-provider"></span>[Provider 扩展协议](./providers/) | `BackendCapabilities`、`QuantumRequest`、`ProviderResult`、`QuantumProvider` |

## 系统管理

| 模块 | 主要接口 |
| --- | --- |
| <span id="waitstatus-与-report"></span>[状态与执行报告](./observability/) | `InvocationStatus`、`ExecutionReport`、`Runtime.report` |
| <span id="集群作业"></span>[集群作业](./jobs/) | `JobClient`、`JobSpec`、`JobHandle`、`JobStatus` |
| <span id="生命周期与错误"></span>[异常与错误处理](./errors/) | `PivotQError`、`ResultUnknownError`、提交异常和重试建议 |

## 性能预测

| 模块 | 主要接口 |
| --- | --- |
| <span id="性能模型与预测"></span>[性能模型与预测](./performance/) | `Workload`、`Hardware`、CPU/QPU/链路配置、`Predictor`、`PredictionResult` |

性能模型独立描述任务与硬件，不依赖正在运行的 Ray 集群或 QPU。执行程序使用 `Runtime`；预测模型使用 `Workload`。
