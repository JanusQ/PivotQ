# 当前运行状态与交接

2026-09-23启动准备。**尚未报告模型收敛或生成真实50 fs轨迹**。

## 当前阶段

**2026-09-24 用户要求停止：训练和守护进程已退出，服务器run/STOP保留，自动跟进`50fs`已暂停。不会自动训练或执行50 fs。**

第1轮完成37/3500训练样本、11次参数更新；停止时当前8样本批次已有6个样本梯度原子保存在latest.pt，但尚未用于第12次更新。最新current_model.json对应第11次更新，不是收敛模型。服务器latest.pt/current_model.json的SHA256分别为`54b76ec56afeab1b3d2f6c457aa80a664fd515da815995fcbdd7f6e6e90d8d59`/`664c59820a887e48e8ec63a1a28dfd8235f914553f9264fbc84b74a18cca44ae`；本地current_run副本校验一致。没有真实50 fs轨迹或评价图。


- 17项软件测试通过：Qiskit状态/读出对照、参数移位一阶梯度对照、混合二阶导数与力损失梯度核验、连续编码及平移不变性、力标签顺序、批内恢复、解析测试势上的MD计步与恢复。
- 解析测试势的501帧仅为临时测试，不能用来交付真实AIMD图。
- MBX参考库在独立环境恢复，冻结训练构型的能量/力误差均为0。
- 实际30比特连续编码前向约175.92秒，60维读出与Aer最大误差5.7062e-11。
- 2026-09-23 11:23（北京时间）完整30比特验收通过：能量/力计算903.36秒、力损失反向2975.65秒，峰值RSS 69,032,583,168字节（约64.29 GiB），梯度有限。验收没有优化器更新。
- 最新服务器检查：epoch 1、position=37/3500、updates=11。前一批4个样本完成后，新调度器保持8 worker并启动8样本批次；模型和检查点已同步current_run。无失败，约685 GiB可用内存、swap=0、磁盘余23 GiB。训练远未收敛。
- 守护进程PID174987，driver PID174989。不要重复启动。实时状态以服务器JSON和进程为准。

## 服务器位置

- 主机：zhanghao@pcie5-up.rc4ml.org
- 独立工作目录：`/var/tmp/water10-energy-force-20260923`
- 代码：`/var/tmp/water10-energy-force-20260923/project`
- Python：`/var/tmp/water10-energy-force-20260923/venv/bin/python`
- 运行：`/var/tmp/water10-energy-force-20260923/run`
- 原验收工作目录：`/tmp/water10-force-preflight.zZ1GK2`
- 当前完整验收JSON：`/tmp/water10-force-preflight.zZ1GK2/dense_force_acceptance_native/preflight.json`
- 首版慢内核预检已经停止并由native版本替代；不要把旧目录的running字段当作活动任务。

NFS在过程中下线，因此正式文件不依赖/mnt/nfs；服务器本地保留完整冻结数据包。环境为Python3.10.12、PyTorch2.5.1+cpu、NumPy2.2.6、Qiskit2.5.2、Aer0.17.2。源码、数据哈希和版本见run/software_acceptance.json。

## 流程与检查点

`supervise_force_run.py`等待真实规模验收通过→`dense_force.training train`→验证联合损失连续10个完整epoch无显著改善时停止→`dense_force.aimd`运行500步（0.1 fs/步）→本地生成图。

- 用户没有批准100轮/7天硬上限，按其最新要求继续并及时保存。
- `latest.pt`：模型、Adam状态、epoch、样本位置、已完成批内梯度；原子写入。恢复跳过已保存的梯度。
- `current_model.json`：每个完成优化批次后导出。
- `epoch_NNNN.pt`：每个完整epoch保留。
- `best.pt`、`best_model.json`：真实最小验证联合损失的模型。
- `status.json`、`supervisor.json`、`termination.json`（如有）：检查当前阶段、PID、失败。
- `training.log`、`aimd.log`、`batches.jsonl`、`history.json`：运行与指标。
- 并行从1开始，随完成批次的吞吐及内存调整；批量随并行增加、上限8。用户最新授权使用空闲资源并保留100 GiB可用内存；每worker至少96 GiB工作预算，并参考1.4倍实际峰值。每worker 8个C++线程。
- plateau是优化停止条件，不等同于物理精度保证；必须展示真实验证误差与轨迹参考误差。

停止：在服务器run目录创建`STOP`。正在执行的内核在下一门边界停止，保留最近已完成样本检查点。用户要求停止时也暂停自动跟进，不自动删除STOP或恢复训练。

## 后续自动跟进

Codex线程heartbeat：`50fs`，每小时跟进；无变化时不通知。原验收PID消失且未通过时，检查错误/SSH中断，修复后重新以脱离SSH方式运行验收，禁止跳过验收。守护若已退出，在确认STOP不存在且用户仍授权继续的情况下恢复；不能启动重复训练。

定向同步新运行检查点与日志到本目录current_run子目录。不要全量拉取旧NFS实验。

## 轨迹和图

- `run/aimd_50fs/frame_000000.npz`至`frame_000500.npz`，包含位置、速度、模型能量/解析力、温度、结构指标和同构型MB-pol参考能量/力。
- 轨迹50fs完成后才绘制完整50fs评价图；失败则保留真实部分结果并诊断，不补造帧。
- MBX需要环境变量`WATER10_FFTW_LIBRARY=/var/tmp/water10-energy-force-20260923/runtime-libs/extracted/usr/lib/x86_64-linux-gnu/libfftw3.so.3`。只在私有目录解包Ubuntu依赖，未修改系统库或冻结数据。
- 用户明确禁止nature-figure；直接使用`文档/energy_force_aimd/plot_results.py`，以真实run目录为输入，用Python/Matplotlib输出SVG/PNG及源数据CSV。查看实际图像后再交付。
- 尚未绘制真实训练或AIMD结果图。原models/final和旧图仍属于旧MPS模型，不能替代本次结果。
