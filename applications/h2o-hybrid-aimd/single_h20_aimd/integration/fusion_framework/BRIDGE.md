# H₂O F2/A2 融合框架桥接

## 目标

本目录把独立 H₂O F2/A2 ADAPT-inspired Hybrid Potential 接到 `pivotq._internal` FusionFramework。客户端对一条完整轨迹只提交一次 Ray Job；框架 Driver 在集群侧运行 CPU AIMD coordinator，并把量子特征派发为 Task、把经典能量头部署为常驻 Actor。

```text
submit_job
  -> pivotq._internal.jobs.driver
     -> register_components(framework)
     -> run_aimd(framework, context)
        -> QPUCircuitService
           -> 每个几何上传 .Z/.X 两条 QuantumCircuit，并分别标记 measurement_basis
           -> 三比特联合概率 -> 14 个 7Z+7X 特征
        -> FusionExecutionClient
           -> classical_predict Actor（14 维入站，checkpoint 内选 12 维）
        -> CPU Cartesian finite difference + VelocityVerlet + diagnostics
```

稳定 Driver 入口：

```text
single_h20_aimd.integration.fusion_framework.registration:register_components
single_h20_aimd.integration.fusion_framework.runner:run_aimd
```

## 代码职责

1. `quantum/qiskit_f2.py`：构造已绑定、无测量的三比特 F2 `.Z/.X` 电路。
2. `qpu_circuit_adapter.py`：批量上传两种电路与 X/Z 基元数据，把联合概率恢复为固定顺序 14 维特征。
3. `registration.py`：注册 CPU/GPU Quantum Task 与 Classical Actor；QPU 模式组合调用融合框架官方 QPU 注册入口。
4. `runner.py`：把 Ray Job 上下文转换为完整 AIMD 请求，QPU 模式创建 `QPUCircuitService`。
5. `fusion_client.py`：把框架的 `submit/result/release` 映射到项目执行客户端。
6. `components.py`：框架组件薄包装，不复制科学计算。
7. `execution/`：传输无关请求、结果、worker、Actor 和本地合同测试客户端。
8. `core/scheduled_potential.py`：用 QPU Quantum API 与远程 Classical API 重新组装同一个 HybridPotential。

## 运行边界

H₂O 输入固定为 `molecular_geometries_A=(B,3,3)` 和 `atomic_numbers=[8,1,1]`。生产 Force 仍是完整 Cartesian 能量的中心有限差分；远程边界只承载推理，不承担训练或 autograd 反向传播。

GPU 路径要求框架实际分配 CUDA 节点，Classical Actor 也会拒绝没有 GPU 声明或 CUDA 不可用的请求。QPU 模式上传 `QuantumCircuit` 和必填的 `measurement_basis` 元数据，不在应用侧增加 `measure` 或伪造 provider/CPU fallback；QPU Actor 和实际测量由融合框架负责。

## 提交

提交端必须安装融合框架提供的 `pivotq._internal`，并能访问 Ray Jobs API：

```bash
python -m single_h20_aimd.integration.fusion_framework.submit_job \
  --address http://RAY_HEAD:8265 \
  --submission-id h2o-f2-aimd-001 \
  --working-dir /path/to/single_h20_aimd \
  --config-path /data/hzhang/tmp/lcz_hybrid_v1/single_h20_aimd/configs/h2o_aimd.yaml \
  --checkpoint-path /data/hzhang/tmp/lcz_hybrid_v1/single_h20_aimd/checkpoints/hybrid_model_readout_pruned_shot_robust.pt \
  --output-dir /data/hzhang/tmp/lcz_hybrid_v1/single_h20_aimd/outputs/fusion/h2o-f2-aimd-001 \
  --quantum-target qpu \
  --qos-helper-module provider_qpu_backend \
  --qos-data-tree-target provider_qpu_backend:DataTree \
  --config-overrides-json '{"checkpoint":{"sha256":"21ba3e8be89ed141fd05d384b0cf6a0d4f054a170aebef14ff028639a706b6ac"}}'
```

集群可见路径必须是绝对路径。Job 内统一设置 `PYTHONDONTWRITEBYTECODE=1`。

## 验证范围

在没有真实 Ray/GPU/QPU 资源时，已经验证 `.Z/.X` 双电路构造、必填 X/Z 基元数据及原样回传、无经典位/无测量/无未绑定参数、直接 `q0 q1 q2` 位序、14 维概率还原，以及 14→12 checkpoint 推理。真实 GPU/QPU 联合验收仍需要相应集群和 provider 凭据。
