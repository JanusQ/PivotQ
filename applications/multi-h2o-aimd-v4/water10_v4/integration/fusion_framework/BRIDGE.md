# 十水 v4 融合框架接口

本接口参考单分子项目的 Driver → quantum Task/service → classical Actor 拓扑实现；运行时不导入单分子项目。默认模型为全量联合训练第 6 轮的 `models/final/best_model.json`，包含原始模板、48 个量子参数、normalizer、radii 和 60→64→32→1 tanh 网络。`models/experimental/current_model.json` 是连续编码的 11 次更新未收敛模型，仅用于运行验证。加载器按模型内的编码版本选择实现，不修改权重或归一化。无需读取训练数据即可部署推理。

默认 `mode=energy`。`energy_force` 和 `aimd` 是新增的实验性能力；本模型仅训练能量，编码有 0.1 rad 硬下限和全局坐标依赖，未证明势面光滑性、力精度或 NVE 守恒。不能从单分子验收结论推导十水已通过。接口不启动训练、不修改归一化、数据划分或已有检查点。

## 入口与数据流

1. `submit_job.py`：整个应用只提交一次 `RayJobSpec`；生成独立 namespace，使用框架 Driver。
2. `registration:register_components(framework)`：注册 CPU statevector Task、CPU/CUDA 常驻 Actor；QPU 模式调用配置指定的供应方注册函数。
3. `runner:run_aimd(framework, context)`：CPU coordinator，读取显式坐标，执行能量批次或实验性 MD，写输出。
4. `model.py`：检查 JSON 模型 SHA256，复用 v4 `data.features/encode_features` 与 `circuit.instances`。
5. `client.FusionPotential`：量子/经典分批，维护 `submit/result/release` 与 session 生命周期。可直接作为其他 CPU coordinator 的势能接口。
6. `qpu.QPUFeatures`：复用 `revision.build_block_circuit`，构造已绑定 X/Z 电路，校验结果并恢复 60 特征；也提供 `evaluate/jacobian` 后端接口，共享参数按每个门实例移位累加。此次没有把联合训练主循环切换到 QPU。

```text
一个 Ray Job → CPU Driver/coordinator
  ├─ quantum_target=cpu：statevector Quantum Task（CPU，非真机）
  ├─ quantum_target=qpu：外部 30-qubit QPU service
  └─ classical_device=cpu/cuda：同一个常驻 Classical Actor
       → 60 特征 → 原 tanh MLP → 反归一化 → eV
```

量子 CPU 使用 double statevector，关闭比特裁剪，显式保存全部30比特振幅，逐构型串行执行。`quantum_num_threads` 默认模板为 8，Task 请求相同数量 CPU；未配置时保留单线程。`statevector_memory_mb=32768` 是每任务的工作内存预算（状态本体16 GiB），任务同时检查宿主机与 cgroup 余量，不足时失败，无 MPS 回退。共享框架的 ResourceRequest 不支持内存预留，多 Job 部署需由集群独立限制并发；应用内存检查不是跨进程原子预留。CUDA 只用于经典 MLP，缺少 CUDA 会失败，不回退。Driver 1 CPU；经典 Actor 0.25 CPU，加 1 GPU（仅 CUDA）。QPU 资源由外部注册函数决定。

`QuantumComponent.execute` 保留仅返回特征的入口；应用客户端调用新增 `execute_with_metadata`，同时返回每构型实际 Aer method/device/num_qubits、精度、线程、耗时、进程 RSS 峰值和内存预检。`run_summary.json` 保存这些诊断及框架 execution report。PivotQ 框架公共接口保持不变。

## 部署和最小命令

Driver、Task、Actor 必须能访问同一共享存储上的 `model_path`、`geometry_path` 和输出目录。框架 `pivotq._internal` 应安装在提交端及各 worker 环境；应用依赖 NumPy、h5py、Qiskit、Qiskit Aer、psutil（现有线路模块的导入依赖），MD 另需 ASE，CUDA 另需支持 CUDA 的 PyTorch。以本仓库框架安装说明为准；本次未安装或升级集群 Ray。

已提供 `configs/fusion_geometry.json`，使用训练样本 `w10_269547167027ff4be8a4`，可直接配合示例配置运行。更换输入时，在 v4 项目目录导出训练集的一条几何，另存新文件并更新配置的 `geometry_path`；`--sample-id` 可重复。脚本不读取测试标签、不覆盖已有输出文件：

```bash
PYTHONDONTWRITEBYTECODE=1 python -B scripts/prepare_fusion_geometry.py \
  --sample-id '<训练集中的实际 sample_id>' --output configs/fusion_geometry_custom.json
```

`configs/fusion_cpu.json` 是应用相对路径模板，内含当前最佳 JSON 模型摘要，不能直接作为远程 Driver 的共享配置。`config.resolve_template(template_path, application_root)` 将模型和几何路径解析为绝对路径，再把结果写到运行目录供 Driver/worker 使用；`load_config` 仍拒绝相对路径。更换模型必须同时更新摘要。输入 JSON：

```text
atomic_numbers: [8,1,1] 重复10次
molecular_geometries_A: (B,30,3)，单位 Å，保留全局坐标
pbc: false
```

可通过 Python 获取当前线路展示样本 ID（来自训练集）：

```bash
python -c "import json; print(json.load(open('models/final/circuit_source/display_manifest.json'))['sample_id'])"
```

不要直接把含大数据和全部 runs 的项目作为 Ray 上传目录。准备只含 `water10_v4/` 的部署目录，模型与输入使用共享绝对路径：

```bash
mkdir -p /tmp/water10-deploy
cp -R water10_v4 /tmp/water10-deploy/
python -B -m water10_v4.integration.fusion_framework.submit_job \
  --submission-id water10-energy-001 \
  --working-dir /tmp/water10-deploy \
  --config-path /shared/water10/runtime_config.json \
  --output-dir /shared/water10/outputs/fusion-energy-001 \
  --dry-run
```

实际提交：去掉 `--dry-run`，增加 `--address http://RAY_HEAD:8265 --wait`。不加 `--wait` 时提交后返回 submission ID；等待超时不自动取消仍在运行的任务。配置文件是共享路径，dry-run 只检查提交参数，不承诺远端文件存在。每次使用新的输出目录和 submission ID。框架拥有连接、Actor 和最终关闭操作，runner 不自行 `ray.init()` 或关闭框架。

## 30 比特 QPU 契约与现有限制

**仓库 `pivotq._internal.qpu_integration.QPUCircuitService` 仍固定三比特，不可直接用于本应用。** 共享框架本次未修改。QPU 模式必须配置：

```json
{
  "quantum_target": "qpu",
  "qpu_registration": "site_water30.registration:register_components",
  "qpu_service_factory": "site_water30.service:create_service",
  "shots": 100000,
  "physical_qubits": null
}
```

这些 `site_water30` 路径是供应方需实现的接口示例，非仓库已有模块；shots 数字仅示范配置类型，不是推荐预算。`create_service(framework, context)` 返回对象，需支持：

- `describe()` 返回 `num_qubits=30`、`result_bit_order="q0..q29"`、`measurement_bases=["X","Z"]`。
- `run_quantum_circuits(step=..., circuits=..., shots=...)`；可显式声明 `measurement_qubits` 与 `physical_qubits` 参数。若声明后者，必须配置 30 个唯一物理比特名称。
- 输入 `QuantumCircuitRequest`：每个几何按 `.X`、`.Z` 顺序两条完整 30 比特电路；X 已包含末端 H，Z 无基变换；均无经典位、测量、Aer save 指令或未绑定参数。供应方添加最终测量，不可再次添加 X 基变换。
- 逐电路输出字典必须与请求顺序一致，回传 `circuit_id`、`measurement_basis`、`shots`、`measurement_qubits=list(range(30))`、`probabilities`。
- `probabilities` 为稀疏 30 位 bitstring → probability，缺失位串按零解释，和必须为 1。字符串从左到右为 q0..q29；原始 Qiskit counts 通常为相反位序，必须在服务内转换，应用不会猜测。
- 同基联合概率恢复各比特边缘期望，拼接为 X0..X29、Z0..Z29。不能复制单分子的 7Z+7X 或 14 维契约；不能要求完整返回十亿个概率。
- 服务负责资源、物理映射、编译、排队、取消和硬件错误。应用不重试不明状态的硬件作业、不将 CPU 结果冒充 QPU。任何缺项、错序、非法概率或单电路失败都会终止当前查询。

`QPUFeatures.jacobian` 可用于后续训练接入：每个共享参数对应的门实例各执行正负移位，乘该实例 coefficient 后累加。完整训练的优化器、数据加载和批调度仍沿用原代码，本次不启动真机训练。

## 力、MD 和工作负载

`mode=energy_force/aimd` 需要显式设 `allow_unvalidated_forces=true`。AIMD 只接受一个初始构型，默认模板为 1 步、0.1 fs、300 K，ASE VelocityVerlet。没有复制单分子刚体力投影，因为 v4 使用全局编码，投影会改变实际势能梯度。测试中的解析势只验证差分和积分程序，不证明训练模型物理正确。

每个十水构型有 90 个 Cartesian 坐标；一次中心差分能量/力查询包含 181 个几何（base、90 plus、90 minus），QPU 对应 362 个测量设置。`batch_size=16` 时分成 12 次量子调用和 12 次 Actor predict，最后一批为 5 个几何。N 步核心查询通常为 N+1（ASE 缓存同构型力/能量），不含额外诊断；实际以输出 `calls` 为准。能量批次 B 个构型对应 B 次状态制备和 2B 个 QPU 设置。

这份说明是应用工作负载契约，未生成或验收性能模拟器 Scenario。

## 输出、失败和验证

`<output_dir>/water10/` 包含输入和配置快照、`energies.json`/`energy_force.json` 或 `trajectory.traj + md_log.jsonl`、`run_summary.json`、可用时的 `framework_trace.jsonl` 及 SHA256 `artifacts.json`。异常或协作停止会保存已知状态并继续向 Driver 抛出，不能用进程成功掩盖失败；Actor session 在正常/异常退出时清理，物理 Actor 由 Driver 关闭。若 `result()` 抛异常且终态未知，不提前 release handle。

`status=succeeded` 仅表示程序完成；`scientific_status=not_validated` 明确不声明力/MD验收通过。真实 Ray 多节点、GPU 和 30 比特真机均需独立验收。

测试命令（环境中需可导入 `pivotq._internal`）：

```bash
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  python -B -m pytest tests/test_fusion_framework.py -q
```

完整 30 比特推理测试带 `heavy` 标记，默认 pytest 排除；显式运行时加 `-m heavy`。小系统测试不能替代真实十水执行证据。

从 PivotQ 根目录执行真实本地 Ray 能量验收，每个模型只执行一个构型：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B tests/integration/run_cpu_water10.py \
  --model both --threads 8 --output-dir applications/multi-h2o-aimd-v4/outputs/ray-check
```

此入口使用 `simulation=False`、独立 Ray namespace/tempdir、9 个逻辑 CPU 和 256 MiB object store；只关闭自己创建的 Ray 实例。量子 Task 超时为 7200 秒。验收要求真实 Ray Task → 同一经典 Actor 的 create/predict/terminate、完整 30 比特 double CPU 状态向量、有限能量、模型/几何/工件 hash 及资源清理。输出 `run_manifest.json` 和 `validation.json`，不采用单水的科学准确性门。

独立解析力 smoke 完成后，以实验模型首帧能量做跨后端核对（旧冻结模型只做 Ray 有限能量验证）：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B tests/integration/run_cpu_water10.py \
  --validate-only --output-dir applications/multi-h2o-aimd-v4/outputs/ray-check \
  --smoke-output applications/multi-h2o-aimd-v4/outputs/smoke-check
```

核对要求模型与输入几何 SHA256 相同，绝对能量差不超过 `1e-6 eV`。`--validate-only` 读取已有产物，不重算量子线路。未提供 smoke 时 `comparison_status=pending_smoke_output`、`acceptance_complete=false`，仍可单独查看已完成的 Ray 验证。所有结果保留 `scientific_status=not_validated`。

历史测试记录已按2026-09-23清理要求删除；保留测试代码，可重新验证。此前已通过17项接口测试及10项子测试，真实Ray/CUDA/QPU未验收。

后端切换后，旧MPS指标/测试记录不能作为statevector验收；保留模型没有重新训练。
