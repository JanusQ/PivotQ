# PivotQ 全站文案审校与落实记录

初次检查：2026-10-05。文案修改完成：2026-10-06。目标：[本机 4321 网站](http://127.0.0.1:4321/)，对应当前仓库的 `website/`。

首页指定句按当前源码记录为：

> PivotQ 可利用真机运行或性能仿真引擎生成详细的性能报告，发现瓶颈。

位置：[首页第 20 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/index.astro:20)。本记录保留当前版本，未回填早期改写；最新页面显示与浏览器回归均已通过，结果见下文。

本次 **134 条全部完成**，包括 **112 条句法、搭配或指代问题和 22 条可选润色**，对应 132 条页面文本与 2 处截图内嵌文字。每个实际位置分别计数，同类措辞在正文、替代文字或截图中重复出现时分别记录。逐条记录保留原文和原因，以当前落实记录中的最终文案、源文件、行号和调整说明为准。

## 检查范围与落实结果

初次审校覆盖全部 31 个内容页面及 404 页面，包括首页、导航与页脚、文档正文和表格、API 说明、应用教程、页面摘要、无障碍说明，以及 6 张教程截图。当次路由检查中，31 个内容页面均返回 HTTP 200；404 页面显示预期错误内容。根据页面源码和站内链接核对，未发现未覆盖的内容路由。本轮 32 个路由的状态码全部符合预期，132 条页面文本均已在当前 4321 页面匹配，修订截图引用正确；使用本机 Chrome 运行的浏览器回归已通过。

动态加载、校验错误、复制状态、图表读数及电路标签按实际挂载组件的源码审读；未逐一强制触发所有错误状态。第三方编辑器或浏览器自身生成的提示不在本站文案清单中。

六张教程截图均已审读。结果中心截图仅修改两处文字：任务记录的自动更新说明和已完成时间步数标签，另存为[文案修订图](/Users/siwei/Developer/codex_project/PivotQ/website/src/assets/guides/aimd/05-results-center-copy-edited.png)，并更新教程引用；[原始截图](/Users/siwei/Developer/codex_project/PivotQ/website/src/assets/guides/aimd/05-results-center.png)保留。两处编辑区域之外的像素保持一致，截图中的数值与其余内容未改动。

本次调整限于表述质量，保留原有数值、API 标识及真机、仿真、预测、实测的区分，不将规模文案当作新的性能测量结论。同期发生的教程润色已按当前段落重新核对，相关条目记录最终可见文案；本次文案修改保留 Markdown 代码块以及 Astro 的脚本、样式和 `pre` 代码展示内容；该说明不涵盖同期其他任务的变更。

| 范围 | 问题修改 | 可选润色 | 已完成 |
| --- | ---: | ---: | ---: |
| 首页、总览与公共文案 | 15 | 4 | 19 / 19 |
| 入门、编程与运行文档 | 34 | 8 | 42 / 42 |
| 性能、后端与 API 文档 | 35 | 2 | 37 / 37 |
| 应用教程与工作台教程 | 26 | 8 | 34 / 34 |
| 教程截图内嵌文字 | 2 | 0 | 2 / 2 |
| **合计** | **112** | **22** | **134 / 134** |

已完成校验：2026-10-06 00:08（BST）对最终源文件重跑 `npm run check`，56 个文件，0 错误、0 警告、0 提示；`npm run build` 成功生成 32 个页面；`git diff --check` 通过。构建仍有既有的 MDX 指令处理、较大 JS 分块及未配置正式 site URL 时跳过 sitemap 的提示。当前 4321 网站的 32 个路由状态码全部符合预期，132 / 132 条页面文本逐条匹配，修订截图引用正确。使用本机 Chrome 运行浏览器回归，**151 个场景和 41 个站内链接全部通过**，涵盖截图加载、桌面与移动端交互；未发现 JavaScript 错误或意外外部资源请求。回归截图保存于 [website/artifacts/root/](/Users/siwei/Developer/codex_project/PivotQ/website/artifacts/root)。

## 按页面逐条列出

### 首页（13 条）

页面：[http://127.0.0.1:4321/](http://127.0.0.1:4321/)

**001 · 首屏标题**（已完成；可选润色）

位置：[website/src/components/HomeOverview.astro:13](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/HomeOverview.astro:13)

原文：统一描述 QPU、CPU、GPU 计算任务，实现自动调度执行。

最终文案：统一描述 QPU、CPU、GPU 的计算任务，由 PivotQ 自动调度并执行。

原因：“实现自动调度执行”将多个动作名词化，读起来较生硬。

**002 · 编程模型简介**（已完成；建议修改）

位置：[website/src/components/HardwareArchitecture.astro:9](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/HardwareArchitecture.astro:9)

原文：以使用 PivotQ 进行水分子动力学（AIMD）计算为例：CPU 给出三个原子的位置并安排计算；QPU 运行量子电路，CPU 将测量结果整理成一组数；GPU 用这组数预测能量；CPU 再算出受力，更新原子位置。

最终文案：以水分子动力学计算为例：CPU 读取 H-O-H 三个原子的坐标并准备输入；QPU 运行量子电路，CPU 将测量结果整理为量子特征；GPU 根据这些特征预测能量；CPU 再计算受力并更新原子位置。

原因：“以使用……进行……为例”层层嵌套；“给出位置”“一组数”不够明确。

落实说明：结合最新 H-O-H 说明改写。

**003 · CPU 代码卡标题**（已完成；建议修改）

位置：[website/src/components/HardwareArchitecture.astro:26](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/HardwareArchitecture.astro:26)

原文：准备位置，计算受力并推进轨迹

最终文案：读取原子坐标，计算受力并推进模拟

原因：“准备位置”和“推进轨迹”搭配不自然。

**004 · QPU 代码卡标题**（已完成；可选润色）

位置：[website/src/components/HardwareArchitecture.astro:38](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/HardwareArchitecture.astro:38)

原文：运行电路，得到描述分子的数值

最终文案：运行电路，提取分子特征

原因：“描述分子的数值”较绕，直接点明特征。

**005 · QPU 代码卡说明**（已完成；建议修改）

位置：[website/src/components/HardwareArchitecture.astro:46](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/HardwareArchitecture.astro:46)

原文：quantum_request 带入水分子坐标；每组坐标运行 Z、X 两种电路，测量结果整理成 14 个数。

最终文案：quantum_request 包含水分子坐标；程序为每组坐标分别运行 Z、X 两种电路，并将测量结果整理为 14 个数值特征。

原因：“每组坐标运行电路”主谓搭配不当，后半句也缺少明确主语。

**006 · GPU 代码卡说明**（已完成；可选润色）

位置：[website/src/components/HardwareArchitecture.astro:60](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/HardwareArchitecture.astro:60)

原文：features 是 QPU 测量后整理出的数；energies_eV 是模型预测的能量。

最终文案：features 是从 QPU 测量结果中提取的数值特征；energies_eV 是模型预测的能量。

原因：“测量后整理出的数”迂回，可直接说明数据含义。

**007 · 提交作业说明**（已完成；建议修改）

位置：[website/src/components/HardwareArchitecture.astro:75](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/HardwareArchitecture.astro:75)

原文：作业包含模型文件、运行配置和输出位置；提交后由 CPU 安排量子电路与 GPU 计算。

最终文案：作业指定模型文件、运行配置和输出位置；提交后，由 CPU 协调 QPU 上的电路执行和 GPU 上的计算。

原因：“安排量子电路与 GPU 计算”并列对象不齐，一个是对象，一个是动作。

**008 · 性能分析规模说明**（已完成；建议修改）

位置：[website/src/pages/index.astro:21](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/index.astro:21)

原文：支持万量子比特、千卡同步性能建模，百万条硬件指令类事件，支持多 Job 并发与资源竞争分析。

最终文案：支持万量子比特、千卡规模的同步性能建模，可模拟百万条硬件指令类事件，并分析多作业并发时的资源竞争。

原因：“百万条……事件”缺少谓语；重复“支持”，并列层次不清。数字沿用原文，不构成规模验证。

**009 · 工作流 04A 节点**（已完成；建议修改）

位置：[website/src/components/FlowWorkbench.astro:35](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/FlowWorkbench.astro:35)

原文：提交真机

最终文案：真机运行

原因：“提交真机”省略了提交对象，字面上像是在提交硬件。

**010 · 工作流 04B 节点**（已完成；建议修改）

位置：[website/src/components/FlowWorkbench.astro:41](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/FlowWorkbench.astro:41)

原文：离散事件仿真模拟器

最终文案：离散事件仿真器

原因：“仿真”与“模拟”重复。

**011 · 工作流无障碍说明**（已完成；建议修改；无障碍说明）

位置：[website/src/components/FlowWorkbench.astro:7](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/FlowWorkbench.astro:7)

原文：量子-经典混合程序选择 CPU、GPU 或 QPU 设备并编排任务后，可选择提交真机或使用离散事件仿真模拟器。两条路径汇入真机/仿真性能报告，均包含各任务运行时间、运行节点、运行指令顺序及运行复杂度。任务编排、分析与报告节点均高亮。此图为流程说明，小屏幕可横向滚动或使用左右按钮查看。

最终文案：为量子-经典混合程序选择 CPU、GPU 或 QPU 并编排任务后，可在真机上运行，也可使用离散事件仿真器评估性能。两种方式均可生成性能报告，包含各任务的运行时间、运行节点、指令执行顺序和运行复杂度。图中已突出标示任务编排、性能分析与报告节点；小屏幕可横向滚动，或使用左右按钮查看。

原因：主语悬空，“两条路径汇入报告”将图形关系写成生硬的动作；同时含前两项措辞问题。

**012 · 教程区引言**（已完成；建议修改）

位置：[website/src/pages/index.astro:29](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/index.astro:29)

原文：了解水分子的能量、受力与轨迹，再学习量子地址如何查询存储位。

最终文案：通过两个教程，了解水分子的能量、受力与运动轨迹，以及如何通过量子地址查询存储数据。

原因：两个独立示例被“再学习”写成前后步骤；“地址如何查询”主谓关系不准。

落实说明：沿用当前“教程”用词。

**013 · 量子随机存储器卡片**（已完成；建议修改）

位置：[website/src/pages/index.astro:32](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/index.astro:32)

原文：利用量子地址访问存储数据，使多个地址及对应数据保持量子叠加关联，为量子算法提供数据查询能力；本例演示理想查询过程。

最终文案：量子随机存储器通过量子地址访问数据，使处于叠加态的地址与对应数据保持关联，为量子算法提供数据查询能力。本例演示理想条件下的查询过程。

原因：“保持量子叠加关联”把不同概念压在一起，句子也过长。

### 文档总览（4 条）

页面：[http://127.0.0.1:4321/docs/](http://127.0.0.1:4321/docs/)

**014 · 系统介绍**（已完成；可选润色）

位置：[website/src/content/guide/system.md:10](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/system.md:10)

原文：PivotQ 是面向 CPU、GPU 与 QPU 协同计算的量超智融合系统，以融合编程框架为核心，配合性能模拟器与可视化工作台，支持组织计算任务、评估硬件配置和查看运行结果。

最终文案：PivotQ 是协同 CPU、GPU 与 QPU 的量超智融合系统。融合编程框架负责组织任务执行，性能模拟器用于评估硬件配置，可视化工作台用于查看运行结果。

原因：定义、组成和用途挤在一句中，拆开后各部分职责更清楚。

**015 · 系统介绍**（已完成；建议修改）

位置：[website/src/content/guide/system.md:12](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/system.md:12)

原文：首页 01 以水分子动力学模拟为例：CPU 从当前原子位置准备输入，QPU 阶段运行电路并取得测量特征，GPU 用这些特征预测势能，CPU 再求出受力、更新原子位置。

最终文案：首页“编程模型”以水分子动力学模拟为例：CPU 根据当前原子坐标准备输入，QPU 运行电路，测量结果经整理后作为 GPU 预测势能的输入；CPU 再计算受力并更新原子位置。

原因：“从位置准备输入”“取得测量特征”搭配生硬，可直接说明各设备处理的数据。

**016 · 使用文档表格／混合编程**（已完成；建议修改）

位置：[website/src/content/guide/system.md:24](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/system.md:24)

原文：连接经典任务、量子电路和数据依赖。

最终文案：连接经典任务与量子电路，并定义它们之间的数据依赖。

原因：任务、电路与依赖不是同一类对象，不适合共用“连接”。

**017 · 使用文档表格／性能建模与预测**（已完成；建议修改）

位置：[website/src/content/guide/system.md:27](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/system.md:27)

原文：描述任务工作量，比较配置下的预计耗时。

最终文案：描述任务工作量，比较不同硬件配置下的预计耗时。

原因：“比较配置下”缺少“不同”，比较对象不完整。

### 水分子动力学模拟（15 条）

页面：[http://127.0.0.1:4321/examples/aimd/](http://127.0.0.1:4321/examples/aimd/)

**018 · 问题与输入**（已完成；建议修改）

位置：[website/src/pages/examples/aimd.astro:75](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:75)

原文：归档轨迹没有提供配套的模型权重、编码配置或执行后端记录，不能确认与当前模型一致，也不能用前三段代码重现后面的能量曲线。

最终文案：最后的代码 4 会转向另一份归档的轨迹 CSV。它没有附上配套的模型权重、编码配置或执行后端记录，所以目前无法确认它是否由当前模型生成，也无法用前三段代码重现后面的能量曲线。

原因：“不能确认与当前模型一致”省略了比较对象，容易误读为轨迹本身与模型作比较。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。前句明确“它”为归档轨迹 CSV，仍保留模型来源未知和无法复现能量曲线的限制。

**019 · 构造量子电路**（已完成；可选润色）

位置：[website/src/pages/examples/aimd.astro:80](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:80)

原文：输出中的 70 个基础门和深度 39 只描述电路结构，不是一帧分子的能量。

最终文案：摘要中的基础门总数 70、电路深度 39，描述的也都是电路结构，不能表示某一帧构型的能量。

原因：“70 个基础门和深度 39”结构不平行，“一帧分子的能量”也略显生硬。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。70 与 39 仍是结构指标，未改作能量或性能指标。

**020 · 构造量子电路**（已完成；建议修改）

位置：[website/src/pages/examples/aimd.astro:80](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:80)

原文：单比特旋转改变各量子比特的状态，CZ 门使相邻比特发生条件相位作用；随后一组 Pauli 旋转按指定的比特和旋转轴继续变换量子态。

最终文案：单比特旋转先改变各量子比特的状态，CZ 门再对相邻的两个比特施加受控相位变换；随后，一组 Pauli 旋转在指定比特上沿指定轴继续变换量子态。

原因：“使比特发生条件相位作用”搭配不当，“按指定的比特”也不自然。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。受控相位与指定比特、轴的表述保留。

**021 · 构造量子电路**（已完成；建议修改）

位置：[website/src/pages/examples/aimd.astro:80](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:80)

原文：模型门结构保留便于理解的 Rx 与 Pauli 旋转，基础门分解则把它们展开为 Ry、Rz、CZ。

最终文案：两张图展示了同一电路的不同层次：“模型门结构”保留 Rx 与 Pauli 旋转，便于理解；“基础门分解”把它们展开为 Ry、Rz、CZ 门。

原因：主语实际指两幅图，原句容易被理解为“结构”和“分解”自身执行动作。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。先明确主语为两张图，再解释两层电路表示，门名保持不变。

**022 · 计算步骤**（已完成；建议修改）

位置：[website/src/pages/examples/aimd.astro:109](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:109)

原文：量子阶段接收编码角和模型参数，在 Z 基与 X 基读出中各形成 7 个统计特征，而不是直接输出原子坐标或受力。

最终文案：先代入编码角和模型参数，量子阶段就可以根据 Z 基、X 基的读出结果，各提取 7 个统计特征。这里得到的还只是特征，并不是原子坐标或受力。

原因：“在读出中形成特征”搭配生硬，改为从读出结果提取特征，计算关系更清楚。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。Z/X 各 7 个统计特征与非坐标、非受力输出的界限保留。

**023 · 计算步骤**（已完成；建议修改）

位置：[website/src/pages/examples/aimd.astro:111](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:111)

原文：一个时间步怎样接起来

最终文案：一个时间步内的计算如何衔接

原因：实际衔接的是计算步骤，“时间步接起来”缺少具体对象。

**024 · 计算步骤**（已完成；建议修改）

位置：[website/src/pages/examples/aimd.astro:120](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:120)

原文：这里的“读出特征”是对电路输出在 Z 基、X 基下取得的统计量。若在采样设备上运行，需要多次测量来估计它；理想模拟器也可直接计算期望值。

最终文案：一次测量只给出一组比特结果；这里需要的特征，则是根据电路在 Z 基、X 基下的读出结果计算的统计量。在采样设备上，要通过多次测量估计这些统计量；理想模拟器也可以直接计算期望值。

原因：“对电路输出在……下取得”语序绕，后句“它”的指代也不够直接。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。统计量的来源、采样估计与理想模拟器期望值三者均保留。

**025 · 在 CPU 上计算能量与受力**（已完成；建议修改）

位置：[website/src/pages/examples/aimd.astro:124](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:124)

原文：使用仓库已配置的 Python 环境，在 applications/h2o-hybrid-aimd/ 目录运行本单元格。

最终文案：使用仓库已配置的 Python 环境，在 applications/h2o-hybrid-aimd/ 目录运行下面这段代码：它会读取默认配置与已训练模型，算出初始水分子构型的势能和三个原子的受力。

原因：页面展示的是代码块，“运行本单元格”容易让人误以为网页提供可执行的 Notebook 单元格。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。明确为下方代码，仍要求在配置好的本地 Python 环境运行，且同段说明浏览器不执行 Python。

**026 · 在 CPU 上计算能量与受力**（已完成；建议修改）

位置：[website/src/pages/examples/aimd.astro:127](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:127)

原文：差分步长为 0.001 Å，中心构型加上 9 个坐标的正负扰动，共求值 19 个构型。

最终文案：为了求出力，程序以 0.001 Å 为差分步长，对 9 个坐标分别施加正、负扰动。这样，连同中心构型，一共需要计算 19 个构型的势能。

原因：“中心构型加上……扰动”省略了扰动后构型，“求值构型”也缺少实际求值的物理量。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。差分步长 0.001 Å、9 个坐标和 19 个构型的势能均保留。

**027 · 读一帧：先对齐结构与曲线**（已完成；可选润色）

位置：[website/src/pages/examples/aimd.astro:134](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:134)

原文：拖到 100 fs，键长分别为 1.2024 Å 和 1.1422 Å，夹角为 95.27°。

最终文案：把曲线光标拖到 100 fs，两条键长变为 1.2024 Å 和 1.1422 Å，夹角为 95.27°。

原因：“拖到”省略了操作对象；补出光标后更容易按说明操作。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。操作对象明确为曲线光标，时间与几何数值保持不变。

**028 · 总能量应当保持不变吗？**（已完成；建议修改）

位置：[website/src/pages/examples/aimd.astro:137](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:137)

原文：理想的封闭、无恒温器模拟中，总能量应大体保持。

最终文案：在理想的封闭、无恒温器模拟中，总能量应大体保持不变；恒温控制与数值积分都可能改变曲线。

原因：“保持”缺少补语，“保持不变”才表达完整。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。“保持不变”补语保留，后文仍说明归档缺少系综和积分器设置。

**029 · 轨迹与能量曲线 / 代码 4**（已完成；建议修改）

位置：[website/src/pages/examples/aimd.astro:140](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:140)

原文：用坐标复算首末两帧

最终文案：根据坐标复算首末两帧的键长和键角

原因：复算的对象是键长和键角，不能直接“复算两帧”。

**030 · 量子电路提取特征，经典模型预测势能**（已完成；建议修改）

位置：[website/src/components/AimdModelEquations.astro:38](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/AimdModelEquations.astro:38)

原文：μ_z、s_z 按分量标准化特征，μ_E、s_E 将网络输出还原为 eV，均随模型训练后固定。

最终文案：公式中，μz、sz 先按分量标准化特征，μE、sE 再把网络输出还原为以 eV 为单位的能量。这些参数在模型训练完成后保持固定。还需要记住这里的预测对象：默认训练目标是数据集中的相对势能，量子读出本身不是电子能量。

原因：“均随模型训练后固定”语法不通，“还原为 eV”将物理量写成单位。

落实说明：同期公式说明整体润色后再次核对，仍明确参数在训练后固定，输出为以 eV 为单位的能量。

**031 · 比较相邻构型的能量，求出原子受力**（已完成；可选润色）

位置：[website/src/components/AimdModelEquations.astro:43](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/AimdModelEquations.astro:43)

原文：力是势能对坐标的负梯度。当前水分子动力学模拟程序对每个原子的 x、y、z 坐标分别做正、负扰动，用中心有限差分近似它：

最终文案：现在能计算一个构型的势能了，怎样从中得到力？关键是看位置发生微小变化时，能量怎样改变：力就是势能对坐标的负梯度。当前水分子动力学模拟程序分别对每个原子的 x、y、z 坐标施加正、负扰动，比较两侧的能量，用中心有限差分近似求出受力：

原因：“它”可能回指力或梯度，直接写出计算对象更清楚。

落实说明：同期公式说明整体润色后再次核对，明确中心有限差分用于计算受力，原先含糊的“它”已移除。

**032 · 比较相邻构型的能量，求出原子受力**（已完成；建议修改）

位置：[website/src/components/AimdModelEquations.astro:50](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/AimdModelEquations.astro:50)

原文：代码随后移除平移与转动方向的数值残差，再交给 VelocityVerlet 积分器更新位置与速度。

最终文案：力算出后，代码还会移除平移与转动方向的数值残差，再把处理后的力交给 VelocityVerlet 积分器。由它更新位置与速度，便从当前构型走到了下一步。

原因：“再交给”省略了宾语，紧接“数值残差”容易读成将残差交给积分器。

落实说明：同期公式说明整体润色后再次核对，明确交给积分器的是处理后的力。

### 量子随机存储器（14 条）

页面：[http://127.0.0.1:4321/examples/qram/](http://127.0.0.1:4321/examples/qram/)

**033 · 页面标题**（已完成；建议修改）

位置：[website/src/pages/examples/qram.astro:34](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:34)

原文：地址 10 如何找到并读出数据

最终文案：如何通过地址 10 找到并读出数据

原因：地址是查询条件，原题把地址写成了执行查找、读出的主体。

**034 · 页面导言**（已完成；可选润色）

位置：[website/src/pages/examples/qram.astro:35](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:35)

原文：先沿树形路径找到地址 |10⟩，再用四个假设的存储位，看看单地址和叠加地址分别读出什么。

最终文案：假设面前有四个存储位置，每个位置都放着一个 0 或 1。现在，我们想知道地址 10 里存了什么。就从这个小问题出发：先找到位置，再把数据读出来，最后试着让地址处于叠加态，看看查询会有什么变化。

原因：实际找到的是地址对应的位置；“用四个假设的存储位”省略了数据假设的内容。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。当前第 35 行明确四个位置各含 0 或 1；第 36 行继续明确教学假设、本地 CPU 理想态矢量模拟与无真机数据。

**035 · 普通内存和量子地址**（已完成；可选润色）

位置：[website/src/pages/examples/qram.astro:45](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:45)

原文：就像从数组中读取 memory[2]，二进制地址 10 指向第三个位置；该位置保存的 0 或 1 是另一件事。

最终文案：至于地址 10 里存了什么，还得查看内容；地址负责告诉我们去哪一格，内容才是我们要取回的值。

原因：“是另一件事”指向含糊，可以直接说清地址和内容的关系。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。当前第 44 行另明确 memory[2]、第三个位置和二进制 10 的对应；第 45 行直接解释地址与内容的关系。

**036 · 普通内存和量子地址**（已完成；建议修改）

位置：[website/src/pages/examples/qram.astro:47](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:47)

原文：这里的“保留”也包括各分支之间的相对相位，称为相干。

最终文案：我们希望查询后，每个地址分支都与它对应的数据关联起来，并保留分支之间的相对相位。这就是这里所说的相干查询。

原因：“称为相干”的主语不明，容易读成把“相对相位”本身称为相干。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。“相干查询”明确指保留各地址分支的数据关联及相对相位，未把相对相位本身称为相干。

**037 · 普通内存和量子地址**（已完成；建议修改）

位置：[website/src/pages/examples/qram.astro:45](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:45)

原文：地址是位置编号，存储位是该位置的内容，二者可以不同。

最终文案：至于地址 10 里存了什么，还得查看内容；地址负责告诉我们去哪一格，内容才是我们要取回的值。为了把这两件事看清楚，这次每格只放一位数据。

原因：“二者可以不同”把编号和一位内容当成同类数值比较，且未说清不同在哪里。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。以“去哪一格”和“取回的值”分别解释地址和内容，第 35 行另明确每格保存 0 或 1。

**038 · 从两位地址开始**（已完成；建议修改）

位置：[website/src/pages/examples/qram.astro:56](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:56)

原文：一般地，n 位地址可编号 2ⁿ 个位置；这里两位地址对应 2² = 4 个存储位置。

最终文案：两位地址恰好能区分它们，因为每一位都有 0、1 两种取值，合起来就是 2² = 4 种；推广到 n 位，就能为 2ⁿ 个位置编号。

原因：“编号……个位置”搭配不顺，应为“为……个位置编号”。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。“为 2ⁿ 个位置编号”搭配正确，2² = 4 解释保留。

**039 · 沿树形结构找到位置 10**（已完成；建议修改）

位置：[website/src/pages/examples/qram.astro:94](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:94)

原文：树的第一层由地址第一位选择，第二层由第二位选择；两层分叉通向四个存储单元。

最终文案：回头看这张图，第一位决定第一层怎么走，第二位决定第二层怎么走，两层分叉就能到达四个存储单元。

原因：选择的是每层的分支，不是树的层；原句主宾语关系不准确。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。当前第 87–88 行已分别解释第一位走右侧分支、第二位走左侧分支，未重新把“层”本身作为选择对象。

**040 · 读取数据 / 小节标题**（已完成；建议修改）

位置：[website/src/pages/examples/qram.astro:102](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:102)

原文：给四个位置放入一位数据

最终文案：在四个位置各存入一位数据

原因：缺少“各”会被读成四个位置合起来只放一位数据，“给位置放入”搭配也不自然。

**041 · 给四个位置放入一位数据**（已完成；建议修改）

位置：[website/src/pages/examples/qram.astro:103](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:103)

原文：为了演算“找到位置”之后的读取，假设四个存储单元各保存一个 0 或 1。

最终文案：位置找到了，现在给这四格放上具体的内容。我们约定它们分别保存下面这些 0 或 1，作为这次讲解的存储表。

原因：“演算……之后的读取”名词叠加，动宾搭配生硬。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。按找到位置、放入具体内容的顺序讲解；标题与表注保留每个位置各存一位的假设。

**042 · 先读固定地址 10**（已完成；建议修改）

位置：[website/src/pages/examples/qram.astro:121](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:121)

原文：直接用存储值覆盖数据位会丢失它原来的值；异或则让地址 10 存 1 时，数据位 0 变 1、1 变 0。

最终文案：量子电路中的相干查询必须可逆，而直接用存储值覆盖数据位，会丢掉它原来的值。仍以地址 10 为例：数据位从 0 开始，就翻成 1；从 1 开始，就翻回 0。

原因：“异或则让……时”混合了使动句和条件句，“它”也可直接明确为数据位。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。条件与翻转结果拆成清楚的句子；“它”紧接数据位、指代明确，地址 10 的存储内容为 1 在第 117 行保留。

**043 · 再读两个地址的叠加**（已完成；可选润色）

位置：[website/src/pages/examples/qram.astro:126](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:126)

原文：量子变换具有线性，同一次理想查询会作用于两个地址分支：01 查得 0，10 查得 1。

最终文案：存储表没有变，查询规则也没有变：01 这一支查得 0，10 这一支查得 1。量子变换具有线性性质，因此对叠加态做同一次理想查询，就得到这两个分支各自变换后的叠加。

原因：“具有线性”略显生硬，“线性性质”更自然，补出因果关系也更便于教学阅读。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。线性性质及两个地址各自的查询结果、变换后的叠加均保留。

**044 · 一次测量会得到什么**（已完成；建议修改）

位置：[website/src/pages/examples/qram.astro:142](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:142)

原文：下面通过 PivotQ 用同一张四位存储表构造可逆查询电路。

最终文案：手上的存储表和查询规则已经足够写出一个小程序了。我们用 PivotQ 构造可逆查询电路；它的电路接口直接复用 Qiskit 对象，因此接着就能交给 Qiskit Statevector，计算查询后的理想量子态。

原因：“通过……用……”连续介词绕口，“四位存储表”也容易误读成地址有四位。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。四个存储位在第 150 行明示，当前句不再使用含混的“四位存储表”，也未新增真机承诺。

**045 · 一次测量会得到什么**（已完成；建议修改）

位置：[website/src/pages/examples/qram.astro:143](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:143)

原文：代码按照“准备输入、执行查询、查看状态”组织。四个函数与前面的两条式子一一对应：

最终文案：四个函数也沿着同一条思路展开：准备输入、执行查询，再查看状态。

原因：四个函数无法与两条式子“一一对应”；下方实际列出的是各函数分工。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。四个函数只描述处理步骤；前句“与公式一一对应”的主语现为程序输出的地址/数据标签，未恢复四函数与两式一一对应的错误。

**046 · 一次测量会得到什么**（已完成；可选润色）

位置：[website/src/pages/examples/qram.astro:162](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:162)

原文：这个四位置算例只解释理想查询的输入和输出，不能据此判断实际硬件性能或算法加速。

最终文案：若继续走向真实设备，还要准备存储数据、实现相干寻址，并处理噪声与读写成本。这些都超出了这张四格存储表的演示范围，因此这里的输入与输出还不能用来判断实际硬件性能或算法加速效果。

原因：“四位置算例”是生硬的压缩组合，“判断算法加速”也缺少“效果”。

落实说明：同期教程整体润色后，按当前段落核对，原问题已解决。四格演示范围和不能据此判断实际硬件性能或算法加速效果的限制均保留。

### 水分子动力学模拟工作台教程（7 条）

页面：[http://127.0.0.1:4321/docs/aimd/](http://127.0.0.1:4321/docs/aimd/)

**047 · 教程导言**（已完成；可选润色）

位置：[website/src/content/guide/aimd.md:12](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/aimd.md:12)

原文：先按文档中的“启动工作台”在本机启动 Docker 工作台，再在浏览器打开 http://127.0.0.1:8787/。

最终文案：先按照文档中“启动工作台”一节的说明，在本机启动 Docker 工作台，再在浏览器打开 http://127.0.0.1:8787/。

原因：“按……启动工作台在本机启动工作台”连续重复，补出“一节的说明”后句法更清楚。

落实说明：保留原有内联标记、链接与单位。

**048 · 3. 查看性能预测结果**（已完成；建议修改）

位置：[website/src/content/guide/aimd.md:78](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/aimd.md:78)

原文：本例水分子电路使用 3 个逻辑比特；Fake SC-36 的“36”表示教程假设的芯片容量，其吞吐为每秒 10,000 shots（同一电路重复运行并测量的次数）、每批提交时延为 1 ms。

最终文案：本例水分子电路使用 3 个逻辑比特；Fake SC-36 的“36”表示教程假设的芯片容量。预测中假设其每秒可完成 10,000 次电路运行与测量（shots），每批提交时延为 1 ms。

原因：“其吞吐为……、每批提交时延为……”句式不平行；将 shot 解释嵌入句中也更自然，仍保留预测假设边界。

落实说明：保留原有内联标记、链接与单位。

**049 · 3. 查看性能预测结果**（已完成；建议修改）

位置：[website/src/content/guide/aimd.md:78](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/aimd.md:78)

原文：经典 CPU 推理根据冻结模型的层尺寸估算工作量，采用峰值 1 TFLOPS、访存带宽 100 GB/s 的假设值；其他固定阶段沿用参考宿主开销。

最终文案：经典 CPU 推理的工作量根据冻结模型的各层规模估算，计算峰值和访存带宽分别假设为 1 TFLOPS 和 100 GB/s；其他固定阶段采用参考宿主机的开销估计。

原因：“推理根据……估算”主语不明确，“层尺寸”“参考宿主开销”也带直译和压缩痕迹。

落实说明：保留原有内联标记、链接与单位。

**050 · 4. 提交任务并查看运行状态**（已完成；建议修改）

位置：[website/src/content/guide/aimd.md:90](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/aimd.md:90)

原文：右侧会显示该任务的运行状态、实际执行方式、实测用时、完成时间步和科学验收状态。

最终文案：右侧会显示该任务的运行状态、实际执行方式、实测用时、已完成的时间步数和科学验收状态。

原因：“完成时间步”既不像字段名也不像数量表达，缺少“已”和“数”。

**051 · 图 5 替代文字**（已完成；建议修改；图片替代文字）

位置：[website/src/content/guide/aimd.md:94](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/aimd.md:94)

原文：结果中心展示任务记录、已完成的水分子动力学模拟任务、CPU 实测用时和完成时间步

最终文案：结果中心展示任务记录、已完成的水分子动力学模拟任务、CPU 实测用时和已完成的时间步数

原因：与正文及截图字段相同，“完成时间步”缺少表示数量的“数”。

落实说明：保留六张截图，仅将图 5 引用更新为另存的文案修订图，原图保留。

**052 · 图 5 左侧“任务记录”卡片说明（1600×1000；编辑区域 x=193–463、y=315–337）**（已完成；建议修改；历史截图内嵌文字）

位置：[website/src/assets/guides/aimd/05-results-center-copy-edited.png](/Users/siwei/Developer/codex_project/PivotQ/website/src/assets/guides/aimd/05-results-center-copy-edited.png)

原文：按最近提交时间排列，运行中的任务会自动更新。

最终文案：按最近提交时间排列，运行中任务的状态会自动更新。

原因：自动更新的是任务状态，原句以“任务”作主语，容易读成任务内容会被自动改动。

落实说明：使用文案修订版截图；原始截图保留，两处文字范围之外的像素完全一致。

**053 · 图 5 右侧“运行结果”统计标签（1600×1000；编辑区域 x=864–970、y=478–501）**（已完成；建议修改；历史截图内嵌文字）

位置：[website/src/assets/guides/aimd/05-results-center-copy-edited.png](/Users/siwei/Developer/codex_project/PivotQ/website/src/assets/guides/aimd/05-results-center-copy-edited.png)

原文：完成时间步

最终文案：已完成时间步数

原因：字段展示的是完成数量，“完成时间步”缺少表示完成状态和数量的词。

落实说明：使用文案修订版截图；原始截图保留，两处文字范围之外的像素完全一致。

### PivotQ（3 条）

页面：[http://127.0.0.1:4321/docs/architecture/](http://127.0.0.1:4321/docs/architecture/)

**054 · 混合计算需求**（已完成；可选润色）

位置：[website/src/content/docs/docs/architecture.mdx:45](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/architecture.mdx:45)

原文：PivotQ 围绕这些需求，提供融合编程、性能模拟和可视化工作台，将任务组织、资源配置与结果查看连接起来。

最终文案：PivotQ 围绕这些需求，提供融合编程、性能模拟和可视化工作台，支持任务组织、资源配置与结果查看。

原因：“将任务组织、资源配置与结果查看连接起来”把不同层面的功能抽象地连接在一起，意思不够直接。

**055 · 系统架构／融合编程框架**（已完成；建议修改）

位置：[website/src/content/docs/docs/architecture.mdx:60](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/architecture.mdx:60)

原文：图中的执行路径从 Python 程序进入融合编程框架。

最终文案：如图所示，Python 程序通过融合编程框架组织执行。

原因：“路径进入框架”主谓搭配生硬；直接说明程序与框架的关系。

**056 · 系统架构／性能模拟器**（已完成；建议修改）

位置：[website/src/content/docs/docs/architecture.mdx:66](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/architecture.mdx:66)

原文：应用提供阶段工作量、数据传输和硬件参数，模拟器据此估算耗时、吞吐及通信开销，用于配置比较与瓶颈分析。

最终文案：应用提供各阶段的工作量、数据传输信息和硬件参数，模拟器据此估算耗时、吞吐及通信开销，用于配置比较与瓶颈分析。

原因：“提供数据传输”缺少宾语中心语；此处提供的是传输相关信息。

### 安装 PivotQ（4 条）

页面：[http://127.0.0.1:4321/docs/installation/](http://127.0.0.1:4321/docs/installation/)

**057 · 支持环境**（已完成；建议修改）

位置：[website/src/content/docs/docs/installation.md:15](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/installation.md:15)

原文：运行 SDK 快速上手不需要下载 水分子动力学模拟的训练数据或模型。

最终文案：运行 SDK 快速上手教程中的程序，无需下载水分子动力学模拟所用的训练数据或模型。

原因：“运行快速上手”缺少“示例”，且“下载”后多了一个空格。

落实说明：遵循网站“教程”统一用词，将建议中的“快速上手示例”改为“快速上手教程中的程序”。

**058 · 使用 Docker 安装**（已完成；可选润色）

位置：[website/src/content/docs/docs/installation.md:19](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/installation.md:19)

原文：镜像地址沿用 `janusq/pivotq:latest`：

最终文案：镜像地址为 `janusq/pivotq:latest`：

原因：“沿用”依赖读者不知道的修改历史，安装说明直接给出地址即可。

**059 · QPU 适配器的可选依赖**（已完成；建议修改）

位置：[website/src/content/docs/docs/installation.md:139](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/installation.md:139)

原文：设备连接配置由 Provider 实现定义，安装本身不会连接或执行 QPU。

最终文案：设备连接配置由 Provider 实现定义；安装依赖不会连接 QPU，也不会在 QPU 上执行任务。

原因：“执行 QPU”动宾搭配错误；执行的是任务，QPU 是执行设备。

**060 · 使用整个仓库环境**（已完成；建议修改）

位置：[website/src/content/docs/docs/installation.md:150](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/installation.md:150)

原文：统一环境还包含工作台与 水分子动力学模拟应用依赖。两种安装方式都导入 `pivotq`；选择其中一种管理当前环境即可。

最终文案：统一环境还包含工作台和水分子动力学模拟应用的依赖。无论使用独立 SDK 环境还是仓库统一环境，均通过 `import pivotq` 导入；选择一种方式管理当前环境即可。

原因：有多余空格和缺少的“的”；整页介绍多种安装方式，“两种”指代不明确，且安装方式本身不会“导入”模块。

### 快速上手（2 条）

页面：[http://127.0.0.1:4321/docs/quickstart/](http://127.0.0.1:4321/docs/quickstart/)

**061 · 运行完整教程程序**（已完成；建议修改）

位置：[website/src/content/docs/docs/quickstart.mdx:28](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quickstart.mdx:28)

原文：默认不连接 QPU，任务提交与依赖调度仍完整经过 Ray。

最终文案：本例默认不连接 QPU，但任务提交与依赖调度仍由 Ray 完成。

原因：“完整经过 Ray”搭配生硬；补足本例这一主语并说明由谁完成。

**062 · 教程源码**（已完成；建议修改）

位置：[website/src/content/docs/docs/quickstart.mdx:52](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quickstart.mdx:52)

原文：下面内容在网站构建时直接读取 `packages/framework/examples/hybrid_program.py`，与仓库里的可执行教程程序保持一致。

最终文案：完整教程代码如下：

原因：“内容读取文件”主语不当；构建维护说明也打断教程，直接引出代码更清楚。

### 常见问题（5 条）

页面：[http://127.0.0.1:4321/docs/troubleshooting/](http://127.0.0.1:4321/docs/troubleshooting/)

**063 · 无法导入 pivotq**（已完成；建议修改）

位置：[website/src/content/docs/docs/troubleshooting.md:16](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/troubleshooting.md:16)

原文：仓库根统一环境使用 `uv sync --locked`。

最终文案：若使用仓库统一环境，请在仓库根目录执行 `uv sync --locked`。

原因：“仓库根统一环境”是压缩词组，目录位置与操作主体混在一起。

**064 · 文档中的教程程序在哪里**（已完成；建议修改）

位置：[website/src/content/docs/docs/troubleshooting.md:22](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/troubleshooting.md:22)

原文：快速上手页面在构建时读取这一个文件；从仓库根目录运行它。

最终文案：快速上手页面展示该文件中的代码；请在仓库根目录运行该程序。

原因：“这一个”多余，后半句突然变为祈使句且“它”指代不够清晰。

落实说明：遵循网站“教程”统一用词，将建议中的“这个示例”改为“该程序”，指向前句已明确的教程代码。

**065 · 电路被拒绝**（已完成；建议修改）

位置：[website/src/content/docs/docs/troubleshooting.md:34](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/troubleshooting.md:34)

原文：实际门集和编译能力还需符合设备适配器的约定。

最终文案：电路还需符合设备适配器支持的门集和编译要求。

原因：需满足要求的是待提交电路，原句把门集和编译能力写成了检查主体。

**066 · 第三方 Provider 的分布被拒绝**（已完成；建议修改）

位置：[website/src/content/docs/docs/troubleshooting.md:62](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/troubleshooting.md:62)

原文：真实后端返回无效结果可能意味着已执行但结果无法确认，不应直接重提。

最终文案：真实后端返回无效结果时，任务可能已经执行，只是结果无法确认；此时不应直接重新提交任务。

原因：“已执行”缺少主语，“重提”过于口语化，也不够明确。

**067 · 性能模拟器无法加载**（已完成；建议修改）

位置：[website/src/content/docs/docs/troubleshooting.md:66](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/troubleshooting.md:66)

原文：先调用 `Predictor().availability()` 查看环境，再核对 Linux x86-64 与兼容运行库。

最终文案：先调用 `Predictor().availability()` 查看环境，再检查系统是否为 Linux x86-64、所需运行库是否兼容。

原因：“核对 Linux x86-64 与兼容运行库”省略了检查对象及判断条件。

### 经典任务（2 条）

页面：[http://127.0.0.1:4321/docs/classical-tasks/](http://127.0.0.1:4321/docs/classical-tasks/)

**068 · 连接任务**（已完成；建议修改）

位置：[website/src/content/docs/docs/classical-tasks.md:25](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/classical-tasks.md:25)

原文：将前一步引用作为后一步输入，运行时会解析依赖后再调用函数。

最终文案：将前一步的结果引用作为后一步的输入，运行时会先解析依赖，再调用函数。

原因：“会解析依赖后再”句式杂糅；补足“结果引用”也使前后步骤的关系更明确。

**069 · CPU 资源与执行器**（已完成；可选润色）

位置：[website/src/content/docs/docs/classical-tasks.md:47](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/classical-tasks.md:47)

原文：使用 Ray 时，driver 与 worker 需要相同的 `pivotq` 安装及应用依赖。

最终文案：使用 Ray 时，driver 与 worker 需要安装相同版本的 `pivotq` 和应用依赖。

原因：“需要相同的安装”搭配不自然，可直接说明环境版本须一致。

### GPU 与异构资源（6 条）

页面：[http://127.0.0.1:4321/docs/gpu-computing/](http://127.0.0.1:4321/docs/gpu-computing/)

**070 · 页首介绍**（已完成；建议修改）

位置：[website/src/content/docs/docs/gpu-computing.md:6](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/gpu-computing.md:6)

原文：应用代码负责在分配到的 GPU 上运行 CUDA、模型推理或其他加速算法。

最终文案：应用代码负责使用 CUDA 等工具，在分配到的 GPU 上运行模型推理或其他加速算法。

原因：CUDA 是技术平台，与模型推理、算法不能作为同一类运行对象并列。

**071 · 标题**（已完成；可选润色）

位置：[website/src/content/docs/docs/gpu-computing.md:8](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/gpu-computing.md:8)

原文：## 选择接入入口

最终文案：## 选择接入方式

原因：“接入入口”语义重复，“接入方式”更自然。

**072 · 选择接入入口／入口表格**（已完成；建议修改）

位置：[website/src/content/docs/docs/gpu-computing.md:13](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/gpu-computing.md:13)

原文：需要应用部署对应的软件与硬件环境。

最终文案：运行应用前，需部署所需的软件与硬件环境。

原因：原句容易读成“应用负责部署环境”，应明确这是运行应用前的准备工作。

**073 · GPU 组件如何执行**（已完成；建议修改）

位置：[website/src/content/docs/docs/gpu-computing.md:37](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/gpu-computing.md:37)

原文：`num_gpus=1` 负责预约 GPU 资源；组件本身仍需显式创建 CUDA 张量并执行 GPU 算法。

最终文案：`num_gpus=1` 用于申请 GPU 资源；组件本身仍需显式创建 CUDA 张量并执行 GPU 算法。

原因：配置值“负责预约”拟人且不够准确；资源声明用“用于申请”更自然。

**074 · GPU 组件如何执行**（已完成；建议修改）

位置：[website/src/content/docs/docs/gpu-computing.md:41](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/gpu-computing.md:41)

原文：应通过执行记录中的设备名称、CUDA 可用性与分配资源确认实际 GPU 执行，不能仅凭任务名称或目标配置认定已经使用 GPU。

最终文案：应根据执行记录中的设备名称、CUDA 可用性和资源分配情况，确认任务是否实际在 GPU 上执行；不能仅凭任务名称或目标配置认定已经使用 GPU。

原因：“确认实际 GPU 执行”缺少明确宾语，“分配资源”也宜明确为记录中的资源分配情况。

**075 · 目标配置与实际执行**（已完成；建议修改）

位置：[website/src/content/docs/docs/gpu-computing.md:64](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/gpu-computing.md:64)

原文：历史 GPU 运行结果按其原始记录保留；目标硬件的预测耗时与不同后端的实测耗时不能直接计算为预测误差。

最终文案：历史 GPU 运行结果按其原始记录保留；不能直接将目标硬件的预测耗时与其他后端实测耗时之间的差异视为预测误差。

原因：“两种耗时计算为误差”搭配不成立；需要明确不能把不同后端间的耗时差异当成预测误差。

### 量子后端（6 条）

页面：[http://127.0.0.1:4321/docs/quantum-backends/](http://127.0.0.1:4321/docs/quantum-backends/)

**076 · 选择后端**（已完成；建议修改）

位置：[website/src/content/docs/docs/quantum-backends.md:31](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quantum-backends.md:31)

原文：状态向量内存随比特数指数增长；增加 `max_qubits` 不会增加可用内存。

最终文案：存储状态向量所需的内存随量子比特数呈指数增长；增加 `max_qubits` 不会增加可用内存。

原因：“状态向量内存”“随比特数指数增长”省略过多，补足关系后更顺畅。

**077 · 支持的电路**（已完成；建议修改）

位置：[website/src/content/docs/docs/quantum-backends.md:35](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quantum-backends.md:35)

原文：提交已绑定参数的 `QuantumCircuit`，或一个最终返回此对象的任务引用。

最终文案：可以提交已绑定参数的 `QuantumCircuit`，也可以提交上游任务的结果引用；该任务的返回值须为已绑定参数的 `QuantumCircuit`。

原因：返回电路对象的是任务，并非“任务引用”；需理清任务、返回值与引用的关系。

**078 · 测量与位序**（已完成；可选润色）

位置：[website/src/content/docs/docs/quantum-backends.md:47](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quantum-backends.md:47)

原文：测量置换保持原语义：若 `q0=1, q1=0`，同时 `measure(0, 1)`、`measure(1, 0)`，返回 `"10"`。

最终文案：测量置换保留原有映射：若 `q0=1, q1=0`，并调用 `measure(0, 1)` 和 `measure(1, 0)`，则返回 `"10"`。

原因：“同时”后直接接代码缺少动词；“原语义”也不如“原有映射”具体。

**079 · 接入 QPU 后端**（已完成；建议修改）

位置：[website/src/content/docs/docs/quantum-backends.md:65](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quantum-backends.md:65)

原文：不同测量基需要用户先在电路中加入相应基变换。

最终文案：若需在不同测量基下测量，用户须先在电路中加入相应的基变换。

原因：“测量基需要用户”主谓关系生硬，应说明用户选择测量基时需要做什么。

**080 · 结果来源与失败**（已完成；建议修改）

位置：[website/src/content/docs/docs/quantum-backends.md:69](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quantum-backends.md:69)

原文：`simulator` 返回采样计数和计数归一化概率。

最终文案：`simulator` 返回采样计数，以及对计数归一化后得到的概率。

原因：“计数归一化概率”把操作和结果压成了名词串，不易读。

**081 · 结果来源与失败**（已完成；建议修改）

位置：[website/src/content/docs/docs/quantum-backends.md:71](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quantum-backends.md:71)

原文：若报错表示任务状态未知，SDK 不会自动重试；任务可能仍在设备执行，需保留作业标识并核实状态后再决定下一步。

最终文案：若报错表示任务状态未知，SDK 不会自动重试；任务可能仍在设备上执行，需保留作业标识，核实状态后再决定下一步。

原因：“在设备执行”缺少方位词“上”；调整后半句停顿，避免“并……后再”的拥挤句式。

### 编写混合程序（2 条）

页面：[http://127.0.0.1:4321/docs/hybrid-programs/](http://127.0.0.1:4321/docs/hybrid-programs/)

**082 · 一个程序，两类调用**（已完成；建议修改）

位置：[website/src/content/docs/docs/hybrid-programs.md:8](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/hybrid-programs.md:8)

原文：两者返回的引用都由同一个 `runtime.get()` 取回，也可以继续传给下游任务。

最终文案：两者都返回结果引用；使用同一个 `runtime.get()` 即可取回对应结果，也可以将这些引用继续传给下游任务。

原因：get() 取回的是引用对应的结果，原句把“引用”写成了取回对象。

**083 · 循环与参数更新**（已完成；建议修改）

位置：[website/src/content/docs/docs/hybrid-programs.md:37](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/hybrid-programs.md:37)

原文：驱动程序可以读取结果，判断下一步参数后再次提交任务。

最终文案：驱动程序可以读取结果，根据结果确定下一轮参数，再次提交任务。

原因：“判断参数”动宾搭配不当，此处应为根据结果确定参数。

### 组件与 Actor（1 条）

页面：[http://127.0.0.1:4321/docs/components-actors/](http://127.0.0.1:4321/docs/components-actors/)

**084 · CPU 配额与生命周期**（已完成；可选润色）

位置：[website/src/content/docs/docs/components-actors.md:57](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/components-actors.md:57)

原文：超时表示软件侧停止等待或报告失败，不证明外部设备工作已经停止。

最终文案：超时表示软件侧停止等待或报告失败，并不意味着外部设备上的任务已经停止。

原因：“外部设备工作”对象不明确，“不证明”也比“不意味着”生硬；宜直接说明设备上的任务。

### 可复用工作流（4 条）

页面：[http://127.0.0.1:4321/docs/workflows/](http://127.0.0.1:4321/docs/workflows/)

**085 · 页面摘要**（已完成；建议修改；页面元描述）

位置：[website/src/content/docs/docs/workflows.mdx:3](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/workflows.mdx:3)

原文：先定义 CPU 与量子任务依赖，再为不同输入和后端执行同一个工作流。

最终文案：先定义 CPU 与量子任务的依赖，再使用不同的输入和后端运行同一个工作流。

原因：“为输入和后端执行工作流”介词搭配不当，应为“使用……运行”。

**086 · 完整教程**（已完成；建议修改）

位置：[website/src/content/docs/docs/workflows.mdx:42](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/workflows.mdx:42)

原文：源码在构建时直接读取被测试的 Python 文件：

最终文案：完整教程代码如下：

原因：“源码读取文件”主谓搭配不当；“被测试的文件”也是维护口吻，正文直接引出完整代码即可。

**087 · 复用、失败与释放**（已完成；建议修改）

位置：[website/src/content/docs/docs/workflows.mdx:50](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/workflows.mdx:50)

原文：执行系统在实际提交过程中仍可能故障；如果部分节点已被接收，`WorkflowSubmissionError.partial_run` 保留这些引用，不能假定整图未执行后重新提交。

最终文案：执行系统在实际提交过程中仍可能发生故障；如果部分节点已被接收，`WorkflowSubmissionError.partial_run` 会保留这些节点的引用。此时不能假定整个工作流都未执行，并据此重新提交。

原因：“可能故障”缺少谓语成分，“假定……后重新提交”关系绕口；拆句并补明引用的对象。

**088 · 复用、失败与释放**（已完成；可选润色）

位置：[website/src/content/docs/docs/workflows.mdx:54](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/workflows.mdx:54)

原文：算法的 `for`、`while` 与结果相关分支继续写在普通 Python 中。

最终文案：算法中的 `for`、`while` 循环，以及依赖结果的条件分支，仍用普通 Python 编写。

原因：原句把关键字与分支直接并列，“结果相关分支”压缩过度。

### 集群作业（3 条）

页面：[http://127.0.0.1:4321/docs/jobs/](http://127.0.0.1:4321/docs/jobs/)

**089 · 页面摘要**（已完成；建议修改；页面元描述）

位置：[website/src/content/docs/docs/jobs.md:3](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/jobs.md:3)

原文：通过 Ray Jobs 提交完整 Python 程序，查看状态、日志和停止作业。

最终文案：通过 Ray Jobs 提交完整 Python 程序，查看作业状态与日志，并停止作业。

原因：“查看”不能支配“停止作业”；并列的是查看与停止两个动作。

**090 · 提交程序**（已完成；可选润色）

位置：[website/src/content/docs/docs/jobs.md:28](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/jobs.md:28)

原文：`entrypoint` 是参数列表，SDK 负责正确引用参数，不需要拼接 shell 字符串。

最终文案：`entrypoint` 是参数列表，SDK 负责按 shell 规则为参数添加引号，无需手动拼接 shell 字符串。

原因：“引用参数”易理解为使用或指向参数，此处表达的是 shell 参数的引号处理。

**091 · 查询与管理**（已完成；建议修改）

位置：[website/src/content/docs/docs/jobs.md:59](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/jobs.md:59)

原文：提交故障抛出 `JobSubmissionError`，其中 `framework_job_id` 保留提交标识。若结果是未知状态，先按该标识查询，SDK 不会自动重复提交。

最终文案：提交出错时会抛出 `JobSubmissionError`，其中 `framework_job_id` 保留提交标识。若无法确认提交结果，请先按该标识查询状态；SDK 不会自动重复提交。

原因：“提交故障抛出”缺少“时”，“结果是未知状态”表意绕口；也需明确查询的是状态。

### 状态与执行报告（4 条）

页面：[http://127.0.0.1:4321/docs/observability/](http://127.0.0.1:4321/docs/observability/)

**092 · 等待与状态**（已完成；建议修改）

位置：[website/src/content/docs/docs/observability.md:15](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/observability.md:15)

原文：`wait()` 返回已结束与尚未结束的引用；已结束可能成功，也可能失败。

最终文案：`wait()` 返回已结束任务和尚未结束任务的引用；已结束的任务可能成功，也可能失败。

原因：结束、成功或失败的是任务，原句省略任务后易被理解为引用自身的状态变化。

**093 · 解释耗时**（已完成；建议修改）

位置：[website/src/content/docs/docs/observability.md:40](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/observability.md:40)

原文：工作流节点可能并行，逐项累加不一定等于整段程序耗时。

最终文案：工作流节点可能并行，因此各节点的耗时之和不一定等于整段程序的耗时。

原因：“逐项累加”没有说明累加的对象；直接说明各节点耗时之和更清楚。

**094 · 解释耗时**（已完成；建议修改）

位置：[website/src/content/docs/docs/observability.md:42](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/observability.md:42)

原文：[性能预测](../performance/)给出目标硬件模型上的估计；执行报告记录此次实际后端运行。

最终文案：[性能预测](../performance/)给出基于目标硬件模型的耗时估计；执行报告记录本次在实际后端上的运行情况。

原因：“模型上的估计”“此次实际后端运行”关系压缩，补足估计与记录的对象。

**095 · 查看资源**（已完成；建议修改）

位置：[website/src/content/docs/docs/observability.md:46](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/observability.md:46)

原文：它不是剩余空闲容量，也不会探测量子设备健康状态。

最终文案：其中的 CPU 总容量不代表当前空闲容量；该接口也不会探测量子设备的健康状态。

原因：“它”在前半句指返回的容量，在后半句又指接口，主语发生了不明显的切换。

### 硬件性能模型（3 条）

页面：[http://127.0.0.1:4321/docs/hardware-profiles/](http://127.0.0.1:4321/docs/hardware-profiles/)

**096 · CPU 与 QPU**（已完成；建议修改）

位置：[website/src/content/docs/docs/hardware-profiles.md:37](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/hardware-profiles.md:37)

原文：`memory_bandwidth_gbps_per_node` 的 Gb/s 是十亿**比特**每秒；例如 1 GB 数据量在 1 Gb/s 下的理想传输项为 8 秒。

最终文案：`memory_bandwidth_gbps_per_node` 的 Gb/s 表示十亿**比特**每秒；例如，以 1 Gb/s 的带宽传输 1 GB 数据，理想传输耗时为 8 秒。

原因：“理想传输项”未说清是公式项还是耗时；补明传输量、带宽和耗时的关系。

**097 · CPU 与 QPU**（已完成；建议修改）

位置：[website/src/content/docs/docs/hardware-profiles.md:37](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/hardware-profiles.md:37)

原文：按运算量/内存量计算的 CPU 模型还包含当前引擎固有的 20 微秒开销；显式 duration 使用用户给定的时间。

最终文案：按运算量/内存量计算的 CPU 模型还包含当前引擎固有的 20 微秒开销；显式指定 duration 时，使用用户给定的耗时。

原因：“显式 duration 使用”缺少动作，主语也不明确。

**098 · 保存与比较**（已完成；建议修改）

位置：[website/src/content/docs/docs/hardware-profiles.md:57](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/hardware-profiles.md:57)

原文：更快的预测不证明两个应用具有相同的科学精度，详见[性能预测](../performance/)。

最终文案：预测耗时更短，并不能证明两个应用具有相同的科学精度，详见[性能预测](../performance/)。

原因：“更快的预测”容易被理解为预测器运行得更快，应指预测出的应用耗时更短。

### 性能预测（5 条）

页面：[http://127.0.0.1:4321/docs/performance/](http://127.0.0.1:4321/docs/performance/)

**099 · 导语**（已完成；建议修改）

位置：[website/src/content/docs/docs/performance.mdx:10](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/performance.mdx:10)

原文：预测不会执行用户的 Python 算法或量子设备，也不会自动从任意程序推导运算量。

最终文案：预测过程不会运行用户的 Python 算法或调用量子设备，也不会自动从任意程序推导运算量。

原因：“执行量子设备”动宾搭配不当。

**100 · 运行与对比**（已完成；建议修改）

位置：[website/src/content/docs/docs/performance.mdx:38](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/performance.mdx:38)

原文：保留目录包含源模型、模拟器输入、原始 CSV 和 `prediction.json`。

最终文案：指定的输出目录中会保留源模型、模拟器输入、原始 CSV 和 `prediction.json`。

原因：“保留目录”不是前文定义的概念，应接续前文的“输出目录”。

**101 · 运行与对比**（已完成；建议修改）

位置：[website/src/content/docs/docs/performance.mdx:40](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/performance.mdx:40)

原文：`PredictionResult` 包括时延、吞吐、阶段耗时、通信信息、参数来源、验证范围、引擎版本和模型与模拟器哈希。

最终文案：`PredictionResult` 包括时延、吞吐、阶段耗时、通信信息、参数来源、验证范围、引擎版本，以及模型和模拟器的哈希值。

原因：末尾“和模型与模拟器哈希”并列层次不清，缺少“的”和“值”。

**102 · 原生运行环境**（已完成；建议修改）

位置：[website/src/content/docs/docs/performance.mdx:44](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/performance.mdx:44)

原文：当前直接运行目标是 Linux x86-64、Ubuntu 24.04 兼容环境。

最终文案：目前可直接运行于 Linux x86-64 平台上与 Ubuntu 24.04 兼容的环境。

原因：“直接运行目标”像直译，且平台架构与系统环境被写成并列项。

**103 · 完整对比教程**（已完成；建议修改）

位置：[website/src/content/docs/docs/performance.mdx:60](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/performance.mdx:60)

原文：源码与测试使用同一文件：

最终文案：完整教程代码如下：

原因：原句带有内部维护口吻，也容易被理解为示例代码和测试代码写在同一文件；直接引出示例更清楚。

### 扩展量子后端（5 条）

页面：[http://127.0.0.1:4321/docs/providers/](http://127.0.0.1:4321/docs/providers/)

**104 · 注册与创建**（已完成；建议修改）

位置：[website/src/content/docs/docs/providers.mdx:24](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/providers.mdx:24)

原文：注册与创建后端均不构造该类，也不连接设备；factory 在执行进程中首次调用时构造实例。

最终文案：注册与创建后端时均不会创建 `MyProvider` 实例，也不会连接设备；执行进程首次调用工厂函数时才创建实例。

原因：构造的是实例而非类；“factory 在……首次调用时”主被动关系不清。

**105 · 结果校验与故障**（已完成；建议修改）

位置：[website/src/content/docs/docs/providers.mdx:48](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/providers.mdx:48)

原文：确认未提交的输入问题使用 `pivotq.errors.ValidationError`；已可能执行但响应丢失时使用 `ResultUnknownError` 并保留设备作业标识。

最终文案：确认请求尚未提交时，输入问题使用 `pivotq.errors.ValidationError`；请求可能已经执行但响应丢失时，使用 `ResultUnknownError` 并保留设备作业标识。

原因：“确认未提交的输入问题”修饰关系不清，“已可能执行”的语序也不自然。

**106 · 结果校验与故障**（已完成；建议修改）

位置：[website/src/content/docs/docs/providers.mdx:48](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/providers.mdx:48)

原文：真实 Provider 的未分类异常或无效结果也按执行状态未知处理，沿后续 CPU 依赖保留核实信息。

最终文案：真实设备 Provider 的未分类异常或无效结果也按“执行状态未知”处理；供核实的信息会随依赖关系传递给后续 CPU 任务。

原因：“沿……依赖保留信息”动作关系不明确，应说明信息随依赖向后续任务传递。

**107 · Task 与 Actor**（已完成；可选润色）

位置：[website/src/content/docs/docs/providers.mdx:52](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/providers.mdx:52)

原文：模拟 Provider 默认使用 Task，每次构造和关闭实例，申请 1 CPU；可设置 `execution="actor"` 保留状态，默认串行。

最终文案：模拟 Provider 默认使用 Task，每次调用都会创建并关闭实例，申请 1 CPU；可设置 `execution="actor"` 保留状态，默认串行。

原因：“每次”缺少所指事件，补明是每次调用。

**108 · 可运行的离线扩展教程**（已完成；建议修改）

位置：[website/src/content/docs/docs/providers.mdx:65](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/providers.mdx:65)

原文：源码与测试使用同一文件：

最终文案：完整教程代码如下：

原因：原句带有内部维护口吻，也容易被理解为示例代码和测试代码写在同一文件；直接引出示例更清楚。

### 运行时与结果引用（2 条）

页面：[http://127.0.0.1:4321/docs/api/runtime/](http://127.0.0.1:4321/docs/api/runtime/)

**109 · Runtime 参数表**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/runtime.md:24](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/runtime.md:24)

原文：是否保留完成调用的执行记录，默认关闭

最终文案：是否保留已完成调用的执行记录，默认关闭

原因：“完成调用”易被读成动宾短语；此处应修饰“调用”。

**110 · wait**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/runtime.md:59](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/runtime.md:59)

原文：超时可以返回不足目标数量的 ready，不取消任务，也不取回业务值。

最终文案：超时后，`ready` 中的引用数可能少于 `num_returns`；此操作不会取消任务，也不会取回业务值。

原因：“不足目标数量的 ready”不明确是元组还是引用数量；补明数量关系。

### 组件与 Actor（1 条）

页面：[http://127.0.0.1:4321/docs/api/components/](http://127.0.0.1:4321/docs/api/components/)

**111 · register**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/components.md:37](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/components.md:37)

原文：注册时不构造业务实例；实例提供 `close()` 时由框架清理调用。

最终文案：注册时不构造业务实例；若实例提供 `close()`，框架会在清理时调用该方法。

原因：“由框架清理调用”缺少必要的连接成分，不能明确何时调用。

### 工作流（2 条）

页面：[http://127.0.0.1:4321/docs/api/workflows/](http://127.0.0.1:4321/docs/api/workflows/)

**112 · Workflow**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/workflows.md:18](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/workflows.md:18)

原文：添加节点时保存普通字面参数的副本；节点只引用已声明输入和较早节点，从构建过程保证无环。

最终文案：添加节点时会保存普通字面参数的副本；节点只能引用已声明的输入和此前添加的节点，从而在构建过程中保证图无环。

原因：“较早节点”“从构建过程保证无环”表达生硬，缺少时间范围与连接词。

**113 · Workflow**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/workflows.md:18](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/workflows.md:18)

原文：首次通过校验的提交冻结图结构，后续仍可重复运行。

最终文案：首次提交通过校验后，图结构即被冻结，但工作流仍可重复运行。

原因：“提交冻结图结构”主谓关系生硬；后半句补明重复运行的对象。

### 量子后端与结果（2 条）

页面：[http://127.0.0.1:4321/docs/api/quantum/](http://127.0.0.1:4321/docs/api/quantum/)

**114 · quantum_backend**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/quantum.md:48](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/quantum.md:48)

原文：`config` 传给对应 Provider 工厂，必须可序列化且符合其构造参数。

最终文案：`config` 传给对应的 Provider 工厂，必须可序列化，并符合 Provider 构造函数的参数要求。

原因：“配置符合构造参数”搭配不完整；“其”所指也不够明确。

**115 · QuantumResult**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/quantum.md:85](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/quantum.md:85)

原文：模拟器返回采样计数和频率，有限次采样不保证等于理想概率。

最终文案：模拟器返回采样计数和频率；有限次采样得到的频率不保证等于理想概率。

原因：能与概率比较的是采样频率，而不是“采样”这一过程。

### Provider 协议（4 条）

页面：[http://127.0.0.1:4321/docs/api/providers/](http://127.0.0.1:4321/docs/api/providers/)

**116 · 导语**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/providers.md:12](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/providers.md:12)

原文：Provider 将设备编译、连接和结果读取封装为同步接口，供 PivotQ 调度。

最终文案：Provider 将面向设备的电路编译、设备连接和结果读取封装为同步接口，供 PivotQ 调度。

原因：“设备编译”容易理解成编译设备；三个并列动作的对象不明确。

**117 · BackendCapabilities**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/providers.md:38](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/providers.md:38)

原文：该声明用于提交前校验，不构成设备在线状态。

最终文案：该声明用于提交前校验，并不表示设备当前在线。

原因：“声明不构成状态”动宾搭配不当，应表达能力声明不能证明在线。

**118 · ProviderResult**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/providers.md:61](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/providers.md:61)

原文：`metadata` 为可序列化字典，每个实例默认独立空字典。

最终文案：`metadata` 为可序列化字典，每个实例默认使用独立的空字典。

原因：后半句缺少谓语“使用”。

**119 · QuantumProvider**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/providers.md:70](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/providers.md:70)

原文：已知失败使用 `pivotq.errors` 的结构化异常；设备可能已接受任务后发生的不确定失败，应抛出 `ResultUnknownError` 并保留设备作业标识。

最终文案：已知失败使用 `pivotq.errors` 中的结构化异常；如果设备可能已接受任务，但执行结果无法确定，应抛出 `ResultUnknownError` 并保留设备作业标识。

原因：“设备可能已接受任务后发生的不确定失败”修饰层次过多，难以直接理解触发条件。

### 集群作业（1 条）

页面：[http://127.0.0.1:4321/docs/api/jobs/](http://127.0.0.1:4321/docs/api/jobs/)

**120 · 导语**（已完成；可选润色）

位置：[website/src/content/docs/docs/api/jobs.md:10](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/jobs.md:10)

原文：作业管理提交整个 Python 程序，由程序内部的 Runtime 调度各项任务。

最终文案：通过作业管理接口提交整个 Python 程序，再由程序内部的 Runtime 调度各项任务。

原因：“作业管理提交”把功能名直接作为执行动作的主体，表达略生硬。

### 执行报告（5 条）

页面：[http://127.0.0.1:4321/docs/api/observability/](http://127.0.0.1:4321/docs/api/observability/)

**121 · 导语**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/observability.md:10](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/observability.md:10)

原文：通过 `Runtime(executor="ray", trace=True)` 启用有界追踪，`trace_max_records` 控制最多保留的完成记录数。

最终文案：通过 `Runtime(executor="ray", trace=True)` 启用有界追踪，`trace_max_records` 控制最多保留多少条已完成调用的记录。

原因：“完成记录”指代不完整，应明确记录的是已完成调用。

**122 · report**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/observability.md:30](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/observability.md:30)

原文：读取已保留的完成调用快照，释放结果或关闭 Runtime 后仍可调用。

最终文案：读取已完成调用的记录快照，其中仅包含保留范围内的记录；释放结果或关闭 Runtime 后仍可调用此接口。

原因：“已保留的完成调用快照”多重修饰不顺，后半句缺少可调用的对象。

**123 · ExecutionReport 属性表**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/observability.md:38](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/observability.md:38)

原文：完成调用记录元组，包含任务、依赖、CPU 配额、后端、耗时与错误

最终文案：已完成调用的记录元组，包含任务、依赖、CPU 配额、后端、耗时与错误

原因：“完成调用记录”易误读为动作，补“已”和“的”明确修饰关系。

**124 · ExecutionReport**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/observability.md:42](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/observability.md:42)

原文：记录中的 `observation_delay_seconds` 包括结果完成到 Driver 观测之间的延迟，不是网络传输耗时。

最终文案：记录中的 `observation_delay_seconds` 包括从结果就绪到 Driver 观测到结果之间的延迟，不是网络传输耗时。

原因：“结果完成”搭配生硬，“Driver 观测”也缺少宾语。

**125 · export**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/observability.md:58](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/observability.md:58)

原文：目标父目录需已存在；同名文件会覆盖。

最终文案：目标父目录需已存在；同名文件会被覆盖。

原因：覆盖对象应使用被动句，否则像是同名文件去覆盖其他内容。

### 性能模型与预测（2 条）

页面：[http://127.0.0.1:4321/docs/api/performance/](http://127.0.0.1:4321/docs/api/performance/)

**126 · Workload / cpu**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/performance.md:33](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/performance.md:33)

原文：提供正的显式耗时，或提供操作量与访存字节数模型。

最终文案：指定大于 0 的耗时，或根据操作量与访存字节数建模。

原因：“提供……字节数模型”把参数值和模型混为一层，句式生硬。

**127 · Workload / qpu**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/performance.md:43](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/performance.md:43)

原文：根据电路数、shots、有效 shot 吞吐与提交延迟预测量子阶段。

最终文案：根据电路数、shots、有效 shot 吞吐与提交延迟预测量子阶段的耗时。

原因：“预测量子阶段”缺少被预测的具体量。

### 异常类型（4 条）

页面：[http://127.0.0.1:4321/docs/api/errors/](http://127.0.0.1:4321/docs/api/errors/)

**128 · PivotQError**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/errors.md:16](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/errors.md:16)

原文：执行失败通过 `runtime.get(ref)` 抛出。

最终文案：任务执行失败时，`runtime.get(ref)` 会抛出相应异常。

原因：被“抛出”的是异常，而非“执行失败”。

**129 · 执行错误表**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/errors.md:25](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/errors.md:25)

原文：Runtime 已关闭，或任务接受前后端不可用

最终文案：Runtime 已关闭，或后端在接受任务前不可用

原因：“任务接受前后端”容易误切分成“任务接受前后”，语序不清。

**130 · 执行错误**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/errors.md:32](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/errors.md:32)

原文：跨 Runtime、释放后的引用及关闭后的新提交不可继续使用，生命周期见[运行时接口](../runtime/)。

最终文案：不能跨 Runtime 使用引用，不能使用已释放的引用，也不能在 Runtime 关闭后提交新任务；生命周期见[运行时接口](../runtime/)。

原因：“跨 Runtime”“引用”“新提交”并列层级不一致，“新提交不可继续使用”含义不清。

**131 · 提交状态与重试建议**（已完成；建议修改）

位置：[website/src/content/docs/docs/api/errors.md:40](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/errors.md:40)

原文：量子设备可能已接受请求后的失败，需要先用请求和作业标识核实状态。

最终文案：如果发生故障时量子设备可能已经接受请求，需要先用请求和作业标识核实状态。

原因：“可能已接受请求后的失败”修饰关系绕口，条件与动作不清。

### 应用教程介绍（1 条）

页面：[http://127.0.0.1:4321/docs/examples/](http://127.0.0.1:4321/docs/examples/)

**132 · 最小混合程序**（已完成；建议修改）

位置：[website/src/content/docs/docs/examples.md:8](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/examples.md:8)

原文：它不依赖水分子应用，用经典任务生成电路、模拟器执行采样，再由经典任务分析结果。

最终文案：它不依赖水分子应用：先由经典任务生成电路，再由模拟器执行采样，最后由经典任务分析结果。

原因：“用经典任务生成电路、模拟器执行采样”混合两种句式，第二个分句缺少介词。

### 404 页面（1 条）

页面：[http://127.0.0.1:4321/404/](http://127.0.0.1:4321/404/)

**133 · 错误页标题**（已完成；建议修改）

位置：[website/src/pages/404.astro:6](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/404.astro:6)

原文：这个页面还没有连接。

最终文案：未找到该页面。

原因：“页面没有连接”不符合中文习惯，也无法准确说明 404 状态。

### 全站页面摘要（1 条）

**134 · 搜索／分享摘要**（已完成；建议修改；页面元描述）

位置：[website/src/data/site.ts:4](/Users/siwei/Developer/codex_project/PivotQ/website/src/data/site.ts:4)

原文：PivotQ 量超智融合系统：协同 CPU、GPU 与 QPU，由用户指定计算资源和任务依赖，组织执行、评估性能并查看结果。

最终文案：PivotQ 是协同 CPU、GPU 与 QPU 的量超智融合系统。用户指定计算资源和任务依赖后，可组织任务执行、评估性能并查看结果。

原因：连续更换主语，“组织执行”缺少宾语。

## 页面覆盖表

| 页面 | 已落实条数 | 检查结果 |
| --- | ---: | --- |
| [首页](http://127.0.0.1:4321/) | 13 | 已审读，条目全部落实，页面文本核验通过 |
| [文档总览](http://127.0.0.1:4321/docs/) | 4 | 已审读，条目全部落实，页面文本核验通过 |
| [水分子动力学模拟](http://127.0.0.1:4321/examples/aimd/) | 15 | 已审读，条目全部落实，页面文本核验通过 |
| [量子随机存储器](http://127.0.0.1:4321/examples/qram/) | 14 | 已审读，条目全部落实，页面文本核验通过 |
| [水分子动力学模拟工作台教程](http://127.0.0.1:4321/docs/aimd/) | 7 | 已审读，条目全部落实，页面文本核验通过 |
| [PivotQ](http://127.0.0.1:4321/docs/architecture/) | 3 | 已审读，条目全部落实，页面文本核验通过 |
| [安装 PivotQ](http://127.0.0.1:4321/docs/installation/) | 4 | 已审读，条目全部落实，页面文本核验通过 |
| [快速上手](http://127.0.0.1:4321/docs/quickstart/) | 2 | 已审读，条目全部落实，页面文本核验通过 |
| [常见问题](http://127.0.0.1:4321/docs/troubleshooting/) | 5 | 已审读，条目全部落实，页面文本核验通过 |
| [经典任务](http://127.0.0.1:4321/docs/classical-tasks/) | 2 | 已审读，条目全部落实，页面文本核验通过 |
| [GPU 与异构资源](http://127.0.0.1:4321/docs/gpu-computing/) | 6 | 已审读，条目全部落实，页面文本核验通过 |
| [量子后端](http://127.0.0.1:4321/docs/quantum-backends/) | 6 | 已审读，条目全部落实，页面文本核验通过 |
| [编写混合程序](http://127.0.0.1:4321/docs/hybrid-programs/) | 2 | 已审读，条目全部落实，页面文本核验通过 |
| [组件与 Actor](http://127.0.0.1:4321/docs/components-actors/) | 1 | 已审读，条目全部落实，页面文本核验通过 |
| [可复用工作流](http://127.0.0.1:4321/docs/workflows/) | 4 | 已审读，条目全部落实，页面文本核验通过 |
| [集群作业](http://127.0.0.1:4321/docs/jobs/) | 3 | 已审读，条目全部落实，页面文本核验通过 |
| [状态与执行报告](http://127.0.0.1:4321/docs/observability/) | 4 | 已审读，条目全部落实，页面文本核验通过 |
| [硬件性能模型](http://127.0.0.1:4321/docs/hardware-profiles/) | 3 | 已审读，条目全部落实，页面文本核验通过 |
| [性能预测](http://127.0.0.1:4321/docs/performance/) | 5 | 已审读，条目全部落实，页面文本核验通过 |
| [扩展量子后端](http://127.0.0.1:4321/docs/providers/) | 5 | 已审读，条目全部落实，页面文本核验通过 |
| [API 参考](http://127.0.0.1:4321/docs/api/) | 0 | 已审读，未发现需单列的表述问题 |
| [运行时与结果引用](http://127.0.0.1:4321/docs/api/runtime/) | 2 | 已审读，条目全部落实，页面文本核验通过 |
| [组件与 Actor](http://127.0.0.1:4321/docs/api/components/) | 1 | 已审读，条目全部落实，页面文本核验通过 |
| [工作流](http://127.0.0.1:4321/docs/api/workflows/) | 2 | 已审读，条目全部落实，页面文本核验通过 |
| [量子后端与结果](http://127.0.0.1:4321/docs/api/quantum/) | 2 | 已审读，条目全部落实，页面文本核验通过 |
| [Provider 协议](http://127.0.0.1:4321/docs/api/providers/) | 4 | 已审读，条目全部落实，页面文本核验通过 |
| [集群作业](http://127.0.0.1:4321/docs/api/jobs/) | 1 | 已审读，条目全部落实，页面文本核验通过 |
| [执行报告](http://127.0.0.1:4321/docs/api/observability/) | 5 | 已审读，条目全部落实，页面文本核验通过 |
| [性能模型与预测](http://127.0.0.1:4321/docs/api/performance/) | 2 | 已审读，条目全部落实，页面文本核验通过 |
| [异常类型](http://127.0.0.1:4321/docs/api/errors/) | 4 | 已审读，条目全部落实，页面文本核验通过 |
| [应用教程介绍](http://127.0.0.1:4321/docs/examples/) | 1 | 已审读，条目全部落实，页面文本核验通过 |
| [404 页面](http://127.0.0.1:4321/404/) | 1 | 已审读，条目全部落实，页面文本核验通过 |

## 源文件覆盖

以下保留本轮实际审读的页面、组件、文案与展示源码；结果中心截图链接已更新为另存的文案修订版。未挂载的旧组件、`website-flow/` 独立副本、源码包和 README 不计入当前 4321 网站文案。

- [website/src/assets/guides/aimd/01-compile.png](/Users/siwei/Developer/codex_project/PivotQ/website/src/assets/guides/aimd/01-compile.png)
- [website/src/assets/guides/aimd/02-hardware-assignment.png](/Users/siwei/Developer/codex_project/PivotQ/website/src/assets/guides/aimd/02-hardware-assignment.png)
- [website/src/assets/guides/aimd/03-performance-forecast.png](/Users/siwei/Developer/codex_project/PivotQ/website/src/assets/guides/aimd/03-performance-forecast.png)
- [website/src/assets/guides/aimd/04-task-resources.png](/Users/siwei/Developer/codex_project/PivotQ/website/src/assets/guides/aimd/04-task-resources.png)
- [website/src/assets/guides/aimd/05-results-center-copy-edited.png](/Users/siwei/Developer/codex_project/PivotQ/website/src/assets/guides/aimd/05-results-center-copy-edited.png)
- [website/src/assets/guides/aimd/06-molecule-evolution.png](/Users/siwei/Developer/codex_project/PivotQ/website/src/assets/guides/aimd/06-molecule-evolution.png)
- [website/src/components/AimdExecutionFlow.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/AimdExecutionFlow.astro)
- [website/src/components/AimdModelEquations.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/AimdModelEquations.astro)
- [website/src/components/AimdWorkbench.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/AimdWorkbench.astro)
- [website/src/components/DocsFooter.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/DocsFooter.astro)
- [website/src/components/DocsHeader.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/DocsHeader.astro)
- [website/src/components/DocsPageTitle.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/DocsPageTitle.astro)
- [website/src/components/DocsSidebar.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/DocsSidebar.astro)
- [website/src/components/DocsTheme.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/DocsTheme.astro)
- [website/src/components/DocsTitle.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/DocsTitle.astro)
- [website/src/components/FlowWorkbench.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/FlowWorkbench.astro)
- [website/src/components/GitHubLink.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/GitHubLink.astro)
- [website/src/components/HardwareArchitecture.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/HardwareArchitecture.astro)
- [website/src/components/HomeOverview.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/HomeOverview.astro)
- [website/src/components/HybridExample.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/HybridExample.astro)
- [website/src/components/PortalHeader.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/PortalHeader.astro)
- [website/src/components/QramDiagram.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/QramDiagram.astro)
- [website/src/components/SDKExample.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/SDKExample.astro)
- [website/src/components/SystemArchitecture.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/components/SystemArchitecture.astro)
- [website/src/content/docs/docs/api.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api.md)
- [website/src/content/docs/docs/api/components.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/components.md)
- [website/src/content/docs/docs/api/errors.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/errors.md)
- [website/src/content/docs/docs/api/jobs.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/jobs.md)
- [website/src/content/docs/docs/api/observability.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/observability.md)
- [website/src/content/docs/docs/api/performance.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/performance.md)
- [website/src/content/docs/docs/api/providers.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/providers.md)
- [website/src/content/docs/docs/api/quantum.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/quantum.md)
- [website/src/content/docs/docs/api/runtime.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/runtime.md)
- [website/src/content/docs/docs/api/workflows.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/workflows.md)
- [website/src/content/docs/docs/architecture.mdx](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/architecture.mdx)
- [website/src/content/docs/docs/classical-tasks.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/classical-tasks.md)
- [website/src/content/docs/docs/components-actors.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/components-actors.md)
- [website/src/content/docs/docs/examples.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/examples.md)
- [website/src/content/docs/docs/gpu-computing.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/gpu-computing.md)
- [website/src/content/docs/docs/hardware-profiles.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/hardware-profiles.md)
- [website/src/content/docs/docs/hybrid-programs.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/hybrid-programs.md)
- [website/src/content/docs/docs/installation.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/installation.md)
- [website/src/content/docs/docs/jobs.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/jobs.md)
- [website/src/content/docs/docs/observability.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/observability.md)
- [website/src/content/docs/docs/performance.mdx](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/performance.mdx)
- [website/src/content/docs/docs/providers.mdx](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/providers.mdx)
- [website/src/content/docs/docs/quantum-backends.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quantum-backends.md)
- [website/src/content/docs/docs/quickstart.mdx](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quickstart.mdx)
- [website/src/content/docs/docs/troubleshooting.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/troubleshooting.md)
- [website/src/content/docs/docs/workflows.mdx](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/workflows.mdx)
- [website/src/content/guide/aimd.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/aimd.md)
- [website/src/content/guide/system.md](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/system.md)
- [website/src/content/i18n/zh-CN.json](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/i18n/zh-CN.json)
- [website/src/data/site.ts](/Users/siwei/Developer/codex_project/PivotQ/website/src/data/site.ts)
- [website/src/layouts/PortalLayout.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/layouts/PortalLayout.astro)
- [website/src/lib/aimd-analysis.ts](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/aimd-analysis.ts)
- [website/src/lib/aimd-circuit-output.txt](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/aimd-circuit-output.txt)
- [website/src/lib/aimd-circuit-summary.py](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/aimd-circuit-summary.py)
- [website/src/lib/aimd-circuit.ts](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/aimd-circuit.ts)
- [website/src/lib/aimd-code-editor.ts](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/aimd-code-editor.ts)
- [website/src/lib/aimd-cpu-energy-force.py](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/aimd-cpu-energy-force.py)
- [website/src/lib/aimd-cpu-output.txt](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/aimd-cpu-output.txt)
- [website/src/lib/aimd-data.ts](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/aimd-data.ts)
- [website/src/lib/aimd-model-source.py](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/aimd-model-source.py)（仅页面展示片段）
- [website/src/lib/aimd-trajectory-analysis.py](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/aimd-trajectory-analysis.py)
- [website/src/lib/aimd-trajectory-output.txt](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/aimd-trajectory-output.txt)
- [website/src/lib/aimd-workbench.ts](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/aimd-workbench.ts)
- [website/src/lib/docs-example-source.ts](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/docs-example-source.ts)
- [website/src/lib/docs-examples/custom_backend.py](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/docs-examples/custom_backend.py)
- [website/src/lib/docs-examples/hybrid_program.py](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/docs-examples/hybrid_program.py)
- [website/src/lib/docs-examples/performance_prediction.py](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/docs-examples/performance_prediction.py)
- [website/src/lib/docs-examples/system_workflow.py](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/docs-examples/system_workflow.py)
- [website/src/lib/hardware-scene.ts](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/hardware-scene.ts)
- [website/src/lib/molecule-view.ts](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/molecule-view.ts)
- [website/src/lib/qram_query.py](/Users/siwei/Developer/codex_project/PivotQ/website/src/lib/qram_query.py)
- [website/src/pages/404.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/404.astro)
- [website/src/pages/docs/aimd.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/docs/aimd.astro)
- [website/src/pages/docs/index.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/docs/index.astro)
- [website/src/pages/examples/aimd.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro)
- [website/src/pages/examples/qram.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro)
- [website/src/pages/index.astro](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/index.astro)

## 本次实际改动与验证状态

- 134 条全部落实，其中 112 条问题修改、22 条可选润色；最终措辞及最新位置见逐条记录。
- 首页指定句以当前源码为准；同期教程润色按当前上下文合并，没有回填旧版本。
- 六张教程截图保留；结果中心截图另存修订版，仅修改两处标签，原始截图保留。
- 本次文案修改保留 Markdown 代码块与 Astro 脚本、样式、`pre` 内容，没有修改 API、算法、数值或运行行为；同期其他任务的变更不包含在此保证内。
- 类型与内容检查、32 页构建以及 `git diff --check` 已通过。
- 当前 4321 网站的 32 个路由状态码符合预期，132 / 132 条页面文本逐条匹配，修订截图引用正确。
- 本机 Chrome 浏览器回归：**151 个场景、41 个站内链接全部通过**；截图加载、桌面与移动交互通过，未发现 JavaScript 错误或意外外部资源请求。
