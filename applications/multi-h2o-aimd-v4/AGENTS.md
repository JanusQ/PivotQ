# PivotQ 十水应用工作约定

- 当前应用位于 PivotQ 的 applications/multi-h2o-aimd-v4，Python 包名为 water10_v4；运行时不得读取相邻 qhai-2026 或旧服务器目录。
- 迁移来源及原工作约定保存在 provenance/。历史主机、训练授权与自动跟进仅为来源记录，不是当前任务授权。
- 保持 models/final、models/experimental/current_model.json 和完整 dataset_water10_mbpol_v1 的原始字节，不更改标签、划分、normalizer 或冻结权重。
- models/experimental/current_model.json 是 11 次更新的未收敛模型，仅用于运行验证；不得称为最终模型。
- 本次允许在当前机器进行 CPU 能量、解析力、短程 MD 与真实 Ray 能量链路验证；不训练、不恢复旧训练、不调用真实 QPU。
- 完整十水为 30 原子、30 比特、60 维 X/Z 读出。数值验收使用完整双精度状态向量，无 MPS、比特裁剪或子系统替代。
- 解析力采用已有连续编码及状态向量伴随导数；原冻结能量模型使用其原编码。不得混淆两种模型或修改正式 50 fs 验收门槛。
- 短跑默认单 worker、8 线程；检查宿主机与 cgroup 内存，解析力预留至少 96 GiB。使用 PYTHONDONTWRITEBYTECODE=1。
- 新运行写入独立 outputs 子目录；编译缓存、轨迹、日志不加入 Git。可将小型验收摘要及来源哈希保存在 provenance。
- 成功运行只表明软件链路完成，结果保持 scientific_status=not_validated，不宣称模型准确性或真实 QPU 验收。
- 修改融合接口前阅读 融合框架与性能模拟器对接.md 和 water10_v4/integration/fusion_framework/BRIDGE.md；接口变化同步更新文档。
