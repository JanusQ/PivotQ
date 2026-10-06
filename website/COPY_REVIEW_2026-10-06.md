# PivotQ 文案修改核对（2026-10-06）

## 技术依据

- 电路计数：`dashboard/backend/program.py` 与 `applications/h2o-hybrid-aimd` 中的 F2 电路实现。预览按电路列表计数，不等同于硬件指令或脉冲数量。
- 累计耗时：`packages/framework/pivotq/_internal/performance/h2o.py` 将同名环节汇总；五个任务阶段和 22 项耗时类别是不同维度。
- 检查标准：水分子应用 `run_aimd.py` 与运行保存的 `metrics.json`、`run_summary.json`、`resolved_config.yaml`。计算检查不宣称完成科学精度验证。
- 未重新执行 Linux 水分子科学计算；页面交互回归使用测试数据，历史截图仍是历史记录。

## 逐项落实

| PDF 序号 | 修改项 | 处理 | 主要位置 |
| --- | --- | --- | --- |
| 1 | 首屏标题与简介 | 已更新对应文案。 | `website/src/components/HomeOverview.astro` |
| 2 | 01 编程模型标题 | 已更新对应文案。 | `website/src/components/HardwareArchitecture.astro` |
| 3 | 01 水分子示例 | 已更新对应文案。 | `website/src/components/HardwareArchitecture.astro` |
| 4 | QPU 代码说明 | 已更新对应文案。 | `website/src/components/HardwareArchitecture.astro` |
| 5 | GPU 代码说明 | 已更新对应文案。 | `website/src/components/HardwareArchitecture.astro` |
| 6 | 作业提交说明 | 已更新对应文案。 | `website/src/components/HardwareArchitecture.astro` |
| 7 | 02 性能分析标题 | 已更新对应文案。 | `website/src/pages/index.astro` |
| 8 | 性能规模说明（待技术核实） | 删除未经本次验证的万量子比特、千卡、百万事件数字，保留模型用途说明。 | `website/src/pages/index.astro` |
| 9 | 工作流总说明 | 已更新对应文案。 | `website/src/components/FlowWorkbench.astro` |
| 10 | 流程节点：任务编排 | 已更新对应文案。 | `website/src/components/FlowWorkbench.astro` |
| 11 | 流程节点：离散事件仿真器 | 已更新对应文案。 | `website/src/components/FlowWorkbench.astro` |
| 12 | 性能报告字段 | 已更新对应文案。 | `website/src/components/FlowWorkbench.astro` |
| 13 | 性能报告字段：运行复杂度（待技术核实） | 未发现统一的算法复杂度报告字段，删除该字段；正文只解释工作量及单位。 | `website/src/components/FlowWorkbench.astro` |
| 14 | 03 教程总标题与说明 | 已更新对应文案。 | `website/src/pages/index.astro` |
| 15 | 水分子教程卡片 | 已更新对应文案。 | `website/src/pages/index.astro` |
| 16 | QRAM 教程卡片 | 已更新对应文案。 | `website/src/pages/index.astro` |
| 17 | 开篇导语 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 18 | 问题与输入：开头 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 19 | 代理势能与 AIMD 的区别 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 20 | 几何特征引言 | 已更新对应文案。 | `website/src/components/AimdModelEquations.astro` |
| 21 | 几何特征公式说明 | 已更新对应文案。 | `website/src/components/AimdModelEquations.astro` |
| 22 | 几何特征转换为旋转角 | 已更新对应文案。 | `website/src/components/AimdModelEquations.astro` |
| 23 | θ、φ 与 theta 的区别 | 已更新对应文案。 | `website/src/components/AimdModelEquations.astro` |
| 24 | 量子特征到势能 | 已更新对应文案。 | `website/src/components/AimdModelEquations.astro` |
| 25 | 能量归一化与预测对象 | 已更新对应文案。 | `website/src/components/AimdModelEquations.astro` |
| 26 | 由能量求力 | 已更新对应文案。 | `website/src/components/AimdModelEquations.astro` |
| 27 | 中心差分公式说明 | 已更新对应文案。 | `website/src/components/AimdModelEquations.astro` |
| 28 | 受力处理与积分 | 已更新对应文案。 | `website/src/components/AimdModelEquations.astro` |
| 29 | 公式对应代码说明 | 已更新对应文案。 | `website/src/components/AimdModelEquations.astro` |
| 30 | 四段代码与轨迹的关系 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 31 | 构造量子电路：环境准备 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 32 | 代码 1、2 运行方式 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 33 | 未赋值参数与摘要 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 34 | 两张电路图的阅读说明 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 35 | 电路深度说明 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 36 | 计算步骤：概述 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 37 | 流程图设备分工（待技术核实） | 明确教程 CPU 数值模拟、目标 QPU 配置与来源不明的导入轨迹，未补写 QPU 实测结论。 | `website/src/pages/examples/aimd.astro` |
| 38 | 流程第 1 步 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 39 | 代码 2 的作用回顾 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 40 | 测量结果与特征 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 41 | 代码 3：计算能量与力 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 42 | 代码 3：差分计算量 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 43 | 代码 3 结尾 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 44 | 轨迹与曲线导语 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 45 | 时间轴说明 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 46 | 键长与键角说明 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 47 | 能量和温度曲线说明 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 48 | 首末帧对比 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 49 | 分子形变说明 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 50 | 能量守恒说明 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 51 | 代码 4：复算步骤 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 52 | 能量差解释 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 53 | 数据来源折叠说明 | 已更新对应文案。 | `website/src/pages/examples/aimd.astro` |
| 54 | 页眉与标题 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 55 | 开篇导语 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 56 | 演示范围说明 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 57 | 普通内存类比 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 58 | 随机访问与地址/数据区别 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 59 | 地址寄存器与数据寄存器 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 60 | 相干查询的解释 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 61 | 与经典查表的区别 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 62 | 两位地址 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 63 | 地址 10 的含义 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 64 | 树形路径与示例代码 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 65 | 路径代码输出说明 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 66 | 树图重复说明 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 67 | 树图对叠加态的限制 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 68 | 存储表导语 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 69 | 固定地址查询 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 70 | 一般查询规则 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 71 | 可逆性解释 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 72 | 叠加地址查询 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 73 | 归一化与张量积符号 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 74 | 输出叠加态说明 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 75 | 纠缠与过渡 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 76 | 代码段标题 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 77 | 查询程序引言 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 78 | 量子比特顺序说明 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 79 | 输入准备函数说明 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 80 | show_components() 说明 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 81 | 电路演示与 QRAM 器件 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 82 | 运行步骤 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 83 | 输出概率说明 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 84 | 单次测量解释 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 85 | 结束段 | 已更新对应文案。 | `website/src/pages/examples/qram.astro` |
| 86 | 系统介绍 | 已更新对应文案。 | `website/src/content/guide/system.md` |
| 87 | 首页示例与工作台教程关系 | 已更新对应文案。 | `website/src/content/guide/system.md` |
| 88 | 使用文档：混合编程 | 已更新对应文案。 | `website/src/content/guide/system.md` |
| 89 | 使用文档：后端扩展 | 已更新对应文案。 | `website/src/content/guide/system.md` |
| 90 | 教程与原理：QRAM 链接 | 已更新对应文案。 | `website/src/content/guide/system.md` |
| 91 | 工作台教程导语 | 已更新对应文案。 同时明确 Linux 启动、门户入口及历史截图关系。 | `website/src/content/guide/aimd.md` |
| 92 | 操作流程概述 | 已更新对应文案。 同时明确 Linux 启动、门户入口及历史截图关系。 | `website/src/content/guide/aimd.md` |
| 93 | 启动与网站关系 | 已更新对应文案。 同时明确 Linux 启动、门户入口及历史截图关系。 | `website/src/content/guide/aimd.md` |
| 94 | 预测配置与真实执行方式 | 已更新对应文案。 同时明确 Linux 启动、门户入口及历史截图关系。 | `website/src/content/guide/aimd.md` |
| 95 | main.py 与 SDK 的关系 | 已更新对应文案。 同时明确 Linux 启动、门户入口及历史截图关系。 | `website/src/content/guide/aimd.md` |
| 96 | 编译按钮的作用 | 已更新对应文案。 同时明确 Linux 启动、门户入口及历史截图关系。 | `website/src/content/guide/aimd.md` |
| 97 | 5 个阶段与 22 项预测的关系 | 已更新对应文案。 同时明确 Linux 启动、门户入口及历史截图关系。 | `website/src/content/guide/aimd.md` |
| 98 | 任务与资源/预测范围 | 已更新对应文案。 同时明确 Linux 启动、门户入口及历史截图关系。 | `website/src/content/guide/aimd.md` |
| 99 | 预测参数说明 | 已更新对应文案。 同时明确 Linux 启动、门户入口及历史截图关系。 | `website/src/content/guide/aimd.md` |
| 100 | 结果中心说明 | 已更新对应文案。 同时明确 Linux 启动、门户入口及历史截图关系。 | `website/src/content/guide/aimd.md` |
| 101 | 预测和实测对比 | 已更新对应文案。 同时明确 Linux 启动、门户入口及历史截图关系。 | `website/src/content/guide/aimd.md` |
| 102 | 三大页面导航 | 已更新对应文案。 | `dashboard/frontend/src/App.tsx` |
| 103 | 工作台应用选择 | 已更新对应文案。 | `dashboard/frontend/src/App.tsx` |
| 104 | 界面品牌（待技术核实） | 新界面统一显示 PivotQ；六张既有截图保留并逐张标为历史记录，正文解释旧 QHAI 标签。未伪造新运行截图。 | `dashboard/frontend/src/App.tsx` |
| 105 | 工作台右侧 | 已更新对应文案。 | `dashboard/frontend/src/App.tsx` |
| 106 | 工作台下方五个阶段 | 已更新对应文案。 | `dashboard/frontend/src/App.tsx` |
| 107 | 设备选择器 | 已更新对应文案。 | `dashboard/frontend/src/App.tsx` |
| 108 | 编译参数摘要 | 已更新对应文案。 | `dashboard/frontend/src/App.tsx` |
| 109 | 电路预览摘要（待技术核实） | 核对 F2 电路及 dashboard 解析：70 基础门 + 1 条组合测量 = Z 基 71 条；X 基另加 6 个旋转门 = 77 条。当前 F2 无屏障，列表若含屏障仍计数；不做设备映射编译。 | `dashboard/frontend/src/components/CircuitDiagram.tsx` |
| 110 | 性能预测页说明 | 已更新对应文案。 | `dashboard/frontend/src/pages/PerformancePage.tsx` |
| 111 | 性能预测摘要 | 已更新对应文案。 | `dashboard/frontend/src/pages/PerformancePage.tsx` |
| 112 | 性能预测摘要 | 已更新对应文案。 | `dashboard/frontend/src/pages/PerformancePage.tsx` |
| 113 | 性能预测摘要 | 已更新对应文案。 | `dashboard/frontend/src/pages/PerformancePage.tsx` |
| 114 | 性能预测明细标题 | 已更新对应文案。 | `dashboard/frontend/src/pages/PerformancePage.tsx` |
| 115 | 耗时卡片百分比 | 已更新对应文案。 | `dashboard/frontend/src/pages/PerformancePage.tsx` |
| 116 | 性能明细：launcher outer（待技术核实） | 按模型耗时分类的含义翻译为中文；保留原始字段标识与累计口径。 | `dashboard/frontend/src/api/labels.ts` |
| 117 | 性能明细：worker exclusive（待技术核实） | 按模型耗时分类的含义翻译为中文；保留原始字段标识与累计口径。 | `dashboard/frontend/src/api/labels.ts` |
| 118 | 性能明细：计算服务初始化 | 已更新对应文案。 | `dashboard/frontend/src/api/labels.ts` |
| 119 | 性能明细：数据初始化 | 已更新对应文案。 | `dashboard/frontend/src/api/labels.ts` |
| 120 | 性能明细：diagnostic input（待技术核实） | 按模型耗时分类的含义翻译为中文；保留原始字段标识与累计口径。 | `dashboard/frontend/src/api/labels.ts` |
| 121 | 性能明细：prepare（待技术核实） | 按模型耗时分类的含义翻译为中文；保留原始字段标识与累计口径。 | `dashboard/frontend/src/api/labels.ts` |
| 122 | 性能明细：circuits | 已更新对应文案。 | `dashboard/frontend/src/api/labels.ts` |
| 123 | 性能明细：qasm export | 已更新对应文案。 | `dashboard/frontend/src/api/labels.ts` |
| 124 | 性能明细：QPU 提交 | 已更新对应文案。 | `dashboard/frontend/src/api/labels.ts` |
| 125 | 性能明细：QPU 采样 | 已更新对应文案。 | `dashboard/frontend/src/api/labels.ts` |
| 126 | 性能明细：decode | 已更新对应文案。 | `dashboard/frontend/src/api/labels.ts` |
| 127 | 性能明细：normalize all（待技术核实） | 按模型耗时分类的含义翻译为中文；保留原始字段标识与累计口径。 | `dashboard/frontend/src/api/labels.ts` |
| 128 | 性能明细：host features（待技术核实） | 按模型耗时分类的含义翻译为中文；保留原始字段标识与累计口径。 | `dashboard/frontend/src/api/labels.ts` |
| 129 | 性能明细：classical | 已更新对应文案。 | `dashboard/frontend/src/api/labels.ts` |
| 130 | 性能明细：host energies（待技术核实） | 按模型耗时分类的含义翻译为中文；保留原始字段标识与累计口径。 | `dashboard/frontend/src/api/labels.ts` |
| 131 | 性能明细：force | 已更新对应文案。 | `dashboard/frontend/src/api/labels.ts` |
| 132 | 性能明细：preflight absolute difference（待技术核实） | 按模型耗时分类的含义翻译为中文；保留原始字段标识与累计口径。 | `dashboard/frontend/src/api/labels.ts` |
| 133 | 性能明细：initial state | 已更新对应文案。 | `dashboard/frontend/src/api/labels.ts` |
| 134 | 性能明细：record | 已更新对应文案。 | `dashboard/frontend/src/api/labels.ts` |
| 135 | 性能明细：积分与记录 | 已更新对应文案。 | `dashboard/frontend/src/api/labels.ts` |
| 136 | 性能明细：结果图表 | 已更新对应文案。 | `dashboard/frontend/src/api/labels.ts` |
| 137 | 性能明细：actor teardown | 已更新对应文案。 | `dashboard/frontend/src/api/labels.ts` |
| 138 | 性能页资源区 | 已更新对应文案。 | `dashboard/frontend/src/pages/PerformancePage.tsx` |
| 139 | 性能页条件说明 | 已更新对应文案。 | `dashboard/frontend/src/pages/PerformancePage.tsx` |
| 140 | 结果中心导语 | 已更新对应文案。 | `dashboard/frontend/src/pages/ResultsPage.tsx` |
| 141 | 结果中心层级标题 | 已更新对应文案。 | `dashboard/frontend/src/pages/ResultsPage.tsx` |
| 142 | 运行摘要（待技术核实） | 改为计算检查并展开实际检查项、记录值及判定标准；读取运行目录的记录和保存配置，未保存阈值明确标缺失。固定残差阈值来自现有实现；短轨迹线性漂移仅供参考。 | `dashboard/backend/results.py` |
| 143 | 运行设备详情 | 已更新对应文案。 | `dashboard/frontend/src/components/TargetAssignments.tsx` |
| 144 | 运行设备详情 | 已更新对应文案。 | `dashboard/frontend/src/components/TargetAssignments.tsx` |
| 145 | 设备详情 | 已更新对应文案。 | `dashboard/frontend/src/components/TargetAssignments.tsx` |
| 146 | 结果图与时间控件 | 已更新对应文案。 | `dashboard/frontend/src/components/Molecule.tsx` |
