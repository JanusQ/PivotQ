# Re-generated twenty-water MB-pol reference data

`water20.h5` 是新生成的 5,000 条完整二十水构型，包含 60 原子坐标、体系总能量和 \(60\times3\) 力标签。没有复制、拼接或补零十水坐标；每条标签由全部二十水共同参与的 MBX `System.Energy(true)` 与完整梯度产生。

| 数据划分 | 构型数 | 独立采样组 |
|---|---:|---:|
| train | 3500 | 35 |
| validation | 500 | 5 |
| test_id | 500 | 5 |
| test_trajectory | 300 | 3 |
| test_ood | 200 | 2 |

组划分在标签生成前确定，任何同源轨迹和扰动均留在原组。每组 100 个构型；测试组未参与 normalizer 拟合。每个组有独立随机种子和初始构型；原子固定 OHH 顺序，非周期柔性水簇。

采样流程：独立紧凑簇 → 有界 FIRE 松弛 → Langevin warmup → 间隔采样。普通组温度为 200/300/450 K；OOD 为 650 K。普通组每 10 帧有 7 条 thermal、2 条显式坐标 distortion、1 条整分子 boundary 平移；trajectory/ood 保留对应连续轨迹类别。具体 seed、步数、时间间隔和 MBX 配置在 `manifest.json` 与 `../configs/dataset.json` 中。

这是有明确来源的采样数据集，**不声称经过充分平衡或达到低温极小值**。本次 150 步 FIRE 预算中各组未达到设定的完整收敛阈值，该事实保存在 manifest，未改写为成功收敛。所有构型通过水分子键长/夹角、跨分子碰撞和有限标签检查；参考力另有能量有限差分审计。短轨迹帧有相关性，group split 用于避免这些相关帧跨划分。

位置单位 Å，能量 eV，力 eV/Å。标签是 MB-pol，经 MBX 提供，**不是 DFT 计算**，也不是量子模型预测。能量保留 MBX 原始模型能量约定，没有额外减单体能量、加核排斥或修改参考零点。

`normalizer.json` 只使用 3,500 条 train：质量中心化 Oxyz、OH 长度及总能量均值/尺度；记录训练 ID 哈希。`manifest.json` 保存数据/外部 MBX 动态库 SHA-256、完整采样配置、标签范围和采样组所有权。标签源的库保存在服务器外部 `PivotQ-runtime/mbx`，不把大型编译产物装入数据目录。

HDF5 的关键键：`positions_angstrom`、`energy_ev`、`forces_ev_per_angstrom`、`sample_id`、`split`、`category`、`group_id`、`md_step`、`temperature_K`、`atomic_numbers`、`molecule_id`。读取时可以直接选行，无需复制为 extxyz、CSV 或另一份 HDF5。

重新生成使用应用源码 `../water20/dataset.py` 与 `../scripts/generate_dataset.py`，必须指定实际 MBX adapter 动态库；不会覆写现有数据：

```bash
python -B scripts/generate_dataset.py \
  --library /absolute/path/libqaqua_mbx.so --output /new/output/dataset
```

外部 adapter ABI 及 MBX/FFTW 动态库需在生成机器可加载。推理只读取冻结 normalizer 和几何，不依赖 MBX；真机部署不需要把标注库带到设备端。
