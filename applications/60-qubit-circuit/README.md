# Twenty-water / 60-qubit AIMD application

本目录实现二十水的完整应用电路、重新生成的 MB-pol 数据集、总能量头、力/MD 入口与真机 HTTP 接口。**不训练模型**：48 个量子参数和 \(120\to64\to32\to1\) 经典网络采用可复现初始化，`training_updates=0`。当前势能/力/MD 结果用于软件链路核验，不能作为已收敛模型或动力学精度结论。

2026-10-04：已在 **109-32cpu** 重新生成 5,000 条二十水数据，完成 CPU 短程 MD、真实 Ray Task→Actor、数据/力/电路一致性验证。用户后续明确要求这次**无需连接真机测试**；真机接口通过离线契约测试。实际 60 比特拓扑、映射和深度预算需在部署时写入硬件 profile，交接包中的九比特映射没有外推为六十比特。

## 先看什么

1. `configs/circuit.json`：从 v4 最终冻结模型继承的**门结构**、平滑截断半径、共享参数和网络维数；没有继承十水权重。
2. `water20/geometry.py` → `water20/circuit.py`：坐标到活动组合、连续角绑定、Pauli 旋转的精确 CZ 分解。
3. `water20/model.py` → `water20/potential.py`：120 个读出值到体系总能量，再到力和 ASE 积分。
4. `water20/hardware.py` → `water20/qpu.py` → `water20/protocol.py`：实际拓扑编译、multipart HTTP 作业和逐 shot 校验。
5. `water20/fusion.py`：PivotQ 公共融合接口；CPU 量子 Task 或 QPU Actor，后接同一个常驻经典 Actor。

`scripts/` 只放命令入口，`tests/` 放验收测试，`models/` 放初始化权重及一份原生电路，`dataset_water20_mbpol_v1/` 只保存一个压缩 HDF5 和两份统计/来源文件，`docs/` 放两张 SVG 及小型预览，`reports/` 保存紧凑证据。环境、MBX 动态库、安装日志和框架源码不复制进应用。

## 电路与完整数据流

每个水按 O,H,H 排列，固定占三个比特；二十水共 60 原子、60 比特。整个状态制备过程没有中间测量、reset 或重新初始化。

$$
\mathbf R\longrightarrow\text{mass centering and smooth features}
\longrightarrow\mathrm{Enc}(1B\to2B\to3B)
\longrightarrow\mathrm{Trainable}(1B\to2B\to3B)
\longrightarrow(\langle X_0\rangle,\ldots,\langle X_{59}\rangle,\langle Z_0\rangle,\ldots,\langle Z_{59}\rangle)
\longrightarrow\widehat E(\mathbf R).
$$

- 1B 为 3 个语义块；2B 为 10 个块；3B 为 15 个块。组合按固定分子 ID 的字典序执行，同一特征槽连续出现，前后两段对应块的逻辑结构有实际差异。
- 候选组合为 190 对和 1,140 个三元组，只执行正平滑权重的组合；两段使用相同活动列表。1B/2B/3B 分别共享 6/18/24 个量子参数，共 **48** 个，增加分子数不会增加参数字典。
- 保留 v4 的 XZ/YZ/XZZ/YZZ 跨分子 Pauli 纠缠。跨分子门作用于各分子的第一条线，另 40 条线保留局部旋转和统一读出；没有新增第四类模块或独立分子能量求和头。
- 量子初始化为非等值、有正负号且绝对值位于 0.2–0.6 rad 的参数。经典网络共有 **9,857** 个参数，整个应用没有训练入口。
- AIMD 继承 v4 连续分支：质量中心化坐标与 bisector xyz，取消不连续的 0.1 rad **数据编码角硬下限**。原方位角特征槽连续编码 bx/by，另一个槽编码 bz；这是 v4 AIMD 的语义槽定义，区别于冻结能量版的单标量方位/极角。可训练块仍为 48 个键。
- 编码/可训练模块都随 quintic 权重平滑关闭。cutoff 原样继承 v4 最终配置：pair 约 2.576/2.926 Å，triple 约 2.532/2.832 Å；不是 MB-pol 标签计算的截断半径。

当前图示训练构型有 20 个 1B、15 个活动 2B、6 个活动 3B。构型变化会改变活动模块和门数量，不改变共享参数、全部 60 条线或 120 维读出。

## 安装与运行

应用作为独立 editable 包安装；无需修改仓库根目录面向其他应用的锁定环境。推荐 Python 3.12；CPU 验证不需要 GPU、PyTorch、PySCF 或显式稠密六十比特状态向量。

```bash
cd /Users/zhanghao/code/PivotQ/applications/60-qubit-circuit
python3.12 -m venv ~/.cache/pivotq-water20-env
~/.cache/pivotq-water20-env/bin/python -m pip install -e '.[dev,figures,fusion]'
```

服务器已经安装的执行环境：`/home/hzhang/code/PivotQ-runtime/venv/bin/python`。本次本地验证环境：`/Users/zhanghao/.cache/pivotq-water20/venv/bin/python`。不要把虚拟环境放在应用目录。

从应用目录执行，每次运行使用新的输出目录：

```bash
python -B scripts/validate.py
python -B scripts/run.py --mode energy --output outputs/energy-001
python -B scripts/run.py --mode energy_force --output outputs/force-001
python -B scripts/run.py --mode aimd --steps 1 --dt-fs 0.1 --output outputs/aimd-001
python -B scripts/export_circuits.py
```

默认取训练集第 0 条几何，仅用于执行验证。换输入可指定 `--sample-index`，或 `--geometry /absolute/path/input.json`。JSON 必须包含 `atomic_numbers=[8,1,1]` 重复二十次、`positions_angstrom` 的 \(60\times3\) 数组、`pbc=false`。无需读取能量或力标签来推理。

CPU 后端根据实际门连接精确分解为张量因子，保留每一条线、使用 complex128，不截断、不用 MPS，也不分项近似能量。模板最多包含二十条相互连接的跨分子线；当前三条验收构型的最大因子为 15/8/15 比特。新增门若使因子超过设定限额，会明确失败。**这不是显式存储完整六十比特稠密振幅的证明。**

CPU 力使用精确量子伴随角导数，再乘连续经典编码的数值 Jacobian。硬件力支持逐门实例 parameter-shift 或 Cartesian finite difference；详见 [接口说明](docs/INTERFACE.md)。MD 使用 ASE VelocityVerlet，默认 300 K、0.1 fs 和 1 步；初始化模型不保证 NVE 守恒或准确动力学。

## 真机接口与融合框架

直接部署入口已经包含绑定、拓扑路由、换基、HTTP、校验和能量/力/MD 调用。部署时用设备确认的 profile 替换 `configs/hardware_profile.template.json` 的空字段；模板会明确拒绝提交，而不是猜测拓扑。profile 不是发送给服务器的新协议，HTTP 参数保持来源示例的约定。

```bash
export QPU_DEVICE_URL='http://ACTUAL_DEVICE_SERVICE:PORT'
# 如设备需要认证，设置 QPU_DEVICE_API_KEY；不写入配置或报告。
python -B scripts/run.py --backend qpu --mode energy \
  --hardware-profile /absolute/path/confirmed-water20-profile.json \
  --shots 3000 --output outputs/qpu-energy-001
```

shots 是可配置预算，3000 是接口默认值，不是精度保证。X/Z 分别为一条完整 60 比特电路，X 已在应用末端换基，设备仍固定 Z 读出。返回恢复全部 120 个期望，不生成包含所有可能状态的概率字典，也不把理想概率当实测值。部署详情见 [INTERFACE.md](docs/INTERFACE.md)。

真机力计算和 MD 默认使用坐标中心差分 `coordinate_fd`，位移为 0.02 Å；可用 `--fd-step-angstrom 0.02` 调整。该位移用于力的数值导数，不是 MD 时间步长；`--dt-fs` 默认仍为 0.1 fs。CPU 默认伴随法，可选 `--force-method parameter_shift` 切换量子角导数路径。差分位移的默认值面向低精度演示，未经真机标定。

融合框架 CPU 示例：

```bash
PYTHONPATH=../../packages/framework python -B scripts/run_fusion.py \
  --backend cpu --output outputs/fusion-001
```

可以指定 `--address` 接入现有 Ray；应用与模型/配置文件必须在各 worker 上以同一绝对路径可读。QPU 模式增加 `--backend qpu --profile ...`，不会使用仓库中固定三比特的 QPU service。`water20.fusion.FusionEnergy` 提供框架托管的 `energy/energy_force` 接口。直接 MD CLI 是直接势能执行路径；本次 Ray 验收是能量 Task→Actor 路径，两者证据分别记录。

## 已验证的内容

完整证据：[validation.json](reports/validation.json)、[运行汇总](reports/runtime.json)、[源文件哈希](reports/provenance.json)、[同步结果](reports/synchronization.json)。

- 41 项测试通过：结构/共享参数、精确分解、小系统完整状态向量、60 比特力链路、数据隔离、逐 shot 完整性、位序/文件关联、multipart、不确定 POST 的安全恢复和完整 60 比特应用的 localhost HTTP 往返。
- 三条完整二十水构型的源电路与原生编译 X/Z 读出最大差异小于 \(3\times10^{-14}\)；抽查力的最大能量有限差分误差小于 \(7\times10^{-6}\) eV/Å。
- MBX 标签独立重算一致，抽查 MBX 力与能量有限差分差异约 \(8\times10^{-9}\) eV/Å。
- 109-32cpu 上两次精确势能/力查询完成一次 MD 步、两帧；另已运行训练集最大连通构型（19 比特因子）的完整六十线能量，耗时约 4.2 秒；真实 Ray 两个量子 Task 接同一个经典 Actor，能量与独立 CPU 路径一致。
- 编译等级采用明确的 level 1、`approximation_degree=1.0`；本次实测 level 2/3 对平滑 cutoff 的小角度产生约 \(1.9\times10^{-5}\) 的读出差异，故没有用于当前导出和真机路由。

上述只验证执行和数值实现，不宣称量子模型准确、具有量子优势或真机科学验收通过。MB-pol 是参考势，不是新进行的 DFT 标注；[MBX 官方说明](https://github.com/paesanilab/MBX)介绍了其能量/力用途。编译依据 [Qiskit OpenQASM 3](https://quantum.cloud.ibm.com/docs/en/api/qiskit/qasm3)和 [final layout 说明](https://qiskit.qotlabs.org/docs/api/qiskit/qiskit.transpiler.TranspileLayout)，真实协议以本次提供的 005 交接包源码为准。

## 图与服务器同步

- [20 分子电路彩色逻辑图.svg](docs/20%20分子电路彩色逻辑图.svg)：实际编码/可训练门序列、活动组合、全局线号及共享参数 θ1–θ48。可训练角以紫色门中的 θ 符号表示，隐藏权重系数；编码角和固定角保留数值。省略未参与当前模块的线是作用域视图，不是删除应用中的比特。
- [20 分子电路transpile图.svg](docs/20%20分子电路transpile图.svg)：完整 60 条线（q0–q59，全部二十个水分子）从左到右连续绘制，不上下分块；保留全部符号编译门和每个 CZ 的两端。编译保留真实的参数表达式，绘图仅展示 θ1–θ48 的依赖，不显示权重系数；固定换基角仍用数值。符号电路与数值绑定后优化的执行 QASM 门数可能不同。**当前是原生门集编译图，没有声称已按未知物理拓扑路由。**

最终文件保留在本目录；小型 `.preview.png` 只是图首段预览。SVG 可以放大编辑，不另外保存巨大完整 PNG、QPY、多份数据或旧项目快照。

```bash
python -B scripts/sync_server.py push
python -B scripts/sync_server.py check
```

同步目标只限 `109-32cpu:/home/hzhang/code/PivotQ/applications/60-qubit-circuit`，核对全部持久文件 SHA-256。`--delete` 仅用于这个新应用镜像；旧项目、外部环境和 MBX 动态库不在同步范围。
