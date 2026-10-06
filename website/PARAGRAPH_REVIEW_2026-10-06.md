# PivotQ 段落与篇章审读

审读日期：2026-10-06。对象：[当前 4321 网站](http://127.0.0.1:4321/)的 `website/` 版本。

本轮通读 **31 个内容页面及 404 页面**，交叉核对正文、代码前后说明、图表位置和源文件。发现 **29 处段落或篇章组织问题**，分布在 **16 个页面**；其中 **10 处优先调整、19 处建议调整**。这些是本轮审读意见，后文改写为建议稿。

“优先调整”指示例与说明不一致、核心关系较晚交代，或多种对象混排，容易让读者误解；“建议调整”指中心意思基本明确，但顺序、分段或重复解释增加理解负担。专业术语、API 签名与必要的事实限制本身不计为问题。

本轮最集中的是三类问题：水分子与 QRAM 教程重复展开，部分说明与对应图或代码分离；SDK 文档的示例切换缺少交代；预测与设备文档将不同层次的条件混在同一段。

## 逐项索引

| 编号 | 位置 | 段落或篇章问题 | 建议等级 |
| --- | --- | --- | --- |
| 01 | [文档总览 · 系统介绍第二段](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/system.md:12) | 文档入口过早比较首页分工与历史截图，打断阅读路径选择。 | 建议调整 |
| 02 | [水分子动力学模拟 · 开篇目标与第一章末尾的材料说明](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:58) | 单构型计算与独立轨迹阅读的分工，在公式之后才完整说明，宜前移。 | 建议调整 |
| 03 | [水分子动力学模拟 · 构造量子电路：代码前的五段导读](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:80) | 安装、运行、参数、摘要和读图方法挤在代码前，解释对象尚未出现。 | 建议调整 |
| 04 | [水分子动力学模拟 · 计算步骤：正文、四步列表与读出说明](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:109) | 同一计算链在公式、正文、四步列表中反复展开，新信息不够突出。 | 建议调整 |
| 05 | [水分子动力学模拟 · 轨迹与能量曲线：读一帧、复算代码及图的位置](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:134) | 先让读者拖动图和下载文件，图与下载入口却在后文，阅读操作来回折返。 | 优先调整 |
| 06 | [量子随机存储器 · 路径演算与树形寻址两节](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:68) | “10 先右后左”在多个段落反复讲，寻址结束后迟迟不进入读取。 | 建议调整 |
| 07 | [量子随机存储器 · 一次测量会得到什么：代码运行与测量解释](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:142) | 标题问测量结果，先讲完整运行教程，核心答案拖到大段代码之后。 | 优先调整 |
| 08 | [水分子动力学模拟工作台教程 · 步骤 1 之前的五段介绍](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/aimd.md:6) | 原理、任务目标、启动方法、预测配置和实际后端交叉出现。 | 建议调整 |
| 09 | [水分子动力学模拟工作台教程 · 查看性能预测结果：预测范围参数段](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/aimd.md:78) | 应用规模、QPU 参数、CPU 参数和验证边界塞在同一段。 | 建议调整 |
| 10 | [快速上手 · 切换执行方式](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quickstart.mdx:38) | 执行器、量子后端和算法参数三条选择线交错。 | 建议调整 |
| 11 | [编写混合程序 · 循环与参数更新](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/hybrid-programs.md:37) | 文字讲按上轮结果更新参数，代码却演示固定角度扫描。 | 优先调整 |
| 12 | [编写混合程序 · 指定硬件](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/hybrid-programs.md:55) | CPU/GPU 入口、QPU 能力查询和电路构造要求混在一段。 | 优先调整 |
| 13 | [组件与 Actor · 显式注册组件](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/components-actors.md:49) | 未先解释显式组件与上一节 Actor 的关系，就进入生命周期和两类 kwargs。 | 建议调整 |
| 14 | [可复用工作流 · 定义与运行 → 完整教程](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/workflows.mdx:29) | 承诺补齐 update_parameter，完整示例却换成 History Actor，无法一一对照。 | 优先调整 |
| 15 | [可复用工作流 · 复用、失败与释放](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/workflows.mdx:54) | 无环图与 Python 算法循环的关系拖到文末，又与性能预测边界混排。 | 建议调整 |
| 16 | [GPU 与异构资源 · GPU 组件如何执行](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/gpu-computing.md:39) | 环境前提、提交入口、参数选项和运行验收未按操作步骤组织。 | 建议调整 |
| 17 | [GPU 与异构资源 · 目标配置与实际执行](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/gpu-computing.md:62) | 目标配置、实际后端、历史截图和预测误差连续切换。 | 建议调整 |
| 18 | [量子后端 · 支持的电路](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quantum-backends.md:35) | 输入类型、公共限制、模拟器范围和真实 QPU 限制没有分层。 | 建议调整 |
| 19 | [量子后端 · 接入 QPU 后端](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quantum-backends.md:61) | 静态能力、实例创建时机、结果处理与测量基要求交错。 | 建议调整 |
| 20 | [硬件性能模型 · CPU 与 QPU](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/hardware-profiles.md:35) | CPU 输入规则讲到一半插入 QPU 和时间取整，再回到 CPU 开销。 | 优先调整 |
| 21 | [性能预测 · 描述工作量](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/performance.mdx:27) | 工作量、硬件和 preview 的关系在代码之后才解释，顺序与代码相反。 | 建议调整 |
| 22 | [性能预测 · 完整对比教程](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/performance.mdx:60) | 未先说清三项比较分别改变什么，也未及时说明算法质量等价未验证。 | 优先调整 |
| 23 | [性能预测 · 结果边界](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/performance.mdx:66) | 模型缺项、计时口径、来源标注和网页入口能力堆在页尾。 | 建议调整 |
| 24 | [扩展量子后端 · 注册与创建](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/providers.mdx:24) | 执行、注册、创建后端和首次实例化之间来回倒叙。 | 优先调整 |
| 25 | [扩展量子后端 · Provider 协议](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/providers.mdx:38) | Provider 与 SDK 各自处理的两层位序映射没有先区分。 | 优先调整 |
| 26 | [扩展量子后端 · 结果校验与故障](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/providers.mdx:48) | 错误分类的判断条件、未知状态及恢复规则挤在长段中。 | 建议调整 |
| 27 | [组件与 Actor · actor](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/components.md:49) | 默认串行、手动依赖和工作流自动依赖的关系没有展开。 | 建议调整 |
| 28 | [Provider 协议 · BackendCapabilities → QuantumRequest → ProviderResult](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/providers.md:38) | 接收末尾测量、移除测量、返回分布、恢复映射散落在多个小节。 | 建议调整 |
| 29 | [集群作业 · JobSpec](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/jobs.md:28) | 普通程序入口之后突然写“保留作业入口”，未说明这是兼容 Driver 入口。 | 优先调整 |

## 原文、阅读障碍与整段调整建议

### 01 · 文档总览：系统介绍第二段

建议调整。页面：[打开文章](http://127.0.0.1:4321/docs/)；源码：[文档总览 · 系统介绍第二段](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/system.md:12)。

原文（相关段落及必要上下文）：

> 首页“编程模型”以水分子动力学模拟为例：CPU 根据当前原子坐标准备输入，QPU 运行电路，测量结果经整理后作为 GPU 预测势能的输入；CPU 再计算受力并更新原子位置。工作台教程截图中的任务实际采用 CPU 数值模拟；首页展示的 GPU/QPU 分工不是那次任务的运行记录。

阅读障碍：文档入口刚介绍完三个系统模块，就转入首页分工、工作台截图的实际后端及二者不可混用的说明。读者还没选择阅读路径，就被要求同时理解两个页面和两套配置；这段承担了应用说明和证据校对两种任务，偏离入口页的主线。

调整方法：入口页先说明去哪里读系统、SDK、应用；把完整的配置差异说明放回应用教程附近，必要时在教程入口后保留一句提醒。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

了解系统组成和设备分工，可阅读“系统介绍”；准备编写自己的程序，可从下面的“安装”和“快速上手”开始。首页的水分子案例展示 CPU、GPU、QPU 的分工。

各处案例采用的配置需分别阅读：首页展示 CPU/GPU/QPU 分工，工作台截图记录的是 CPU 数值模拟，两者不是同一次运行。

### 02 · 水分子动力学模拟：开篇目标与第一章末尾的材料说明

建议调整。页面：[打开文章](http://127.0.0.1:4321/examples/aimd/)；源码：[水分子动力学模拟 · 开篇目标与第一章末尾的材料说明](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:58)。

原文（以下为相关位置的完整段落，按引用顺序列出）：

[第 58 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:58)：

> 知道水分子此刻的样子，怎样计算它下一刻的位置？这篇教程从三个原子的坐标出发，沿着能量、受力与位置更新逐步展开：先看量子电路如何参与计算，再看 CPU 与 QPU 如何分工，最后借一份已保存的轨迹观察分子的运动。

[第 75 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:75)：

> 带着这条计算路径往下读，代码 1、2 会先搭好可复用的三比特电路。到代码 3，再用当前仓库的默认模型，在 CPU 上算出一个构型的能量与力，把上面的公式落实为数值。

[第 75 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:75)：

> 最后的代码 4 会转向另一份归档的轨迹 CSV。它没有附上配套的模型权重、编码配置或执行后端记录，所以目前无法确认它是否由当前模型生成，也无法用前三段代码重现后面的能量曲线。阅读时，需要把这份轨迹与前面的模型计算分开理解。

阅读障碍：开篇以“计算下一刻的位置”串联后文，但代码部分完成的是电路构造和单构型能量/受力，轨迹阅读使用另一份归档。第一章末尾和轨迹章已明确说明来源差异，事实界限清楚；阅读负担在于，读者经过公式后才取得完整的材料分工，需要回头调整对整篇教程目标的预期。

调整方法：开篇就把两项学习任务并列说明：理解当前模型的单步计算，以及独立阅读归档轨迹。把材料对应关系放到代码前，并给轨迹章节显式标注“独立练习”。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

这篇教程分为两个部分。第一部分从水分子坐标出发，介绍量子电路、经典能量模型和差分求力，并用代码算出一个构型的能量与受力；代码 1、2 构造电路，代码 3 完成这次单构型计算，不推进轨迹。

第二部分使用另一份已保存的 CSV，练习查看分子运动并复算键长、键角。该归档没有配套的模型权重、编码配置或后端记录，因此不能确认它由当前模型生成，也不能用前三段代码重现其中的能量曲线。

### 03 · 水分子动力学模拟：构造量子电路：代码前的五段导读

建议调整。页面：[打开文章](http://127.0.0.1:4321/examples/aimd/)；源码：[水分子动力学模拟 · 构造量子电路：代码前的五段导读](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:80)。

原文（以下为相关位置的完整段落，按引用顺序列出）：

[第 80 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:80)：

> 几何已经可以写成三个编码角，接下来要把它们放进怎样的电路？先准备 Python 3.12，在 PivotQ 仓库根目录运行 python -m pip install ./packages/framework，也可以使用仓库已配置的统一环境。PivotQ 的电路接口直接复用 Qiskit 对象。

[第 80 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:80)：

> 按代码 1、代码 2 的顺序运行，就会先定义辅助函数，再构造三比特电路并打印结构摘要。下方的“代码 2 输出”来自这两段源码的实际运行；浏览器只展示源码和输出，不执行 Python。

[第 80 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:80)：

> 此时搭好的是电路结构。它保留了 enc 和 theta 共 14 个未赋值参数，其中 enc 随分子构型改变，theta 是模型训练后使用的参数。摘要中的基础门总数 70、电路深度 39，描述的也都是电路结构，不能表示某一帧构型的能量。

[第 80 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:80)：

> 看电路图时，可以从左边沿着 q0、q1、q2 三条水平线往右读。单比特旋转先改变各量子比特的状态，CZ 门再对相邻的两个比特施加受控相位变换；随后，一组 Pauli 旋转在指定比特上沿指定轴继续变换量子态。

[第 80 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:80)：

> 两张图展示了同一电路的不同层次：“模型门结构”保留 Rx 与 Pauli 旋转，便于理解；“基础门分解”把它们展开为 Ry、Rz、CZ 门。要让这套结构给出能量，还需要代入参数、读出量子态，再将读出特征交给经典模型。

阅读障碍：五段依次切换问题引入、安装环境、执行方法、14 个参数、70 个门/39 层、读图方法和门分解。大部分解释都发生在代码与图之前，读者尚未看到对象就要记住后面如何解读它，操作说明和概念说明互相打断。

调整方法：按阅读动作分成“准备与运行”“如何看输出”“如何看两张图”三处，分别紧贴代码、输出和图；保留参数及深度限定，但放在相关对象旁边。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

准备与运行：使用 Python 3.12，在仓库根目录运行 `python -m pip install ./packages/framework`，或使用仓库已配置的统一环境。按顺序运行代码 1、2，即可构造三比特电路并打印摘要。PivotQ 的电路接口直接复用 Qiskit 对象；网页展示的是已保存的源码与实际运行输出，不在浏览器中执行 Python。

输出旁说明：电路包含 14 个未赋值参数，分为随构型变化的 `enc` 和训练后使用的 `theta`。70 个基础门、39 层深度描述电路结构，不是分子能量，也不能换算为分子动力学时间。

图旁说明：沿 q0、q1、q2 从左向右阅读。模型门结构保留 Rx 和 Pauli 旋转；基础门分解将它们展开为 Ry、Rz、CZ，两图表示同一电路。代入参数并取得读出特征后，经典模型才能预测能量。

### 04 · 水分子动力学模拟：计算步骤：正文、四步列表与读出说明

建议调整。页面：[打开文章](http://127.0.0.1:4321/examples/aimd/)；源码：[水分子动力学模拟 · 计算步骤：正文、四步列表与读出说明](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:109)。

原文（以下为相关位置的完整段落，按引用顺序列出）：

[第 109 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:109)：

> 电路准备好以后，它怎样参与一次位置更新？先代入编码角和模型参数，量子阶段就可以根据 Z 基、X 基的读出结果，各提取 7 个统计特征。这里得到的还只是特征，并不是原子坐标或受力。

[第 109 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:109)：

> 这些特征随后进入原应用的经典能量模型。模型有两层、每层 32 个单元，负责预测势能。有了能量计算方法，就能对坐标做中心有限差分，求力并移除刚体数值残差；VelocityVerlet 积分器再结合所得的力，更新原子位置和速度。新构型由此成为下一时间步的输入，同一条计算链便可以继续。

[第 120 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:120)：

> 读到这里，还可以停下来分清“测量结果”和“读出特征”。一次测量只给出一组比特结果；这里需要的特征，则是根据电路在 Z 基、X 基下的读出结果计算的统计量。在采样设备上，要通过多次测量估计这些统计量；理想模拟器也可以直接计算期望值。

[第 120 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:120)：

> 因此，一次测量的结果还不能直接作为分子的势能。要等经典能量模型接收这些特征，才会得到当前构型的能量预测。

阅读障碍：同一条“特征→能量→力→位置”的计算链已在第一章的概念与公式中展开，第三章又先用正文叙述一遍，再通过四步列表和执行流程图展开。不同形式各有用途，但正文多次从头推演，读者难以区分哪些内容是本节新增的执行细节。测量与统计特征的补充说明可直接放在四步列表的量子读出步骤旁，让新信息与主流程对齐。

调整方法：保留公式解释、四步列表和硬件流程图各自的用途；第三章正文只概括新信息，不再次完整推演。测量/特征的说明紧贴量子读出步骤，代入编码角与模型参数的前提保留。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

本节把前面的公式对应到实际计算步骤。先将编码角和模型参数代入电路，再从 Z 基、X 基读出中各提取 7 个统计特征，共 14 个。采样设备通过多次测量估计这些特征，理想模拟器也可直接计算期望值；单次测量得到的一组比特不能直接作为势能。

经典模型接收这些特征并预测势能，本例模型包含两层、每层 32 个单元。后续按前述中心差分方法求力、移除刚体数值残差，再由 VelocityVerlet 积分器更新位置与速度。下方四步列表概括计算顺序，设备流程图说明各阶段的目标硬件。

### 05 · 水分子动力学模拟：轨迹与能量曲线：读一帧、复算代码及图的位置

优先调整。页面：[打开文章](http://127.0.0.1:4321/examples/aimd/)；源码：[水分子动力学模拟 · 轨迹与能量曲线：读一帧、复算代码及图的位置](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:134)。

原文（以下为相关位置的完整段落，按引用顺序列出）：

[第 134 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:134)：

> 先停在第 0 帧：两条 O–H 键都是 0.9572 Å，H–O–H 夹角为 104.52°，温度为 300 K，总能量为 0.5912 eV。这些数值共同描述了轨迹的起点。

[第 134 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:134)：

> 把曲线光标拖到 100 fs，两条键长变为 1.2024 Å 和 1.1422 Å，夹角为 95.27°。与起点相比，两条键分别长了 0.2452 Å、0.1850 Å，夹角小了 9.25°。此时，分子图显示当前形状，曲线光标也指向同一帧。

[第 141 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/aimd.astro:141)：

> 图中的键长和键角，也可以直接从原子坐标复算。先在下方的“数据来源与运行条件”下载两个 CSV，放到同一个 imported/ 目录；再把这段代码保存为 analyze_imported.py，在 Python 3.9+ 中运行 python3 analyze_imported.py imported。它会从坐标算出键长和键角，并读取相同时间步的总能量，便于与图中数据对照。

阅读障碍：正文先要求暂停第 0 帧、拖动曲线光标，实际回放组件却放在后面的解释、代码 4 和数据来源之后。复算段落又要求先去下方下载文件再回来执行。文章连续让读者向下找对象、向上找说明；这是操作顺序与阅读顺序不一致，不是改几个连接词能解决。

调整方法：将数据范围及来源简介、回放组件、逐帧观察指引放在一起；复算作为后续独立步骤，下载链接和环境要求置于代码 4 前。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

先查看下面的轨迹和曲线。本组归档覆盖 0–100 fs，共 1001 帧。暂停在第 0 帧，可看到两条 O–H 键均为 0.9572 Å、夹角 104.52°、温度 300 K、总能量 0.5912 eV。

再将光标移动到 100 fs：两条键长为 1.2024 Å 和 1.1422 Å，夹角为 95.27°。与起点相比，两条键分别增长 0.2452 Å、0.1850 Å，夹角减小 9.25°。这只是首末帧的差异；中间是否持续伸长或收缩，还要查看完整时间序列。这里是在阅读已有数据，不重新生成轨迹。

完成观察后，可用代码 4 复算首末帧。先从本段的下载链接取得能量与时间 CSV、原子坐标 CSV，放入同一个 `imported/` 目录；再将代码保存为 `analyze_imported.py`，使用 Python 3.9+ 运行 `python3 analyze_imported.py imported`。程序从坐标计算键长、键角，并读取对应时间步的总能量。

### 06 · 量子随机存储器：路径演算与树形寻址两节

建议调整。页面：[打开文章](http://127.0.0.1:4321/examples/qram/)；源码：[量子随机存储器 · 路径演算与树形寻址两节](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:68)。

原文（以下为相关位置的完整段落，按引用顺序列出）：

[第 68 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:68)：

> 把这些位置画成一棵两层分叉的树，地址就可以变成行走路线。我们先约定：遇到 0 向左，遇到 1 向右。从根节点出发，按顺序读完 10，便会先向右，再向左。下面这小段 Python 把刚才的过程写了下来，可以先对照输出读一遍。

[第 78 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:78)：

> 看到“存储单元 10”，说明我们已经找对位置了。现在还没有读取内容，也没有改变数据量子位；这个位置究竟保存 0 还是 1，等拿到后面的存储表，就能继续往下算。

[第 94 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:94)：

> 回头看这张图，第一位决定第一层怎么走，第二位决定第二层怎么走，两层分叉就能到达四个存储单元。蓝线画出了确定地址 |10⟩ 的路线。

阅读障碍：“0 左 1 右、10 先右后左”在路径说明、Python 输出、两步列表、图注和图后段落中反复讲述。正文在第二节已经完成寻址，第三节再次完整重走同一过程，新增信息很少，导致直到第四节才开始回答“里面存了什么”。

调整方法：把代码、两步说明和树图合为同一节；只保留一次完整演算，图后立即接存储表。叠加态限制移到叠加查询段落。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

约定 0 向左、1 向右。从根节点依次读取地址 10，先向右，再向左，就到达编号 10 的存储单元。下面的 Python 输出与树图蓝线展示的是同一条路径。

寻址到这里已经完成，但还没有读取内容。接下来查看存储表：本例规定地址 10 存储 1，我们将把它读入数据量子位。

### 07 · 量子随机存储器：一次测量会得到什么：代码运行与测量解释

优先调整。页面：[打开文章](http://127.0.0.1:4321/examples/qram/)；源码：[量子随机存储器 · 一次测量会得到什么：代码运行与测量解释](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:142)。

原文（以下为相关位置的完整段落，按引用顺序列出）：

[第 142 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:142)：

> 手上的存储表和查询规则已经足够写出一个小程序了。我们用 PivotQ 构造可逆查询电路；它的电路接口直接复用 Qiskit 对象，因此接着就能交给 Qiskit Statevector，计算查询后的理想量子态。

[第 143 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:143)：

> 对照代码前，先认清三个量子位：q2、q1 负责地址，q0 负责数据。Qiskit 按 q2q1q0 写出的三位标签，会被程序拆成 |地址⟩|数据⟩ 的样子，这样就能和前面的公式一一对应。四个函数也沿着同一条思路展开：准备输入、执行查询，再查看状态。

[第 151 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:151)：

> 如果想亲手试一遍，可以使用 Python 3.12，在 PivotQ 仓库根目录运行 python -m pip install ./packages/framework，也可以直接使用仓库已配置的统一环境。接着把下方代码复制并保存为 qram_query.py，在同一环境中运行 python qram_query.py，然后对照下面的输出，看看它是否和刚才的推导一致。

[第 161 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/pages/examples/qram.astro:161)：

> 这时很自然会想到开头留下的问题：既然屏幕上有两行，一次测量能把两行都读出来吗？Statevector 能列出理想态的所有非零分支，是因为我们正在查看模拟器计算出的量子态；这里没有执行随机测量。若直接测量地址位和数据位，单次只会得到其中一组。每次重新准备同样的输入、完成查询再测量，重复多次后，两组结果的出现频率才会趋近各 50%。

阅读障碍：标题问“一次测量”，开头却依次讲库的关系、量子位编号、四个函数、器件边界、安装命令和完整程序，读者要越过整段运行教程才看到标题的答案。测量解释本身清楚；需要调整的是小节范围与标题的对应关系，使运行方法和结果含义各有明确入口。

调整方法：将此节分为“运行理想查询”和“一次测量的含义”，前者按环境→位序→函数→输出组织；后者先直接回答单次结果，再解释 Statevector 和重复测量。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

运行理想查询：使用 Python 3.12 安装框架，保存并运行下方 `qram_query.py`。程序用 q2、q1 表示地址，用 q0 表示数据；两种输入经过同一查询电路，再由 Statevector 计算理想态的振幅和概率。四个存储位直接编码在电路中，本例不创建可动态读写的量子随机存储器。

一次测量的含义：测量叠加查询后的地址位和数据位，单次只会得到 |01⟩|0⟩ 或 |10⟩|1⟩ 中的一组。屏幕能同时列出两组，是因为 Statevector 展示的是完整理想态，没有进行随机抽样。每次重新准备相同输入、完成查询再测量，重复多次后，两组结果的频率才趋近各 50%。

### 08 · 水分子动力学模拟工作台教程：步骤 1 之前的五段介绍

建议调整。页面：[打开文章](http://127.0.0.1:4321/docs/aimd/)；源码：[水分子动力学模拟工作台教程 · 步骤 1 之前的五段介绍](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/aimd.md:6)。

原文（以下为相关位置的完整段落，按引用顺序列出）：

[第 6 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/aimd.md:6)：

> 水分子中的氧原子和两个氢原子会随时间移动。程序从它们当前的位置预测能量，计算能量随位置的变化以得到各原子的受力，再用力更新位置。重复这一过程，就得到一段分子运动轨迹。

[第 8 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/aimd.md:8)：

> 本教程使用预先训练好的量子-经典代理势能模型。严格的“从头算分子动力学”（AIMD）通常在每一步重新计算电子结构；这里的计算方式是：量子电路提供数值特征，经典模型预测能量，程序据此求力，并不在每一步重新求解电子结构。

[第 10 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/aimd.md:10)：

> 本教程用 10 个时间步演示水分子动力学模拟的工作台操作：选择应用、编译电路、分配设备、预测耗时、提交任务并检查结果。历史工作台与以下截图中的应用标签为 **H₂O AIMD**。

[第 12 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/aimd.md:12)：

> 先按照文档中[“启动工作台”](http://127.0.0.1:4321/docs/#启动工作台)一节的说明，在本机启动 Docker 工作台，再在浏览器打开 `http://127.0.0.1:8787/`。本教程操作的是该工作台；当前静态网站只展示文档和已保存的教程内容。

[第 14 行](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/aimd.md:14)：

> 本例使用 **CPU 与 QPU** 目标配置：经典计算阶段选择“参考 CPU”，量子特征计算选择虚拟目标“Fake SC-36”。截图来自同一组 10 步任务参数的实际操作；运行使用工作台的 **CPU 数值计算模式**，量子电路也由 CPU 数值模拟，不连接真实 QPU。

阅读障碍：操作教程在开始操作前连续切换分子物理、严格 AIMD 的定义、10 步任务目标、Docker 启动、预测目标和实际 CPU 执行。每项条件都已说明，但“要完成什么、先准备什么、如何理解两种运行口径”分散在五段中；以操作为目的的读者需要自行把前提整理出来。

调整方法：先给任务目标和启动入口，再并列列出“预测配置/实际运行”；科学原理及 AIMD 名称说明单独放作背景短段或链接。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

本教程带你完成一次 10 步水分子动力学模拟：选择应用、编译电路、分配设备、预测耗时、提交任务并查看结果。先按“启动工作台”的说明启动 Docker 服务，再打开 `http://127.0.0.1:8787/`。当前网站展示的是说明与保存的截图。

阅读截图时，请区分预测目标与实际执行方式：性能预测采用参考 CPU 和虚拟 QPU 目标 Fake SC-36；实际运行采用 CPU 数值计算，量子电路也在 CPU 上模拟，没有连接真实 QPU。

模型背景：量子电路提供数值特征，预先训练的经典模型据此预测势能，再求力并更新位置。历史应用标签为 H₂O AIMD，但本例不在每一步重新计算电子结构，因此应与严格的从头算分子动力学区分。

### 09 · 水分子动力学模拟工作台教程：查看性能预测结果：预测范围参数段

建议调整。页面：[打开文章](http://127.0.0.1:4321/docs/aimd/)；源码：[水分子动力学模拟工作台教程 · 查看性能预测结果：预测范围参数段](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/guide/aimd.md:78)。

原文（相关段落及必要上下文）：

> 本例水分子电路使用 **3 个逻辑比特**；Fake SC-36 的“36”表示教程假设的芯片容量。预测中假设其每秒可完成 10,000 次电路运行与测量（shots），每批提交时延为 1 ms。经典 CPU 推理的工作量根据冻结模型的各层规模估算，计算峰值和访存带宽分别假设为 **1 TFLOPS** 和 **100 GB/s**；其他固定阶段采用参考宿主机的开销估计。这些参数未经实际目标硬件标定，预测不代表实机测试结果，也不评价科学精度。

阅读障碍：一个段落同时列出电路规模、芯片容量、shots 速率、提交延迟、CPU 模型工作量、计算峰值、带宽、其他开销及验证边界。原文已标明各数字的归属，但读者仍需在应用、QPU、CPU 和整套预测之间逐句切换，才能整理出这次预测用了哪些输入。按对象分列后会更方便理解和核对。

调整方法：先说明是假设配置，再用 QPU/CPU/其他阶段三项列参数，最后集中说明标定和科学精度边界。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

本次预测将应用工作量与假设的硬件参数配合使用。其中，硬件容量、速率和延迟参数未经实际目标设备标定。

- QPU：应用电路使用 3 个逻辑比特；Fake SC-36 假设芯片容量为 36 比特，每秒完成 10,000 次电路运行与测量（shots），每批提交时延为 1 ms。
- CPU：根据冻结模型的各层规模估算推理工作量；计算峰值假设为 1 TFLOPS，访存带宽假设为 100 GB/s。
- 其他固定阶段：采用参考宿主机的开销估计。

这些设置用于估算执行耗时，不代表目标设备的实测性能，也不用于评价科学精度。

### 10 · 快速上手：切换执行方式

建议调整。页面：[打开文章](http://127.0.0.1:4321/docs/quickstart/)；源码：[快速上手 · 切换执行方式](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quickstart.mdx:38)。

原文（相关段落及必要上下文）：

> 连接 QPU 时，先由部署方或用户实现并注册 Provider，再在程序中取得对应的后端对象。参见[通过 Provider 接入 QPU](http://127.0.0.1:4321/docs/quantum-backends/#接入-qpu-后端)与[扩展量子后端](http://127.0.0.1:4321/docs/providers/)。经典任务和量子任务之间仍通过相同的结果引用传递数据。
>
> 仅调试函数逻辑时，也可以显式使用本地线程池执行器。这种模式不启动 Ray：
>
> ```bash
> python packages/framework/examples/hybrid_program.py --executor local
> ```
>
> 教程中的脚本不带参数时同样使用本地执行器；本页主流程通过 `--executor ray` 显式启用 Ray。`--seed` 控制模拟器采样；可通过 `--steps 30`、`--shots 2048` 调整迭代上限与采样次数。

阅读障碍：本节先讲 Ray 集群地址，随后改讲 QPU Provider，接着回到本地执行器，最后又把默认执行器、随机种子、迭代次数和 shots 放到同一段。执行位置、量子后端和算法参数是三种独立选择，却来回穿插；初学者读完容易不知道换成 QPU 到底该改执行器、命令参数还是程序注册逻辑。

调整方法：将本节按“选择任务执行器→选择量子后端→调整教程参数”组织；把本地线程池及脚本默认值紧跟在 Ray 地址说明后，再讲 QPU，最后单列运行参数。已有命令保留在对应段后。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

先选择任务执行器。本页主流程使用 `--executor ray`：`--address local` 在本机启动 Ray，连接已有集群时使用部署方提供的地址，或在已配置集群的节点上使用 `--address auto`。仅调试函数逻辑时可改为 `--executor local`，通过本地线程池执行；此模式不启动 Ray。教程脚本不带参数时也使用本地执行器。

再选择量子后端。`--backend` 与 `--executor` 独立设置；本教程默认使用 `simulator`。接入 QPU 时，需要先由部署方或用户实现并注册 Provider，再在程序中取得对应的后端对象，参见[接入 QPU 后端](http://127.0.0.1:4321/docs/quantum-backends/#接入-qpu-后端)与[扩展量子后端](http://127.0.0.1:4321/docs/providers/)。经典任务与量子任务仍通过结果引用传递数据。

最后按需要调整计算参数：`--seed` 控制模拟器采样，`--steps 30` 设置迭代上限，`--shots 2048` 设置每次采样次数。

### 11 · 编写混合程序：循环与参数更新

优先调整。页面：[打开文章](http://127.0.0.1:4321/docs/hybrid-programs/)；源码：[编写混合程序 · 循环与参数更新](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/hybrid-programs.md:37)。

原文（相关段落及必要上下文）：

> 驱动程序可以读取结果，根据结果确定下一轮参数，再次提交任务。这适用于变分算法、参数扫描和量子特征计算。
>
> ```python
> with Runtime(executor="ray", address="local") as runtime:
>     backend = runtime.quantum_backend("simulator")
>     for angle in [0.0, 0.5, 1.0]:
>         circuit_ref = runtime.submit(build_circuit, angle)
>         quantum_ref = backend.submit(circuit_ref, shots=4096, seed=7)
>         value_ref = runtime.submit(expectation, quantum_ref)
>         value = runtime.get(value_ref)
>         print(angle, value)
>         runtime.release(circuit_ref, quantum_ref, value_ref)
> ```
>
> 每次 `get()` 都是显式等待点。参数扫描可先提交互不依赖的任务，再读取结果；依赖上次量子结果的参数更新则需要等待。

阅读障碍：开头用“读取结果→确定下一轮参数”引出代码，代码却遍历预先给定的 [0.0, 0.5, 1.0]，没有用 value 更新 angle。结尾才同时提到参数扫描和反馈更新。读者会在代码中寻找不存在的参数更新，并把两种不同依赖结构当成同一个示范。

调整方法：在代码前明确这是固定参数扫描；代码后再解释独立扫描和反馈更新的区别，并将真正的反馈更新指向快速上手。代码可以保留，不需要为了文案改变算法。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

下面先演示固定参数扫描：对预先给定的 `0.0`、`0.5`、`1.0` 分别构造电路、执行采样并计算期望值。这个循环逐次读取并打印结果，各次使用的角度不依赖上一轮输出。

每次 `get()` 都是显式等待点。对互不依赖的参数扫描，可以先提交各次任务，再统一读取结果。若下一轮参数必须根据上一轮量子结果计算，就需要等待该结果后再继续提交；[快速上手](http://127.0.0.1:4321/docs/quickstart/)展示了这种参数反馈流程。

### 12 · 编写混合程序：指定硬件

优先调整。页面：[打开文章](http://127.0.0.1:4321/docs/hybrid-programs/)；源码：[编写混合程序 · 指定硬件](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/hybrid-programs.md:55)。

原文（相关段落及必要上下文）：

> 本页公开 SDK 教程中的经典任务在 CPU 上执行；GPU 计算通过仓库内的应用桥接和 Ray 组件接入，见 [GPU 与异构资源](http://127.0.0.1:4321/docs/gpu-computing/)。量子调用通过后端对象显式选择模拟器或已注册的 QPU Provider；使用 `backend.describe()` 查询声明的比特范围等能力，并按适配器支持的电路范围准备输入。接入方式见[量子后端](http://127.0.0.1:4321/docs/quantum-backends/#接入-qpu-后端)。算法中的数学操作不会因资源声明而自动转成量子电路。

阅读障碍：整段在 CPU SDK 教程、GPU 内部接入、量子后端选择、能力查询、输入电路限制和“不会自动量子化”之间连续切换。标题承诺回答如何指定硬件，但读者没有得到按计算类型分开的入口，反而需自行把每个限制重新归类。

调整方法：围绕用户要安排的经典计算和量子计算分成两段：第一段说明本页 CPU 与 GPU 的入口差别，第二段说明选择量子后端、检查能力和准备电路的顺序。保留 GPU 仅通过仓库应用桥接/Ray 组件接入的范围。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

先安排经典计算。本页公开 SDK 教程中的经典任务在 CPU 上执行；需要 GPU 时，应使用仓库中的应用桥接与 Ray 组件，具体入口和环境要求见 [GPU 与异构资源](http://127.0.0.1:4321/docs/gpu-computing/)。

再安排量子计算。通过后端对象选择模拟器或已注册的 QPU Provider，使用 `backend.describe()` 查看声明的比特范围等能力，再按适配器支持的范围准备电路。算法中的数学操作需要由用户写成电路，资源声明不会自动完成这一步；接入方法见[量子后端](http://127.0.0.1:4321/docs/quantum-backends/#接入-qpu-后端)。

### 13 · 组件与 Actor：显式注册组件

建议调整。页面：[打开文章](http://127.0.0.1:4321/docs/components-actors/)；源码：[组件与 Actor · 显式注册组件](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/components-actors.md:49)。

原文（相关段落及必要上下文）：

> `factory` 是一个无参数的可调用对象。注册不会调用 factory。`execution="task"` 每次调用创建实例并在结束后清理；`"actor"` 复用实例，退出 Runtime 时调用可选的 `close()`。
>
> 业务方法的关键字参数通过 `component.submit("method", kwargs={...})` 传入。构造 Actor 的关键字参数通过 `runtime.actor(..., kwargs={...})` 传入，构造参数须可序列化，不能包含运行时结果引用。

阅读障碍：上一节通过 runtime.actor() 创建 Actor，本节直接给出 ComponentSpec/register 代码，却直到代码后才介绍 task/actor 两种执行方式，也没有先说明这套写法与上一节的关系。解释随后从代码中没有显式命名的 factory 跳到两个不同层面的 kwargs；读者难以先建立“组件定义—实例创建—方法调用”的模型。

调整方法：在代码前加一句说明本节是显式声明组件配置与绑定业务实现；代码后先解释 Accumulator 在 register 中充当 factory，以及执行方式如何决定实例生命周期，最后分开介绍构造参数和方法参数。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

上一节展示直接创建 Actor 的写法。本节使用 `ComponentSpec` 显式声明组件名称、业务方法、执行方式、CPU 配额和超时，再通过 `runtime.register()` 绑定业务实现。

在上面的 `runtime.register(spec, Accumulator)` 中，`Accumulator` 充当工厂，即无参数的可调用对象；注册时不会调用它。选择 `execution="task"` 时，每次方法调用都会创建实例，并在结束后清理；选择 `execution="actor"` 时复用同一个实例，退出 Runtime 时调用可选的 `close()`。

需要向方法传递关键字参数时，使用 `component.submit("method", kwargs={...})`。需要向 Actor 构造函数传递关键字参数时，使用 `runtime.actor(..., kwargs={...})`；这些构造参数须可序列化，不能包含运行时结果引用。

### 14 · 可复用工作流：定义与运行 → 完整教程

优先调整。页面：[打开文章](http://127.0.0.1:4321/docs/workflows/)；源码：[可复用工作流 · 定义与运行 → 完整教程](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/workflows.mdx:29)。

原文（相关段落及必要上下文）：

> 上面的 `build_circuit`、`update_parameter` 是用户函数；下面的完整教程提供可直接运行的实现。`NodeRef` 表示图中的值，执行后 `WorkflowRun.outputs` 才包含可供 `get()` 使用的 `ResultRef`。
>
> <span id="完整示例"></span>
>
> ## 完整教程
>
> 程序重复运行同一个工作流，用 Actor 累积量子结果，最后导出执行记录：

阅读障碍：短片段的主线是构造电路→测量→update_parameter，正文随后承诺完整教程提供这些用户函数的可运行实现。但实际嵌入的 system_workflow.py 没有 update_parameter，而是改用 History Actor 记录概率，并增加两次工作流运行和报告导出。读者以为下文会补齐上文，结果遇到另一套例子，无法一一对照。

调整方法：最好统一短片段与完整程序的同一条计算链。若保留两例，必须在过渡段明确短片段只是结构示意，完整教程换成记录结果的独立程序；同时把 NodeRef/ResultRef 的概念解释独立成段，不夹在源码补齐承诺里。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

上面的片段用于说明工作流的定义和运行方式，其中 `build_circuit`、`update_parameter` 需由应用提供。定义阶段的 `NodeRef` 表示图中的值；执行后，`WorkflowRun.outputs` 中的 `ResultRef` 才能交给 `runtime.get()` 读取。

下面的完整教程使用另一条计算链：构造电路、执行采样，再由 `History` Actor 累积量子结果。程序用不同输入重复运行同一个工作流，最后导出执行记录；它不包含上面片段中的 `update_parameter`。

### 15 · 可复用工作流：复用、失败与释放

建议调整。页面：[打开文章](http://127.0.0.1:4321/docs/workflows/)；源码：[可复用工作流 · 复用、失败与释放](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/workflows.mdx:54)。

原文（相关段落及必要上下文）：

> 算法中的 `for`、`while` 循环，以及依赖结果的条件分支，仍用普通 Python 编写。工作流描述执行依赖；[性能工作量模型](http://127.0.0.1:4321/docs/performance/)是另一个由用户编写的模型，不会自动从图中推断准确计算耗时。

阅读障碍：前文说工作流的图不会出现循环，但“算法循环放在普通 Python 中”直到全文最后、失败和释放之后才解释。这个核心编程模型答案又与性能工作量建模挤在同一段：一个回答循环放在哪里，另一个回答能否预测耗时。读者在“定义与运行”阶段最需要的澄清被延后了。

调整方法：将循环与条件分支说明前移到“定义与运行”，紧跟图不会出现循环的句子；性能预测边界留成独立扩展说明。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

工作流描述一次运行中的任务依赖，节点之间构成无环图。算法中的 `for`、`while` 和依赖结果的条件分支仍写在普通 Python 驱动程序中；需要重复计算时，由驱动程序再次运行工作流。

若还需要预测耗时，应另外编写[性能工作量模型](http://127.0.0.1:4321/docs/performance/)。执行工作流与性能模型是两种描述，系统不会仅从工作流图中自动推断准确计算耗时。

### 16 · GPU 与异构资源：GPU 组件如何执行

建议调整。页面：[打开文章](http://127.0.0.1:4321/docs/gpu-computing/)；源码：[GPU 与异构资源 · GPU 组件如何执行](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/gpu-computing.md:39)。

原文（相关段落及必要上下文）：

> 运行该验证程序前，需要准备 Ray Jobs 服务、带 `CPU_HEAD` 资源标记的 Head、至少一份可分配的 GPU 资源，以及兼容的 GPU 驱动、CUDA 和 PyTorch。该教程的程序还使用仓库测试夹具，必须从完整源码目录运行。提交入口及参数在同目录的 `submit_job.py`；它支持设置服务地址、工作目录、远程 Python 路径、独立作业 ID 和输出目录，并设置 300 秒提交侧超时。
>
> CUDA 不可用时，教程中的程序会明确报错。应根据执行记录中的设备名称、CUDA 可用性和资源分配情况，确认任务是否实际在 GPU 上执行；不能仅凭任务名称或目标配置认定已经使用 GPU。

阅读障碍：一段同时承担环境清单、源码依赖、启动入口、六类可配置参数和超时说明，下一段才开始讲运行验收。读者很难区分“运行前必须满足什么”“从哪里提交”“运行后如何确认”，尤其测试夹具这一前提被夹在环境与参数之间。

调整方法：按实际操作顺序拆成准备环境、提交程序、核验执行三步；将完整源码与测试夹具归入准备阶段，把提交选项和 300 秒超时留在入口说明中。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

运行前先准备 Ray Jobs 服务、带 `CPU_HEAD` 资源标记的 Head，以及至少一份可分配的 GPU 资源。执行节点还需具备兼容的 GPU 驱动、CUDA 和 PyTorch。此程序依赖仓库测试夹具，因此必须从完整源码目录运行。

准备完成后，使用同目录的 `submit_job.py` 提交。该入口可设置服务地址、工作目录、远程 Python 路径、独立作业 ID 和输出目录；提交侧超时为 300 秒。

运行后，检查执行记录中的设备名称、CUDA 可用性和资源分配情况，以确认任务实际使用了 GPU。CUDA 不可用时程序会报错；任务名称或目标配置本身不能证明 GPU 已参与执行。

### 17 · GPU 与异构资源：目标配置与实际执行

建议调整。页面：[打开文章](http://127.0.0.1:4321/docs/gpu-computing/)；源码：[GPU 与异构资源 · 目标配置与实际执行](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/gpu-computing.md:62)。

原文（相关段落及必要上下文）：

> 工作台的 GPU 目标配置用于选择应用支持的资源或预测场景；实际后端由部署模式和任务提交路径决定。默认本地数值模式会在 CPU 上执行，资源列表中的 GPU 型号不能证明本次任务使用了 GPU。
>
> [水分子动力学模拟工作台教程](http://127.0.0.1:4321/docs/aimd/)保留已采集的 CPU/QPU 目标配置与 CPU 数值模拟截图。历史 GPU 运行结果按其原始记录保留；不能直接将目标硬件的预测耗时与其他后端实测耗时之间的差异视为预测误差。

阅读障碍：两段依次切换工作台目标配置、部署模式、CPU 默认执行、某次 AIMD 截图、历史 GPU 结果和预测误差。读者尚未分清“目标配置”和“本次后端”，就被带到历史记录与误差比较；“历史 GPU 运行结果”也没有在本段说明与教程截图的关系。边界虽然齐全，但缺少一条按证据解释结果的顺序。

调整方法：先说明怎样判定本次实际后端，再以教程截图和历史数据说明来源，最后说明预测与实测如何比较。保留 CPU/QPU 目标配置、CPU 数值模拟及历史记录原样保留的界限。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

工作台中的 GPU 目标配置用于选择应用支持的资源或预测场景。本次任务究竟在哪个后端运行，取决于部署模式和提交路径，需要结合执行记录判断。默认本地数值模式在 CPU 上执行，因此资源列表中出现 GPU 型号，并不能证明本次使用了 GPU。

[水分子动力学模拟工作台教程](http://127.0.0.1:4321/docs/aimd/)中的目标配置为 CPU/QPU，截图记录的是 CPU 数值模拟。历史 GPU 运行结果则按各自的原始记录保留；解释具体结果时，应先确认它对应的来源和实际后端。

比较预测与实测前，也要确认两者对应的硬件和后端。目标硬件的预测耗时与另一后端的实测耗时之差，不能直接作为预测误差。

### 18 · 量子后端：支持的电路

建议调整。页面：[打开文章](http://127.0.0.1:4321/docs/quantum-backends/)；源码：[量子后端 · 支持的电路](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quantum-backends.md:35)。

原文（相关段落及必要上下文）：

> 可以提交已绑定参数的 `QuantumCircuit`，也可以提交上游任务的结果引用；该任务的返回值须为已绑定参数的 `QuantumCircuit`。`pivotq.QuantumCircuit` 直接复用 Qiskit 原始类型，已有的 Qiskit 电路同样兼容；电路、参数、编译与序列化入口见[电路 API](http://127.0.0.1:4321/docs/api/quantum/#电路构造与参数)。标准幺正门与可分解的幺正电路可被模拟；支持末尾的全量、部分及置换测量。
>
> 当前不支持中途测量、reset、initialize、经典条件、控制流和未绑定参数。使用 `assign_parameters()` 绑定参数，再提交电路。执行不会修改输入电路；提交后直到任务完成，请勿修改同一个电路对象。
>
> 实际 QPU 支持的门集、连接关系和编译方式由设备及其 Provider 决定。通过公共电路校验不代表任意设备都可以执行该电路；Provider 还需完成设备适配与检查。

阅读障碍：这三段把输入对象类型、上游引用、Qiskit 兼容性、模拟器可支持的操作、公共拒绝条件、提交后的对象生命周期，以及真实设备能力连续放在一起。主要障碍不是术语多，而是规则所属层次不清：读者要到最后才知道，前面的公共校验和模拟器范围并不等于目标 QPU 的可执行范围。

调整方法：按“提交什么→公共限制与对象使用→模拟器和 QPU 各自范围”分层，明确每组规则的适用对象；电路 API 链接放在输入兼容性说明旁。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

提交输入可以是已绑定参数的 `QuantumCircuit`，也可以是上游任务的结果引用；后者最终须返回已绑定参数的 `QuantumCircuit`。`pivotq.QuantumCircuit` 复用 Qiskit 原始类型，因此已有 Qiskit 电路同样兼容。电路、参数、编译与序列化入口见[电路 API](http://127.0.0.1:4321/docs/api/quantum/#电路构造与参数)。

提交前，请用 `assign_parameters()` 绑定全部参数。当前公共接口不支持中途测量、reset、initialize、经典条件、控制流和未绑定参数。执行不会修改输入电路；提交后直到任务完成，请勿修改同一个电路对象。

模拟器支持标准幺正门、可分解的幺正电路，以及末尾的全量、部分和置换测量。实际 QPU 的门集、连接关系与编译方式则由设备及 Provider 决定；通过公共电路校验后，仍需通过适配器的设备检查。

### 19 · 量子后端：接入 QPU 后端

建议调整。页面：[打开文章](http://127.0.0.1:4321/docs/quantum-backends/)；源码：[量子后端 · 接入 QPU 后端](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/quantum-backends.md:61)。

原文（相关段落及必要上下文）：

> 这里的 `provider_factory`、`capabilities` 和配置来自实际适配器；SDK 不会仅凭设备名称自动完成接入。`BackendCapabilities` 声明最小/最大比特数、是否模拟和是否支持采样种子；`backend.describe()` 返回这些静态信息。
>
> 注册与创建后端不构造 Provider，也不连接量子设备。提交后，运行时在执行进程中构造实例并调用 `run()`；电路也可以来自上游 CPU 任务引用。读取结果统一使用 `runtime.get(backend.submit(circuit, shots=1024))`。
>
> Provider 负责原生门编译、物理布局还原及结果读取；SDK 负责保留末尾测量映射并生成统一的 `QuantumResult`。若需在不同测量基下测量，用户须先在电路中加入相应的基变换。

阅读障碍：代码后的说明没有沿注册→创建→提交→读取的顺序推进：能力字段介绍后进入延迟构造，中途又插入 CPU 引用和嵌套 get 调用，再转到 Provider/SDK 分工，最后突然讲测量基。读者容易把静态能力描述、设备连接时机和电路准备责任混为同一个接入步骤。

调整方法：依照真实生命周期重排；先交代适配器提供的工厂、能力和配置，再说明注册/创建不连接设备及提交时的工作，最后说明结果如何分工处理。测量基要求移到“测量与位序”作为电路准备说明。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

先从实际适配器取得 `provider_factory`、`capabilities` 和连接配置。`BackendCapabilities` 声明最小/最大比特数、是否模拟以及是否支持采样种子；注册后可通过 `backend.describe()` 读取这些静态信息。SDK 不会仅凭设备名称自动完成接入。

注册与创建后端不构造 Provider，也不连接量子设备。提交任务后，运行时才在执行进程中构造 Provider 实例并调用 `run()`。提交的电路也可以来自上游 CPU 任务的结果引用。

执行过程中，Provider 负责原生门编译、物理布局还原和结果读取；SDK 保留用户的末尾测量映射，并生成统一的 `QuantumResult`。结果可统一通过 `runtime.get(backend.submit(circuit, shots=1024))` 取回。

若需要在不同测量基下测量，请在提交前自行将相应的基变换加入电路。

### 20 · 硬件性能模型：CPU 与 QPU

优先调整。页面：[打开文章](http://127.0.0.1:4321/docs/hardware-profiles/)；源码：[硬件性能模型 · CPU 与 QPU](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/hardware-profiles.md:35)。

原文（相关段落及必要上下文）：

> CPU 任务若提供已知的 `duration_seconds`，无需填写计算速率，且不能同时传入 `ops`。按运算量或内存量建模时，需要提供对应速率。正的耗时、提交延迟和链路延迟向上取整到整数微秒。QPU 的 shot_rate 合并采集、测量和复位阶段，不等于量子门时钟频率。
>
> `memory_bandwidth_gbps_per_node` 的 Gb/s 表示十亿**比特**每秒；例如，以 1 Gb/s 的带宽传输 1 GB 数据，理想传输耗时为 8 秒。按运算量/内存量计算的 CPU 模型还包含当前引擎固有的 20 微秒开销；显式指定 duration 时，使用用户给定的耗时。

阅读障碍：这两段按“CPU 输入方式→所有模型的时间取整→QPU shot_rate→CPU 内存带宽→CPU 固有开销”来回切换。读者刚建立 CPU 的两种建模方式，就被时间精度和 QPU 打断；到下一段末尾才得知 20 微秒开销只属于其中一种方式。硬件速率与工作量输入的配对关系也因此不够直观。

调整方法：把 CPU 的两种输入方式和相应开销讲完，再解释 CPU 带宽单位；另起一段定义 QPU 的有效采样速率，最后统一说明所有时间参数的取整规则。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

CPU 任务可以按已知耗时建模，也可以按运算量或内存量建模。使用 `duration_seconds` 时，无需填写计算速率，且不能同时传入 `ops`；模型使用用户给定的耗时。按运算量或内存量建模时，需要在硬件配置中提供对应速率，这类 CPU 模型还包含当前引擎固有的 20 微秒开销。

CPU 的 `memory_bandwidth_gbps_per_node` 以 Gb/s 为单位，即十亿**比特**每秒。例如，以 1 Gb/s 的带宽传输 1 GB 数据，理想传输耗时为 8 秒。

QPU 的 `shot_rate` 表示合并采集、测量和复位阶段后的有效采样速率，不等于量子门时钟频率。

模型的计时精度为整数微秒：正的耗时、提交延迟和链路延迟都会向上取整。

### 21 · 性能预测：描述工作量

建议调整。页面：[打开文章](http://127.0.0.1:4321/docs/performance/)；源码：[性能预测 · 描述工作量](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/performance.mdx:27)。

原文（相关段落及必要上下文）：

> 以上时间与速率是教程采用的假设值。`preview()` 校验图、硬件与编译结果，不启动原生模拟器、不写入文件。`cpu()` 可用已知时间或运算量/内存量，`qpu()` 描述电路宽度、shots 与电路数量；`transfer()` 描述显式通信。相关单位见[硬件性能模型](http://127.0.0.1:4321/docs/hardware-profiles/)。

阅读障碍：代码同时定义了工作量、目标硬件并调用 preview，但说明段落先讲假设值，再讲校验方法，最后才解释最早出现的 cpu/qpu/transfer。读者必须倒回代码，自己拼出“工作量说明做多少事，硬件说明做得多快，preview 只校验输入”的关系。

调整方法：代码前先交代本例的依赖链以及工作量和硬件分别负责什么；代码后再解释 preview 的作用和假设值。避免把各 API 的定义集中放在整段代码之后。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

本例描述一条“CPU 准备输入 → QPU 执行电路 → CPU 更新”的依赖链。工作量用 `cpu()` 描述已知耗时或运算量、内存量，用 `qpu()` 描述电路宽度、shots 和电路数量；需要建模通信时，再用 `transfer()` 显式描述传输。

`Hardware` 为这份工作量提供目标 CPU 和 QPU 参数。示例中的时间与速率都是教程采用的假设值，相关单位见[硬件性能模型](http://127.0.0.1:4321/docs/hardware-profiles/)。

定义工作量和硬件后，调用 `preview()` 校验图、硬件与编译结果。这一步不启动原生模拟器，也不写入文件。

### 22 · 性能预测：完整对比教程

优先调整。页面：[打开文章](http://127.0.0.1:4321/docs/performance/)；源码：[性能预测 · 完整对比教程](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/performance.mdx:60)。

原文（相关段落及必要上下文）：

> 教程中的程序比较用户提供的纯 CPU 模型、CPU/QPU 模型和另一种 QPU 吞吐配置。完整教程代码如下：

阅读障碍：这一句直接引出 46 行完整程序，只说比较三种模型，却没有说明哪两项只改变硬件、哪一项连工作量模型也不同。读者要自行追踪 cpu_workload、workload 和 replace 才能看懂比较逻辑；关于质量等价未验证的说明又在整段代码之后，容易先把 cpu_reference 当成可直接比较的同质量基线。

调整方法：在完整代码前用三项短说明交代配置名和变化轴，明确 CPU 参考项是独立填写的模型，另外两项才是同一工作量下改变 QPU 吞吐；将质量等价限定随这组比较一起说明。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

这个教程分别预测三个由用户提供的配置：

- `cpu_reference`：独立描述的纯 CPU 模型，将经典算法耗时设为 0.25 秒。
- `cpu_qpu`：CPU 准备输入耗时 0.002 秒，随后执行量子阶段，再由 CPU 用 0.001 秒完成更新。QPU 的默认 `shot_rate` 为 10000，提交延迟为 0.001 秒。
- `faster_qpu`：沿用 `cpu_qpu` 的工作量，仅将 QPU 的 `shot_rate` 提高到两倍。

教程采用假设的时间与速率，其中 QPU 吞吐未经过真机测量。纯 CPU 与 CPU/QPU 模型也没有验证算法质量等价，输出中的 `quality_equivalence_verified` 因而为 `False`；预测耗时只能结合这些假设解读。完整教程代码如下：

### 23 · 性能预测：结果边界

建议调整。页面：[打开文章](http://127.0.0.1:4321/docs/performance/)；源码：[性能预测 · 结果边界](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/performance.mdx:66)。

原文（相关段落及必要上下文）：

> 当前模型不覆盖量子噪声、门深度与路由开销、外部设备排队和科学精度。`quality_equivalence_verified=False` 表示未验证对比算法的质量等价。阶段任务可能重叠，阶段耗时总和不一定等于整体时延。
>
> CPU 数值模拟的实测速度、性能模型预测的目标 QPU 速度和真实设备测量必须分别标注。应用所用的工作台预测入口仍受其应用模型限制，SDK 的通用预测接口不代表网页已经支持任意 Python 程序。

阅读障碍：最后两段连续放入物理模型缺项、算法质量等价、并行阶段计时、数据来源标注、工作台入口范围五类问题。前四项分别影响不同的结果解读，最后一项却返回产品入口能力，阅读主线突然跳转。限定内容本身必要，但集中在页尾使读者不容易把每项限定对应到前面的用法。

调整方法：模型缺项和算法质量限定放在比较教程旁；阶段耗时重叠的规则并入 PredictionResult 的指标解释；实测/预测标注紧随结果说明；工作台入口范围移到开头的接口适用范围。若保留集中说明，至少按“模型范围、结果解读、入口范围”分开。与上一条的改写合并时，质量等价说明只保留一处。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

模型范围：当前预测不覆盖量子噪声、门深度与路由开销、外部设备排队和科学精度。`quality_equivalence_verified=False` 表示未验证对比算法的质量等价。

结果解读：阶段任务可能重叠，因此阶段耗时之和不一定等于整体时延。展示结果时，还须分别标明 CPU 数值模拟的实测速度、性能模型预测的目标 QPU 速度，以及真实设备的测量结果。

入口范围：本页介绍 SDK 的通用预测接口。工作台的预测入口仍受具体应用模型限制，网页尚不能因此被视为支持任意 Python 程序的预测。

### 24 · 扩展量子后端：注册与创建

优先调整。页面：[打开文章](http://127.0.0.1:4321/docs/providers/)；源码：[扩展量子后端 · 注册与创建](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/providers.mdx:24)。

原文（相关段落及必要上下文）：

> 执行时通过 `MyProvider(**config)` 构造实例。注册与创建后端时均不会创建 `MyProvider` 实例，也不会连接设备；执行进程首次调用工厂函数时才创建实例。配置须可序列化，并在创建后端时生成独立快照。
>
> 注册属于当前 Runtime，名称不能重复或覆盖已有后端。`backend.describe()` 返回注册时提供的静态能力，不探测设备。

阅读障碍：段落从“执行时构造实例”开始，接着退回“注册与创建后端时”，再跳到“执行进程首次调用工厂函数时”，最后又回到创建后端时的配置快照。第二段再补注册范围和 describe。时间顺序反复倒转，而“创建后端”与“创建 Provider 实例”是两个不同动作，容易被读成前后矛盾。

调整方法：按注册、创建后端对象、执行三个阶段顺序讲。把配置快照和 describe 与后端对象放在一起，再明确 Provider 实例何时才出现。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

注册只在当前 Runtime 中生效，名称不能重复，也不能覆盖已有后端。注册时不会创建 `MyProvider` 实例或连接设备。

调用 `runtime.quantum_backend()` 创建后端对象时，SDK 会为配置生成独立快照，因此配置必须可序列化。这一步仍不会创建 `MyProvider` 实例或连接设备。`backend.describe()` 返回注册时提供的静态能力，不探测设备。

真正执行任务时，执行进程首次调用工厂函数，才会通过 `MyProvider(**config)` 创建 Provider 实例。

### 25 · 扩展量子后端：Provider 协议

优先调整。页面：[打开文章](http://127.0.0.1:4321/docs/providers/)；源码：[扩展量子后端 · Provider 协议](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/providers.mdx:38)。

原文（相关段落及必要上下文）：

> 输入电路是已绑定参数、去掉末尾测量的独立副本。Provider 负责把它编译到设备门集并读取**所有逻辑量子位**。结果位串必须为 `q[n-1]…q0`，不含寄存器分隔空格；设备路由后的物理布局和厂商位序由 Provider 还原。
>
> SDK 保存用户原始测量映射，统一处理部分测量、位重排和未写入的经典位。Provider 不需要重复实现这些逻辑。首版不支持中途测量、动态控制、reset 或 initialize。

阅读障碍：第一段要求 Provider 还原物理布局和厂商位序，第二段又说 SDK 统一处理位重排。两项职责都正确，但没有先区分“设备物理位→电路逻辑量子位”和“逻辑量子位→用户经典测量位”这两个层次，读者可能认为 Provider 与 SDK 在重复处理同一件事。输入、设备执行、结果恢复的过程也被拆在不同句子里。

调整方法：沿数据经过 SDK→Provider→SDK 的顺序重写，每一步明确输入和输出，以及负责哪一层映射；把不支持的电路操作单列。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

SDK 保存用户原始测量映射，并将已绑定参数、去掉末尾测量的电路独立副本交给 Provider。

Provider 负责把电路编译到设备门集，并读取**所有逻辑量子位**。返回结果前，Provider 需要还原设备路由后的物理布局和厂商位序，使结果位串按逻辑量子位排列为 `q[n-1]…q0`，且不含寄存器分隔空格。

收到这个完整逻辑位结果后，SDK 再依据用户原始测量映射，处理部分测量、位重排和未写入的经典位。Provider 不需要重复实现这一步。

首版不支持中途测量、动态控制、reset 或 initialize。

### 26 · 扩展量子后端：结果校验与故障

建议调整。页面：[打开文章](http://127.0.0.1:4321/docs/providers/)；源码：[扩展量子后端 · 结果校验与故障](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/providers.mdx:48)。

原文（相关段落及必要上下文）：

> 确认请求尚未提交时，输入问题使用 `pivotq.errors.ValidationError`；请求可能已经执行但响应丢失时，使用 `ResultUnknownError` 并保留设备作业标识。真实设备 Provider 的未分类异常或无效结果也按“执行状态未知”处理；供核实的信息会随依赖关系传递给后续 CPU 任务。SDK 不自动重试或回退模拟器。

阅读障碍：一个段落同时给出两种错误分类、真实设备的兜底规则、作业信息的依赖传播，以及禁止自动重试/回退。最重要的判断依据——请求是否可能已经提交执行——藏在两个长条件句里；后续“供核实的信息”也要回读才能知道指哪一类故障。

调整方法：先明确按提交状态分类，再用两项说明异常类型；把真实设备的兜底规则接在未知状态分支下，最后统一交代故障传播和恢复策略。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

Provider 应根据请求是否可能已提交执行来报告错误：

- 能确认请求尚未提交时，输入问题使用 `pivotq.errors.ValidationError`。
- 请求可能已经执行、但响应丢失时，使用 `ResultUnknownError`，并保留设备作业标识。真实设备 Provider 的未分类异常或无效结果，也按“执行状态未知”处理。

出现执行状态未知的故障后，供核实的信息会沿依赖关系传递给后续 CPU 任务。SDK 不会自动重试，也不会回退到模拟器。

### 27 · 组件与 Actor：actor

建议调整。页面：[打开文章](http://127.0.0.1:4321/docs/api/components/)；源码：[组件与 Actor · actor](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/components.md:49)。

原文（相关段落及必要上下文）：

> 默认同一实例串行执行。需要保证状态更新之间的依赖时，应显式传递前次结果；工作流会为绑定到同一串行 Actor 的节点补充构图顺序依赖。

阅读障碍：同一段先说“默认串行”，紧接着又要求“显式传递前次结果”，却没有解释串行与依赖顺序有什么区别。随后转入工作流自动补依赖，又没有点明它与普通调用的区别。读者必须自行判断：前一句是否已经保证更新顺序、什么情况下需要手工连依赖。问题在三种执行约定的关系，而不是术语本身。

调整方法：先解释串行约束的含义，再把普通调用与 Workflow 的依赖处理分开说明。将“同时执行数量”和“状态更新先后关系”明确连接起来。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

同一 Actor 实例默认串行执行，即同一时刻只执行一个方法。若后一次调用必须基于前一次更新后的状态，应显式传递前一次调用的结果引用，建立两次调用之间的依赖。

使用工作流时，框架会为绑定到同一串行 Actor 的节点按构图顺序补充依赖。

### 28 · Provider 协议：BackendCapabilities → QuantumRequest → ProviderResult

建议调整。页面：[打开文章](http://127.0.0.1:4321/docs/api/providers/)；源码：[Provider 协议 · BackendCapabilities → QuantumRequest → ProviderResult](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/providers.md:38)。

原文（相关段落及必要上下文）：

> 该声明用于提交前校验，并不表示设备当前在线。当前协议接收已绑定的幺正电路及末尾测量，SDK 统一处理测量映射。
>
> ## QuantumRequest
>
> | 字段 | 含义 |
> | --- | --- |
> | `circuit` | 独立的 Qiskit 电路副本，已绑定参数并去掉末尾测量 |
> | `shots` | 请求的重复次数 |
> | `seed` | 模拟采样种子；未指定时为 `None` |
> | `request_id` | 本次调用的稳定标识，建议关联远端作业记录 |
>
> 由 SDK 创建并传入 `run`。Provider 执行电路后，返回全部逻辑量子位的 Z 测量分布；设备编译导致的布局置换需由 Provider 还原。

阅读障碍：能力小节说协议接收“末尾测量”，紧接着 QuantumRequest 字段表又说电路已“去掉末尾测量”；之后要求 Provider 返回全部逻辑量子位的 Z 测量分布，到 ProviderResult 才说明 SDK 将其转换为用户请求的分布。SDK 与 Provider 各自负责哪一步被拆成多处，读者需要来回拼接，才能理解“接收末尾测量”和“传入无测量电路”并不矛盾。这是协议流程缺少总述，不是必要字段太多。

调整方法：在 QuantumRequest 表前交代 SDK 保存测量映射、剥除测量和调用 Provider 的顺序；表后接 Provider 返回完整逻辑位分布、SDK 恢复用户测量映射的后半程。ProviderResult 小节保留位序与数值校验细节即可，避免再零散重述这条流程。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

能力声明用于提交前校验，并不表示设备当前在线。

## QuantumRequest

用户提交的电路须已绑定参数，可包含幺正操作和末尾测量。SDK 会保存测量映射，移除末尾测量，并将电路副本封装为 `QuantumRequest`，传给 Provider 的 `run` 方法。

| 字段 | 含义 |
| --- | --- |
| `circuit` | 独立的 Qiskit 电路副本，已绑定参数并去掉末尾测量 |
| `shots` | 请求的重复次数 |
| `seed` | 模拟采样种子；未指定时为 `None` |
| `request_id` | 本次调用的稳定标识，建议关联远端作业记录 |

Provider 执行电路后，须返回全部逻辑量子位的 Z 测量分布；若设备编译改变了量子位布局，Provider 需先还原该置换。SDK 再按保存的测量映射，将完整分布转换为用户请求的测量分布。

### 29 · 集群作业：JobSpec

优先调整。页面：[打开文章](http://127.0.0.1:4321/docs/api/jobs/)；源码：[集群作业 · JobSpec](/Users/siwei/Developer/codex_project/PivotQ/website/src/content/docs/docs/api/jobs.md:28)。

原文（相关段落及必要上下文）：

> Driver 和 Worker 需要安装相同版本的 `pivotq`。保留作业入口 `python -m pivotq.jobs.driver`。

阅读障碍：前面的 entrypoint 参数表让用户填写自己的程序（例如 python main.py），这里却突然要求“保留作业入口 python -m pivotq.jobs.driver”。段落没有交代这是谁的入口、与 entrypoint 的关系，也没有说明“保留”是兼容性说明还是用户应遵循的调用要求；再与 Driver/Worker 版本要求并列，容易让读者误以为每个作业都必须改用该命令。对应教程末尾其实已区分现有应用 Driver 的兼容入口与普通程序入口，API 页丢失了这层关系。

调整方法：将环境前提和入口兼容性拆为两个段落；先明确 entrypoint 指向用户程序，再把 pivotq.jobs.driver 限定为现有应用 Driver 的兼容启动入口。

整段建议稿（涉及位置调整时，段落应随相应代码或图移动）：

Driver 和 Worker 需要安装相同版本的 `pivotq`。

普通用户程序在 `entrypoint` 中填写自己的启动命令，例如 `["python", "main.py"]`。`python -m pivotq.jobs.driver` 仍作为现有应用 Driver 的兼容启动入口保留。

## 阅读覆盖与核对

当前站点的 32 个路由均已抓取：31 个内容页返回 HTTP 200，404 页面返回预期 HTTP 404。已按内容目录与页面文件核对覆盖；每条引用均与当前源文件及对应页面正文匹配。文内特别涉及的固定参数扫描、工作流完整示例与性能对比代码也已复读。

下列“未单列问题”表示本轮未发现需要提出的段落组织问题。

| 页面 | 本轮条数 | 阅读结果 |
| --- | ---: | --- |
| [首页](http://127.0.0.1:4321/) | 0 | 已通读，未单列问题 |
| [文档总览](http://127.0.0.1:4321/docs/) | 1 | 已逐条列出 |
| [水分子动力学模拟](http://127.0.0.1:4321/examples/aimd/) | 4 | 已逐条列出 |
| [量子随机存储器](http://127.0.0.1:4321/examples/qram/) | 2 | 已逐条列出 |
| [水分子动力学模拟工作台教程](http://127.0.0.1:4321/docs/aimd/) | 2 | 已逐条列出 |
| [安装 PivotQ](http://127.0.0.1:4321/docs/installation/) | 0 | 已通读，未单列问题 |
| [快速上手](http://127.0.0.1:4321/docs/quickstart/) | 1 | 已逐条列出 |
| [常见问题](http://127.0.0.1:4321/docs/troubleshooting/) | 0 | 已通读，未单列问题 |
| [经典任务](http://127.0.0.1:4321/docs/classical-tasks/) | 0 | 已通读，未单列问题 |
| [编写混合程序](http://127.0.0.1:4321/docs/hybrid-programs/) | 2 | 已逐条列出 |
| [组件与 Actor](http://127.0.0.1:4321/docs/components-actors/) | 1 | 已逐条列出 |
| [可复用工作流](http://127.0.0.1:4321/docs/workflows/) | 2 | 已逐条列出 |
| [GPU 与异构资源](http://127.0.0.1:4321/docs/gpu-computing/) | 2 | 已逐条列出 |
| [量子后端](http://127.0.0.1:4321/docs/quantum-backends/) | 2 | 已逐条列出 |
| [集群作业](http://127.0.0.1:4321/docs/jobs/) | 0 | 已通读，未单列问题 |
| [状态与执行报告](http://127.0.0.1:4321/docs/observability/) | 0 | 已通读，未单列问题 |
| [硬件性能模型](http://127.0.0.1:4321/docs/hardware-profiles/) | 1 | 已逐条列出 |
| [性能预测](http://127.0.0.1:4321/docs/performance/) | 3 | 已逐条列出 |
| [扩展量子后端](http://127.0.0.1:4321/docs/providers/) | 3 | 已逐条列出 |
| [API 参考](http://127.0.0.1:4321/docs/api/) | 0 | 已通读，未单列问题 |
| [运行时与结果引用](http://127.0.0.1:4321/docs/api/runtime/) | 0 | 已通读，未单列问题 |
| [组件与 Actor](http://127.0.0.1:4321/docs/api/components/) | 1 | 已逐条列出 |
| [工作流](http://127.0.0.1:4321/docs/api/workflows/) | 0 | 已通读，未单列问题 |
| [量子后端与结果](http://127.0.0.1:4321/docs/api/quantum/) | 0 | 已通读，未单列问题 |
| [Provider 协议](http://127.0.0.1:4321/docs/api/providers/) | 1 | 已逐条列出 |
| [集群作业](http://127.0.0.1:4321/docs/api/jobs/) | 1 | 已逐条列出 |
| [执行报告](http://127.0.0.1:4321/docs/api/observability/) | 0 | 已通读，未单列问题 |
| [性能模型与预测](http://127.0.0.1:4321/docs/api/performance/) | 0 | 已通读，未单列问题 |
| [异常类型](http://127.0.0.1:4321/docs/api/errors/) | 0 | 已通读，未单列问题 |
| [应用教程介绍](http://127.0.0.1:4321/docs/examples/) | 0 | 已通读，未单列问题 |
| [PivotQ 系统介绍](http://127.0.0.1:4321/docs/architecture/) | 0 | 已通读，未单列问题 |
| [404](http://127.0.0.1:4321/404/) | 0 | 已通读，未单列问题 |

本轮建议保留 CPU/GPU/QPU 的实际支持范围、目标配置与实际后端的区别、模型与归档来源、数值和 API 标识。重组的目标是让这些信息在读者需要时出现。
