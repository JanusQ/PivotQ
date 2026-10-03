# 十水 MB-pol 势能训练数据集

本数据集由用户于 2026-09-14 授权生成，目标是完整十水构型到一个 MB-pol 势能的监督学习。**标签是 MB-pol 模型能量，不是 ωB97M-V、DFT 或逐构型 CCSD(T) 电子结构计算结果。** 数据集是否冻结以 `selected/dataset_manifest.json` 为准。

已在 pcie5 完成5000条标签并通过验收。32个构型的有限差分最大绝对误差约为 \(7.86\times10^{-7}\) eV/Å。标注循环约12.86秒，包含输入检查、数值审计、导出和回读的自动生成流程约28.55秒；不含此前代码准备和文件同步时间。

## 数据入口

主文件为 `selected/water10.h5`，共5000条真实 MBX 计算的能量与解析力标签。`selected/` 同时提供各 split 的 extxyz、`splits.csv`、`nested_train_ids.json` 和 `normalization.json`。

| split | 数量 |
|---|---:|
| train | 3500 |
| validation | 500 |
| test_id | 500 |
| test_trajectory | 250 |
| test_ood | 250 |

训练集保持2450 thermal、700 distortion、350 boundary。验证集与普通测试集各保持350/100/50。轨迹测试保留5段各50帧的连续片段；外推测试含125个未见网络点和125个距离外推点。250、500、1000、2000、3500条嵌套训练前缀保持70/20/10配比，不重划分验证和测试。

| HDF5 字段 | 含义 |
|---|---|
| positions_angstrom | float64，形状 `(5000,30,3)`，完整原子坐标 |
| energy_ev | float64，形状 `(5000,)`，原始 MBX 模型能量，eV |
| forces_ev_per_angstrom | float64，形状 `(5000,30,3)`，完整势能的负梯度 |
| energy_centered_ev | 仅减去3500条训练数据均值的能量 |
| atomic_numbers / molecule_id | 固定 O,H,H 排列及10个分子的身份 |
| sample_id / split / category | 样本、划分与构型类别 |
| coordinate_sha256 / metadata_json | 坐标哈希、轨迹和采样来源信息 |

## 能量定义与计算

所有30个原子同时传入 MBX `System.Energy(true)`；采用原始 `h2o` 单体定义、非周期、柔性水，包含该模型完整的内部形变、分子间相互作用与多体极化。不是把旧1B/2B/3B训练标签拼接，也不是四个独立监督目标。

保留 MBX 自身的能量零点，不再减单体能量，不另加核排斥、动能、D3/D4或DFT修正。原始能量不可直接作为DFT绝对电子能；其差异也不能仅用常数校正消除。`config/reference.lock.json` 保存commit、二进制/源码哈希、MBX设置、转换常数及环境。`reports/numerical_audit.json` 另记录指定单水几何的原始模型能量，不把近似参考几何声称为精确势能最低点。

训练可使用 \(y=E-E_{\mathrm{shift}}\)。其中 \(E_{\mathrm{shift}}\) 只能由当前使用的训练子集计算。各标准前缀的均值和标准差在 `normalization.json`；自定义子集必须重新拟合。数据加载器默认不返回力，显式请求才返回。

## 读取与复现

在本数据集目录执行：

```python
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path('code').resolve()))
from dataset_loader import load_dataset, fit_train_normalizer
ids = json.loads(Path('selected/nested_train_ids.json').read_text())['250']
train = load_dataset('selected/water10.h5', sample_ids=ids)
normalizer = fit_train_normalizer(train)
validation = load_dataset('selected/water10.h5', split='validation')
force_test = load_dataset('selected/water10.h5', split='test_id', include_forces=True)
```

生成在 `zhanghao@pcie5-up.rc4ml.org` 上执行，项目根目录为 `/mnt/nfs/home/zhanghao/code/multi-h2o-aimd-v3`，解释器为 `/mnt/nfs/home/zhanghao/envs/water10-pyscf/bin/python`。从项目根目录运行 `python scripts/generate_mbpol_dataset.py`；存在冻结清单时仅核验，不覆盖数据。


## 验收与局限

检查包括5000条坐标身份/几何、精确划分和家族隔离、独立近重复检查、连续轨迹、外推网络、32个分层构型的有限差分与旋转/平移/水分子置换/H交换、全部5000点总力/力矩、已有提议能量对照、HDF5和extxyz回读、energy-only加载及子集归一化。

结果与实测耗时在 `reports/final_quality_report.json`、`reports/labeling_metrics.json` 和 `reports/numerical_audit.json`，分布图在 `figures/`。本次没有训练电路，没有证明量子优势或DFT精度。MB-pol采样加MB-pol监督用于拟合该势函数，不能把测试误差解释为独立电子结构精度验证。


## 独立数据包（2026-09-14 迁移）

本目录包含读取、核验和重新标注所需的全部数据文件，不再依赖旧 DFT 数据目录或项目外的数据集。原有 5000 条数据、划分、归一化参数及冻结清单保持字节不变。

- `selected/water10.h5`：实验直接读取的主数据。
- `code/dataset_loader.py`：读取器；默认仅能量监督，力可显式启用。
- `inputs/`：原始构型、候选池、轨迹、划分与来源审计。
- `vendor/mbx/`：MBX 源码、接口、官方示例和已编译库。
- `code/generate_dataset.py`：用包内构型重生成标签与完整数值验收。
- `provenance/source_relocations.json`：冻结方法锁中的历史路径到当前包内路径的映射。历史记录中的旧目录名不是运行依赖。

在 pcie 服务器运行（下列命令以本数据包目录为工作目录）：

```bash
/mnt/nfs/home/zhanghao/envs/water10-pyscf/bin/python -B code/verify_package.py
/mnt/nfs/home/zhanghao/envs/water10-pyscf/bin/python -B code/generate_dataset.py
# 需要全量重生成时指定新输出目录，现有冻结数据不会覆盖：
/mnt/nfs/home/zhanghao/envs/water10-pyscf/bin/python -B code/generate_dataset.py --output-dir /tmp/water10_rebuild
```

软件环境仍需 Python、NumPy、h5py；重新标注额外使用 ASE、SciPy、NetworkX、PyYAML、Matplotlib 和 MBX/FFTW。服务器现有环境可直接使用。MBX 二进制为服务器 Linux 构建，其他系统需用所附源码重新编译；这属于软件依赖，不需要其他数据集。
