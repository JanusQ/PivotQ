# 水分子 AIMD 静态展示材料

本目录保存预先生成的轨迹、历史运行记录和电路示例源码。AIMD 页的“重新播放”只回放已有 CSV，不会提交或重新执行计算任务。下面两组轨迹分别保存，不能混用它们的指标或硬件记录。

## 当前页面播放的导入轨迹

- 页面实际读取 `imported/md_log.csv` 与 `imported/positions.csv`，由浏览器生成动力学曲线和三维轨迹。
- 两文件于 2026-10-02 入库，提交为 `90889f947c0591d64ef2426cd350adef52053179`。现有归档未附原始运行编号或执行后端记录，不能确认其 CPU/GPU/QPU 执行方式；不得套用下面旧运行的硬件元数据。
- 文件包含 1001 帧，step 为 0–1000，time_fs 为 0–100，时间步长为 0.1 fs，初始温度为 300 K。
- 初始总能量为 0.5911674093739174 eV，末帧为 0.4855263892197086 eV，变化为 -0.10564102015420879 eV。页面直接展示文件数值；这些数值不代表本次修改完成了科学验收或硬件性能评估。
- `md_log.csv` SHA-256：`c360f7ca3923ecadbef2892d13ad2cb7d46190e0037388c88dce51d4b85f1750`。
- `positions.csv` SHA-256：`7984085f1ef5626828ccee6aa3f710fc989fe0a0b62789f776bf367307865ffb`。
- 使用指南中的短步数 CPU 操作示例独立采集，与本页轨迹不是同一次运行。

## 电路

- `f2-native-circuit.png` 和 `generate_circuit.py` 来自 qhai-2026 的 `applications/h2o-hybrid-aimd/deliverables/handoff-0830/量子线路/`。
- `qiskit_f2.py` 来自同一应用的 `single_h20_aimd/quantum/qiskit_f2.py`。
- 页面逻辑示意按源代码绘制：3 比特、Ry 编码、Ry/CZ/Rx Native seed，随后为 IYZ、YII、YZI、IIX、YII。示意中的 Rx 和多比特旋转代表逻辑操作，原生实现使用 Ry/Rz/CZ。
- 图像是态制备电路；Z/X 读出在页面逻辑示意中另行标明。

## 历史运行记录（不用于当前页面曲线）

- 来源：用户指定参考项目 qfp 的已完成运行。
- 运行编号：`portal-fake-aimd-434aa110e245add823ddf2926a72a6a5`，归档日期 2026-09-10。
- `h2o_aimd_summary.png`、`h2o_aimd_trajectory_3d.png`：该运行原始 figures 文件。
- `md_log.csv`、`positions.csv`：该运行原始 aimd 文件，未抽样、未改写。
- `results.json`：从该运行 `aimd/metrics.json` 的 simulation 字段提取的结果摘要，初始温度由 `md_log.csv` 第 0 帧核实。为公开展示去掉服务器绝对路径。
- 条件：1000 步 NVE、0.1 fs 时间步、初始 300 K、1001 帧。量子环节为 CPU 理想态矢量模拟（fake-QPU），经典模型由 GPU 执行。
- 这里的 GPU 字段是该历史运行的真实记录，保留用于来源追溯，不作为当前门户 CPU/QPU 架构的说明，也不改写成 CPU 运行。
- 这些文件不是本次网页修改新跑的实验，也不是真实 QPU 结果。不将 qhai-2026 独立评估报告中的能量/力误差混入本次轨迹表格。

两组 CSV 的时间单位均为 fs，能量 eV，坐标/键长 Å，力 eV/Å，键角 degree。历史 `h2o_aimd_summary.png` 的总能量曲线使用相对于初始值的变化量，图中单位为 meV；当前页面从导入 CSV 读取绝对能量值，单位为 eV。NVE 的 300 K 是初始温度，不是恒温约束。
