# Multi-H2O AIMD v4 — 最终保留版

10个水分子、30个量子比特，1B→2B→3B线路；48个共享量子参数，60维量子读出接60→64→32→1 tanh MLP。最终模型为全量训练第6轮，验证能量RMSE 0.3995958194 eV。

## 当前模拟后端

CPU训练、核验和融合接口统一使用Qiskit Aer `statevector`、double精度，关闭比特裁剪，显式保存全部30比特振幅；不使用MPS。单个状态本体16 GiB，每个worker要求至少32 GiB可用内存预算，默认1 worker，内存不足直接失败。32 GiB是工作预算，不是所有线路的峰值保证。60维读出直接从完整状态计算，不额外向Python返回一份16 GiB振幅副本。

已保存的第6轮模型、指标和曲线来自此前MPS训练，权重原样保留；尚未执行statevector全量训练或30比特数值验收。切换后必须重新核验指标；不得把旧曲线标成statevector训练结果。

## 当前文件

- `water10_v4/`：线路、数据处理、训练和推理源码；`integration/fusion_framework/`：融合接口。
- `models/final/best_model.json`：冻结模型，包含模板、量子参数、MLP、normalizer和radii。
- `models/final/best_trained.pkl`：同一最佳检查点；`best_selection.json`：选择依据。历史训练数据缓存和优化过程已删除，不再提供原运行的逐批续训目录。
- `models/final/circuit_source/`：最终图所需的原始QPY、逐门清单和来源信息。
- `models/initialization/`：当前线路初始化定义和radii，供将来显式启动新训练使用，不包含旧实验日志。
- `configs/`：数据配置、融合配置和示例训练构型。
- `dataset_water10_mbpol_v1/`：完整冻结数据集；`data_v4/`：数据适配资源，均保留。
- `文档/water10_stateprep_rx_rz_cz_opt3/`：最新θ参数超长图、符号QPY、参数表、可编辑draw.io和生成源码。
- `tests/`、`scripts/`：核验和运行工具；训练脚本必须显式传入新运行目录。

[最新SVG电路图](文档/water10_stateprep_rx_rz_cz_opt3/water10_stateprep_symbolic_rx_rz_cz_opt3.svg) · [完整PNG](文档/water10_stateprep_rx_rz_cz_opt3/water10_stateprep_symbolic_rx_rz_cz_opt3.png) · [融合接口说明](water10_v4/integration/fusion_framework/BRIDGE.md)

## 运行与复现

融合配置 `configs/fusion_cpu.json` 已指向 `models/final/best_model.json`。其中是服务器共享绝对路径；部署时需上传整理后的模型目录并按实际环境调整路径。默认只做能量推理；30比特QPU服务需外部实现，MD仍为未做科学验收的显式选项。

`python -B scripts/export_current_circuit.py` 可从最终模型和示例坐标重建当前图的输入。完整横图通过 `文档/water10_stateprep_rx_rz_cz_opt3/water10_stateprep_symbolic_source.py` 在本地codex-figures环境生成。

## 2026-09-23清理

按用户要求，本地删除multi-h2o-aimd、v2、v3。v4删除全部旧runs、半量模型、逐轮检查点、实验日志、旧报告、旧数值图及重复图片。最终模型、完整数据集和当前符号图保留；必要路径已重定位。清单和保留数据校验见 `cleanup_20260923.json`。

服务器历史副本和项目外图形目录未删除。不要全量pull旧服务器项目，否则会重新引入已删除实验；后续应定向同步当前源码、模型和所需数据。

## 能量—力训练（2026-09-23新请求）

新增 `water10_v4/dense_force/`：完整30比特complex128伴随导数及混合二阶导数、连续编码、单能量头、力损失、批内可恢复训练和50 fs轨迹评价。17项小规模/恢复测试已通过；真实30比特验收和训练状态见 `reports/force_preparation_20260923/RUN_STATUS.md`。旧models/final不是本次训练结果。

用户已允许修改不连续编码：新版本采用质量中心化O坐标及单位角平分线xyz，移除0.1 rad编码下限。48个量子参数、60读出、60→64→32→1网络不变；部分编码门增加，旧线路图不代表新编码。质量中心化保证平移不变，未强制旋转不变；轨迹评价记录总力与力矩。

NFS下线期间在服务器独立本地目录运行，避免依赖/mnt/nfs。结果仅根据真实数据绘制，不使用nature-figure。
