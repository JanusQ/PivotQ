---
title: PivotQ 使用指南
description: 安装 PivotQ，用 Python 编写 CPU 与 QPU 协作的混合程序。
---

PivotQ 是量超融合系统的 Python 编程库，通过 Ray 调度经典任务与量子后端调用。用普通 Python 函数处理经典计算，用 Qiskit 构造量子电路，再通过结果引用连接计算步骤。用户选择量子模拟器或已配置的 QPU 后端。

第一次使用，先[安装 PivotQ](./installation/)，再运行[快速上手](./quickstart/)中的完整示例：在本机启动 Ray，完成经典预处理、量子执行与经典更新。示例默认不连接 QPU，量子电路由 CPU 模拟；任务与依赖通过 Ray 调度。

## 选择阅读路径

| 分类 | 阅读顺序与用途 |
| --- | --- |
| 入门 | 先[安装](./installation/)，再跑通[快速上手](./quickstart/)；遇到问题查阅[常见问题](./troubleshooting/)。 |
| 混合编程 | 从[经典任务](./classical-tasks/)与[量子后端](./quantum-backends/)开始，组合为[混合程序](./hybrid-programs/)，再使用[组件与 Actor](./components-actors/)保存状态、用[工作流](./workflows/)复用任务图。 |
| 运行与管理 | 用[集群作业](./jobs/)提交完整程序，通过[状态与执行报告](./observability/)查看执行过程。 |
| 性能建模与预测 | 定义[硬件性能模型](./hardware-profiles/)，运行[性能预测](./performance/)并比较方案。 |
| 后端扩展 | 实现 Provider，[接入自己的模拟器或量子设备](./providers/)。 |
| API 参考 | 按模块查阅[接口签名、参数与返回值](./api/)。 |
| 应用示例 | 查看[示例导航](./examples/)或阅读水分子 AIMD 的[工作台教程](./aimd/)。 |

## 系统如何组成

应用定义算法；PivotQ 组织任务、依赖与量子后端调用，Ray 执行器负责将任务提交给本机或集群中的 Worker。QPU 通过统一的量子后端接口接入，由 Provider 适配具体设备服务。另提供本地线程池执行器用于函数调试，使用 `Runtime()` 时默认为这一模式；快速上手主流程显式选择 Ray。

性能模拟器接收任务描述与目标硬件配置，用于估算执行耗时；它需要应用提供相应工作负载，不会自动为任意 Python 程序生成可靠的耗时预测。工作台为已接入的应用提供配置和结果视图。

## 编程与工作台

Python SDK 支持用户在自己的文件中编写程序。网页工作台目前支持预设 AIMD 应用与受控电路编辑，网页中的 `qhai.tasks` 写法属于工作台配置语法。SDK 的入口是 `import pivotq`。

水分子 AIMD 是一个应用示例。它的模型、特征与科学验收条件不限制用户通过 SDK 编写其他混合程序。

完整公开接口见 [API 参考](./api/)。组件、任务图、作业、性能模型和 Provider 均通过 `pivotq` 包访问，不需要外部用户导入内部开发接口。
