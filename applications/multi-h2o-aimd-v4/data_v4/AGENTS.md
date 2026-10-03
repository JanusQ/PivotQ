# v4 派生数据约定

- 本目录只保存由冻结数据派生的样本名单和归一化参数；原始数据仍在项目的 `dataset_water10_mbpol_v1/`，不得修改其冻结文件。
- `panels.json` 由 `scripts/prepare_v4_data.py` 确定性生成，不根据能量或实验效果挑选样本。pilot-32来自冻结train-250，validation-64来自原validation，不重新划分数据集。
- `normalizer_pilot_train_32.json` 只服务32条阶段，`normalizer_train_250.json` 只服务250条阶段。更小/更大面板必须保存新的ID与对应normalizer，验证/测试不能参与拟合。
- 这些文件是数据准备产物，不代表任何训练已完成。不将不同normalizer下的损失直接拼接为一条曲线。
- 改动生成逻辑或数据契约后在pcie5重跑适配核验，结果保存至 `reports/dataset_adaptation_report.json` 并同步回本地。
