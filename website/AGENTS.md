# 门户网站维护约定

- PivotQ 的定位是量超智融合系统，协同经典 CPU、GPU 加速与量子 QPU。用户指定计算资源和任务依赖，框架据此组织执行；不得再将系统范围限定为 CPU/QPU 或写成不包含 GPU。
- 门户使用 website-flow 的蓝色工作流设计，交付与部署位置是 PivotQ 仓库的 `website/`。独立源码包目录可叫 `website-flow/`；仓库发布始终构建 `website/dist/`。不回写旧 `intro-website/site/`。
- 水分子 AIMD 是一个应用示例，不是框架的通用组成模块。通用编程能力与应用模型、数据及科学验收条件分别描述。
- 系统层面的 GPU 能力来自内部 Ray 资源声明和应用桥接。公开 `pivotq` SDK 当前的任务、组件与 Actor 资源参数只暴露 `num_cpus`；不可编造 `Runtime.submit(..., num_gpus=...)` 或公开 `ComponentSpec(num_gpus=...)`。实际 GPU 运行需要支持的后端、GPU 资源与 CUDA 环境。
- GPU 性能模型在 `packages/perf-sim` 中；公开 `pivotq.performance` 的 Hardware/Workload 当前只暴露 CPU/QPU/通信建模，不可编造 GPUProfile 或 Workload.gpu。预测依赖应用提供工作量，不能自动从任意 Python 程序推断。
- 首页使用用户提供的 `src/assets/hero-lab.png`，不得声称照片中的设备属于 PivotQ、代表现有部署或产生页面数据。
- `HardwareArchitecture.astro` 与 `hardware-scene.ts` 展示可旋转的 CPU/GPU/QPU 互联架构。首页 01 的四段代码围绕 `applications/h2o-hybrid-aimd/`：第一段 CPU 读取原子坐标、差分求力并推进轨迹，第二段 QPU 阶段运行电路取得量子特征，第三段 GPU 上的经典模型用特征预测势能，第四段由 CPU 提交整项作业。运行中的依赖顺序是 CPU 准备输入 → QPU 产生特征 → GPU 预测势能 → CPU 根据受力更新位置。页面展示应用中的关键步骤，不提交任务；这些片段不能直接拼接为完整程序。
- 三维造型与线缆不代表实际机型、部署、接线、带宽或性能。鼠标拖拽与设备标签支持旋转，滚轮/双指不缩放；画布聚焦后按 Home 键恢复初始视角。WebGL 不可用时保留 `public/images/hardware-render-poster.webp` 与文字标签，尊重减少动态效果设置。
- 首页“编程仿真工作流”在混合程序、选择设备、任务编排后分成真机执行与离散事件仿真两条路径，汇入同一张“真机/仿真性能报告”卡，列出各任务运行时间、运行节点、运行指令顺序、运行复杂度；任务编排、执行分析与报告节点高亮，不保留阶段选项卡。静态门户不提交计算任务，实际工作台位于 `dashboard/`。首页规模文案来自用户 2026-10-05 提供的修改意见，本次页面修改不构成规模性能的独立测量或验证。
- 顶部及页脚的文档导航统一叫“文档”，不保留顶部“系统”入口。文档保留“系统介绍”“使用文档”“应用教程”分类；使用文档按入门、混合编程、运行与管理、性能建模与预测、后端扩展及分模块 API 参考组织。文档侧栏的所有层级分组固定完全展开，组标题不提供折叠箭头或展开/收起交互；移动端保留整个目录的打开/关闭入口。“应用教程”包含“介绍”“水分子动力学模拟”“量子随机存储器”三个入口；后两项直接进入对应教程页。
- 网站用户可见文案统一使用“教程”，覆盖导航、页脚、标题、正文和无障碍名称；保留原有 `examples/` 路径与历史锚点兼容。
- 水分子动力学模拟工作台教程保持独立 `/docs/aimd/` 页面，入口保留在首页及教程中，不在文档总览、文档侧边栏或文档页脚推广，也不混入 SDK 文档的自动上下页序列。教程正文唯一维护在 `src/content/guide/aimd.md`，保留六张截图。
- 文档里的 GPU 支持与具体教程的实际配置分别说明。水分子动力学模拟教程使用 CPU/QPU 目标配置，截图实际运行采用 CPU 数值模拟；首页的 GPU/QPU 应用路径不属于那次运行，不得写成 GPU 或 QPU 实测。`qhai.tasks` 是工作台配置语法，公开 SDK 使用 `import pivotq`。
- 快速上手以真实 Ray 调度为主，命令显式选择 Ray；未连接 QPU 时仅量子电路采用 CPU 模拟。本地线程池只是调试选项，不把它称为 Ray 调度。
- QPU 文档使用通用量子后端与 Provider 接口，不恢复历史实验室专用后端或固定三比特设备限制。应用电路规模按算法实际情况描述。
- 区分目标硬件预测耗时与实际后端实测耗时。历史 GPU 字段按原始数据保留；导入 AIMD 轨迹未记录后端时明确未知，回放不重新计算，来源与单位见 `public/aimd/README.md`。
- QRAM 页面与 `src/lib/qram_query.py` 通过 PivotQ 构造电路、使用 Qiskit Statevector 进行本地理想态矢量模拟，存储位为假设数据，不代表 QRAM 真机或 PivotQ 在线应用。
- 使用 Node.js 24 与 `npm ci`。开发默认根路径 `127.0.0.1:4321`，已被占用时通过 `--port` 使用空闲端口，不终止其他服务。
- GitHub Pages 使用 `SITE_URL=https://janusq.github.io` 和 `SITE_BASE=/PivotQ/`；发布预览与浏览器回归必须保持相同子目录。正式域名由 SITE_URL 指定，子路径由 SITE_BASE 指定。
- `.github/workflows/website.yml` 对 PR 仅验证，main 推送或 main 手动运行才部署。Pages Source 需为 GitHub Actions，使用平台部署身份；未经 Actions 与公网访问核验，不宣称已上线。
- 当前迁移中提交与推送由用户执行，不代为 `git add`、`git commit`、`git push`。保留工作区已有改动。
- 门户代码优先从 `pivotq` 或 `pivotq.circuit` 导入已有封装：电路、参数、寄存器、编译及序列化。尚未封装的工具（如 `qiskit.quantum_info.Statevector`）保留原导入，不编造 PivotQ API；同步网页代码、可下载源码及独立源码副本。

- 网站展示名称统一使用“水分子动力学模拟”和“量子随机存储器”；原有 `aimd`、`qram` 路径、源码标识与历史截图保留。
