# H2O Hybrid AIMD (`h2o-hybrid-aimd`)

## Project

这是从最终已验证版本中抽离的单个 H₂O 量子—经典混合势与 NVE AIMD 项目。它位于统一仓库的 `applications/h2o-hybrid-aimd/`，内部 Python 包名仍为 `single_h20_aimd`。项目自带配置、数据、checkpoint、模型实现和运行入口，不依赖相邻实验目录。

项目唯一模型为 F2/A2：三比特 one-to-one `Ry` 角度编码，编码缩放为 `[π/4,π/8,π/4]`；Native seed 后接 `IYZ → YII → YZI → IIX → YII` 五个 ADAPT Pauli 旋转；线形 CZ connectivity `[[0,1],[1,2]]`；7Z+7X 共 14 个量子读出；经典端为 32--32 SiLU `TorchMLPRegressor`。线路在 ideal exact-statevector 上执行，逻辑门编译到 `Ry/Rz/CZ` 原生门集，transpiled CZ count/depth 为 6/6。项目不再提供其他编码、seed、算符池、readout 或候选架构实验入口。

训练时的 11 个量子参数固定使用标准两点参数移位法，移位量为 $\pm\pi/2$；经典 MLP 参数仍由 backprop 更新。每个含量子更新的 batch 因此需要 $2P_q=22$ 组移位状态制备，其中 $P_q=11$。当前实现已在 exact-statevector 后端提供参数移位反向链路与真实执行计数；真实带 shots 的 QPU 训练仍需 QPU 中间件适配器，不能把 exact-statevector 重训表述为真机训练。

真实生产链路为：

```text
H2O geometry (B,3,3), O-H-H
→ smooth exchange-invariant features (r1+r2, (r1-r2)^2, cosθ)
→ train-only standardization + one-to-one Ry angle encoding
→ 3-qubit F2 Native seed + ADAPT circuit
→ 7Z+7X exact expectation features (14 dimensions)
→ 32-32 SiLU classical energy head
→ relative Energy / eV
→ Cartesian central difference of the same full energy
→ projected conservative Force / eV/Å
→ ASE Calculator
→ VelocityVerlet NVE AIMD
```

同一能量张量路径保持对 Cartesian 坐标可微。评价脚本另外计算 $F=-\partial E/\partial R$，并与细化中心差分比较。生产 AIMD 仍使用冻结配置中的 `cartesian_central_finite_difference`；整理工作没有把求力算法更换成新的科学实现。

## Directory

```text
h2o-hybrid-aimd/
├── AGENTS.md
├── README.md
├── requirements.txt
├── configs/
│   ├── adapt_campaign.yaml
│   └── h2o_aimd.yaml
├── data/
│   ├── h2o_pyscf_sto3g_fci_v1.csv
│   ├── h2o_pyscf_sto3g_fci_test_final_v2.csv
│   ├── h2o_pyscf_sto3g_fci_offgrid_final_v2.csv
│   └── h2o_pyscf_sto3g_fci_reference_force_final_v2.csv
├── checkpoints/
│   └── hybrid_model.pt
├── single_h20_aimd/
│   ├── api/
│   ├── backends/force/
│   ├── classical/
│   ├── configuration/
│   ├── core/
│   ├── data/
│   ├── evaluation/
│   ├── execution/
│   ├── integration/fusion_framework/
│   ├── quantum/
│   ├── simulation/
│   └── workflows/
├── scripts/
│   ├── evaluate.py
│   ├── plot_f2_results.py
│   ├── run_adapt_campaign.py
│   ├── run_aimd.py
│   ├── submit_fusion_job.py
│   └── validate.py
├── tests/
├── provenance/
└── outputs/
```

## Dataset

| 文件 | 用途 | 数量 | 标签与单位 |
|---|---:|---:|---|
| `h2o_pyscf_sto3g_fci_v1.csv` | 固定 train/validation/test 网格 | 185/25/22 | FCI relative Energy，eV |
| `h2o_pyscf_sto3g_fci_test_final_v2.csv` | 独立 Energy test | 22 | relative Energy，eV |
| `h2o_pyscf_sto3g_fci_offgrid_final_v2.csv` | 独立 off-grid Energy | 48 | relative Energy，eV |
| `h2o_pyscf_sto3g_fci_reference_force_final_v2.csv` | 独立 reference Force | 300 | full-space CASCI analytic Force，eV/Å；Energy 由 direct FCI 交叉检查 |

所有几何均使用 Å，原子顺序固定为 O、H、H。网格数据本身没有 Force 标签；reference Force 是单独生成且与训练、验证、测试和 off-grid 几何无泄漏的数据集。

## Environment

已验证环境是服务器 Conda 环境 `ase-aimd-gpaw`。新环境可安装：

```bash
python -m pip install -r requirements.txt
```

在统一仓库中，根 `pyproject.toml` 和 `uv.lock` 用于跨模块环境；本目录的 `pyproject.toml` 用于 AIMD 模块独立开发。当前根 uv 环境仍限定 Windows x86-64，AIMD 正式科学验证仍按 `AGENTS.md` 在 `109-32cpu` 的 `ase-aimd-gpaw` Conda 环境执行。

## Run

以下命令均从项目根目录执行：

```bash
python scripts/evaluate.py --config configs/h2o_aimd.yaml
python scripts/run_aimd.py --config configs/h2o_aimd.yaml
```

默认配置直接加载冻结 F2 checkpoint。F2 三种子参数移位重训、冻结评估和图像生成分别使用：

```bash
PYTHONDONTWRITEBYTECODE=1 python -B scripts/run_adapt_campaign.py \
  --config configs/adapt_campaign.yaml --stage train
PYTHONDONTWRITEBYTECODE=1 python -B scripts/run_adapt_campaign.py \
  --config configs/adapt_campaign.yaml --stage evaluate
PYTHONDONTWRITEBYTECODE=1 python -B scripts/plot_f2_results.py
```

训练结果写入 `outputs/adapt_campaign/experiments/F2PS_A2_seed_*`；项目只保留这三个 F2 参数移位实验。损失、MAE、最终误差和线路图输出到 `outputs/adapt_campaign/figures/f2_current/`。

## Fusion framework

项目现包含收窄到 H₂O F2/A2 的融合框架完整应用侧闭包：传输无关 Task/Actor 契约、CPU/GPU Quantum worker、可注入 QPU worker、常驻 Classical Actor、远程 Quantum/Classical API 代理、调度势、组件注册、Ray Job Runner、单次提交器、JSON Schema、示例请求和合同测试。

融合框架、QPU 中间件和性能模拟器的总体拓扑、当前完成度、调用次数口径、双方待确认项及联合验收顺序，统一维护在根目录 `融合框架与性能模拟器对接.md`。以后处理这三类对接任务时应先阅读该文件，低层实现细节再看 `BRIDGE.md` 和 `CONTRACT.md`。

融合 Driver 使用两个稳定入口：

```text
single_h20_aimd.integration.fusion_framework.registration:register_components
single_h20_aimd.integration.fusion_framework.runner:run_aimd
```

提交命令示例和运行边界见 `single_h20_aimd/integration/fusion_framework/BRIDGE.md`。提交机器和集群运行环境需要由融合框架方提供 `pivotq`；它不是公开 PyPI 依赖，因此没有伪造到 `requirements.txt` 中。没有真实集群、CUDA 节点、QPU provider 和凭据时，本地合同测试不能代替真实 GPU/QPU 验收。

根目录 `requirements.txt` 继续锁定已验证的 CPU PyTorch 环境。融合 GPU worker 的集群镜像必须另行预装与驱动匹配的 CUDA PyTorch 2.13.0；GPU worker 和 Classical Actor 会在 CUDA 不可用时明确失败，不会静默回退到 CPU。

默认 AIMD 为 300 K、0.1 fs、1000 步 NVE。短 smoke test 可以临时覆盖步数，不会改写配置：

```bash
python scripts/run_aimd.py --config configs/h2o_aimd.yaml --steps 10 \
  --output-dir outputs/smoke_10_steps
```

完整独立性验证使用 Python isolated mode：

```bash
python -I -B scripts/validate.py
python -m unittest -v tests.test_standalone
python -m unittest -v tests.test_execution_contract tests.test_fusion_bridge
```

输出按运行内容保存在 `outputs/` 下，包括配置快照、JSON/CSV 指标、图像、日志和轨迹。默认 F2 推理 checkpoint 的 SHA-256 为 `560bef3584db36933dfcdf1679912f04503b9339da869f489edfee0a631f2b80`。

## Portability and provenance

配置中的数据、checkpoint 和输出路径全部相对项目根目录解析；绝对路径或越出项目根目录的配置路径会被拒绝。`provenance/source_manifest.json` 保存项目抽取时的历史来源快照；本次 F2/A2 参数移位重训、默认 checkpoint 替换及正式验证记录见 `provenance/f2_parameter_shift_training_audit.json`。

配置保留 GPU/QPU 调度契约和硬件噪声代理，但当前 checkpoint 与默认 AIMD 在 CPU exact-statevector 上运行。没有 provider、凭据与校准记录时，不应把 CPU 结果表述为真实 QPU 证据。

## Verified delivery

独立项目已在 `109-32cpu/ase-aimd-gpaw` 完成以下验证：

- F2/A2 三个随机种子的 parameter-shift accepted path 均完成 100 epochs，最佳 epoch 分别为 92、92、96，中位数为 92；
- 每个种子的 accepted-path 训练实际记录 311910 次 parameter-shift state-preparation 输入、350710 次总 state-preparation 输入；代表 checkpoint 连同训练后诊断累计记录 314000 次 parameter-shift 输入；
- 冻结代表 seed 20260829 的 Energy final-test MAE 为 `0.0274429888 eV`，off-grid MAE 为 `0.0320402058 eV`；
- 300 点 reference Force MAE 为 `0.2624120342 eV/Å`；
- autograd Force 与细化中心差分最大绝对误差为 `0.0000830398 eV/Å`；
- 默认 1000 步 NVE 生成 1001 帧，总能量漂移为 `0.000082863 eV`，轨迹验收通过。

初次统一仓库迁移后，项目还完成了 noise-aware finite-shot Force 路线的 1000 步、5-seed 探索性代理 AIMD。5/5 条轨迹完整且无 OOD 或发散，4/5 通过全部预注册探索性判据；唯一未通过项是一个 seed 的 latent Energy 线性漂移率。该结果不改变“严格 measured-Energy NVE 门尚未通过、真实 QPU 尚未验证”的证据边界。

机器可读的参数移位重训与评估证据位于 `outputs/adapt_campaign/experiments/F2PS_A2_seed_20260829/` 和 `outputs/adapt_campaign/final_evaluation/F2PS/`；默认 checkpoint 的正式 1000-step NVE 证据位于 `outputs/full_1000/`。非 F2 与旧 checkpoint 实验产物已从项目删除。

最新有限采样实验的完整交接报告已按仓库发布规则移出并归档；机器可读完成清单仍保存在 `provenance/exploratory_aimd_1000step_completion_manifest.json`。公开 README 和模型说明保留必要的验证范围与已知限制，汇报材料、实验说明和候选方案图集中保存在 `最新实验指导文档/`；本地逐步轨迹、运行日志和重新生成的报告位于未纳入 Git 的 `outputs/` 与 `reports/`。
