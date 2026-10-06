# 水分子动力学模拟静态展示材料

本目录保存预先生成的轨迹、历史运行记录和电路教程源码。水分子动力学模拟页的“重新播放”只回放已有 CSV，不会提交或重新执行计算任务。下面两组轨迹分别保存，不能混用它们的指标或硬件记录。

## 当前页面播放的导入轨迹

- 页面实际读取 `imported/md_log.csv` 与 `imported/positions.csv`，由浏览器生成动力学曲线和三维轨迹。
- 两文件可追溯至本仓库旧站的初始提交 `8127b35258d229932b9a4cac84fa1416165e62d6`（2026-10-03），新版站点沿用相同数据。现有归档未附原始运行编号或执行后端记录，不能确认其 CPU/GPU/QPU 执行方式；不得套用下面旧运行的硬件元数据。
- 文件包含 1001 帧，step 为 0–1000，time_fs 为 0–100，时间步长为 0.1 fs，初始温度为 300 K。
- 初始总能量为 0.5911674093739174 eV，末帧为 0.4855263892197086 eV，变化为 -0.10564102015420879 eV。页面直接展示文件数值；这些数值不代表本次修改完成了科学验收或硬件性能评估。
- `md_log.csv` SHA-256：`e7a11bef1d19dc639768ba8353338b27a75a7006fd87cf7ea2c57ad5dbdcedfb`。
- `positions.csv` SHA-256：`8f6829627280df27b1708a13b9dcbc2a673a9330aacf1f5cb8cd2680f2893394`。
- 使用指南中的短步数 CPU 操作教程独立采集，与本页轨迹不是同一次运行。

## 电路

- `f2-native-circuit.png` 和 `generate_circuit.py` 来自 qhai-2026 的 `applications/h2o-hybrid-aimd/deliverables/handoff-0830/量子线路/`。
- 门户的 `generate_circuit.py` 与 `website/src/lib/aimd-model-source.py` 同步维护，现在通过 `pivotq` 和 `pivotq.circuit` 导入电路接口；底层直接复用 Qiskit，电路结构保持不变。使用 Python 3.12，在 PivotQ 仓库根目录运行 `python -m pip install ./packages/framework`，或使用仓库已配置的统一环境。
- 页面里的电路构造与摘要代码只需上述 SDK。运行完整 `generate_circuit.py` 导出 PNG 时，还需 `matplotlib`；可运行 `python -m pip install matplotlib pylatexenc`，同时启用电路绘图所需的可选依赖。
- `qiskit_f2.py` 来自同一应用的 `single_h20_aimd/quantum/qiskit_f2.py`；门户副本改为从 `pivotq` 导入 `QuantumCircuit`，原有门操作与编译逻辑保持一致。
- 页面逻辑示意按源代码绘制：3 比特、Ry 编码、Ry/CZ/Rx Native seed，随后为 IYZ、YII、YZI、IIX、YII。示意中的 Rx 和多比特旋转代表逻辑操作，原生实现使用 Ry/Rz/CZ。
- 图像是态制备电路；Z/X 读出在页面逻辑示意中另行标明。

## 历史运行记录（不用于当前页面曲线）

- 来源：用户指定参考项目 qfp 的已完成运行。
- 运行编号：`portal-fake-aimd-434aa110e245add823ddf2926a72a6a5`，归档日期 2026-09-10。
- `h2o_aimd_summary.png`、`h2o_aimd_trajectory_3d.png`：该运行原始 figures 文件。
- `md_log.csv`、`positions.csv`：该运行原始 aimd 文件，未抽样、未改写。
- `results.json`：从该运行 `aimd/metrics.json` 的 simulation 字段提取的结果摘要，初始温度由 `md_log.csv` 第 0 帧核实。为公开展示去掉服务器绝对路径。
- 条件：1000 步 NVE、0.1 fs 时间步、初始 300 K、1001 帧。量子环节为 CPU 理想态矢量模拟（fake-QPU），经典模型由 GPU 执行。
- 这里的 GPU 字段是该历史运行的真实记录，保留用于来源追溯；不能据此推断当前页面播放的导入轨迹使用 GPU，也不改写成 CPU 运行。
- 这些文件不是本次网页修改新跑的实验，也不是真实 QPU 结果。不将 qhai-2026 独立评估报告中的能量/力误差混入本次轨迹表格。

两组 CSV 的时间单位均为 fs，能量 eV，坐标/键长 Å，力 eV/Å，键角 degree。历史 `h2o_aimd_summary.png` 的总能量曲线使用相对于初始值的变化量，图中单位为 meV；当前页面从导入 CSV 读取绝对能量值，单位为 eV。NVE 的 300 K 是初始温度，不是恒温约束。
