# 60-qubit hardware contract

本接口根据 005 真机交接包的 `device_adapter.py`、`parallel_shots.py` 和 `qasm3_export.py` 实现。复用实际 HTTP 生命周期和列名约定，重新定义全局 60 比特的内部请求/结果类型。来源实现的三条独立三比特 lane、八状态概率、九比特固定映射没有搬入新应用。

## 部署 profile

`configs/hardware_profile.template.json` 是明确未配置的模板，不能提交。实际设备 profile 必须包含：

| 字段 | 含义 |
|---|---|
| `schema_version=1`, `n_qubits=60` | 应用侧 profile 版本与宽度 |
| `capability_status=confirmed_60_qubit_global_circuit` | 确认支持跨分子的全局电路；不是多个独立 lane |
| `mapping_version` | 可追溯的映射/标定版本 |
| `physical_labels` | 60 个唯一 `qNN` 标签，按上传 `q[slot]` 的寄存器槽位排序 |
| `coupling_edges` | 实际连通子图，用槽位 0–59 表示；必须包含所有槽位 |
| `initial_layout` | 逻辑线到槽位的完整置换 |
| `native_gates=[rx,rz,cz]` | 本适配器支持的原生门 |
| `terminal_measurement=server_z` | 和来源实际 QASM 一样，由设备末端 Z 读出 |
| `result_format=shot_table` | 支持完整逐 shot 六十位读出 |
| `shot_index_base=0` 或 `1` | 真实设备 shot 编号起点 |
| `max_depth`, `max_gates` | 设备确认的编译后电路预算 |

这些字段是应用的配置，不是自行添加的服务器表单字段。必须依据设备实际能力填写；交接包只证明了三/九比特历史返回，不能证明六十比特全局执行。用户要求本次无需连接真机测试，所以本次不产生六十比特实机运行证明。

Qiskit 路由可能改变末态所在槽位。`hardware.prepare` 保存 `final_index_layout()`，将**每个逻辑线**对应到最终 `result_qNN` 列；不按 CSV 位置猜测，不依赖初始映射恢复结果。上传前校验每个 CZ 的实际边、60 比特宽度、已绑定参数、门集和深度预算。原生导出没有中间测量、reset 或未绑定 theta。

## 实际 HTTP 约定

1. 从 `QPU_DEVICE_URL` 连接服务，`QPU_DEVICE_API_KEY` 可选 Bearer；客户端关闭环境代理，日志不保存认证头。
2. `GET /health` 必须为 `status=ok, backend=circuit`。遵守 `limits.max_circuits/max_file_bytes`，缺失时按来源默认 32/1048576；如有 `max_qubits` 则检查不小于 60。全部 QASM 文件大小在任何提交前校验。
3. `POST /v1/jobs` 使用重复 multipart `files` 字段，文件为 `.qasm` basename。`parameters` 为 JSON 字符串：`{"reps": shots, "measure_base": "Z", "use_DD": true, "DD_type": "X", "parallel": true}`。参数已绑定在 QASM 内，不额外扫描 theta。
4. 获取 `job_id` 后，`GET /v1/jobs/{job_id}?wait_seconds=0`。queued/running 继续查询同一个 ID；succeeded 才解码；failed/interrupted 终止，未知状态或 ID 不一致进入不确定状态。
5. POST 前独占创建、落盘 journal；POST 超时或返回不可关联时拒绝自动重投。同一 request ID、相同 payload 重新调用会读取保存的 job ID，继续查询或复用已完整结果。payload 包含服务标识、映射、shots 和 QASM；任何变化不能借旧记录重放。

本接口不新增未经确认的取消/幂等 HTTP endpoint。需要中止时停止调用者；远端已提交作业须依据设备服务本身管理。POST 尚未保存 usable job ID 的不确定 journal 需要对账获得真实 ID，不能删除记录后自动重投。单个 Actor 内请求串行；跨应用硬件独占/准入由设备服务或站点调度管理，CPU 配额不能充当物理 QPU 锁。

## 返回校验与读出

成功记录必须包含正确 job ID、`backend=circuit`、`status=succeeded`、`error=null`、匹配 reps 和 Z 基、完整文件 index/name manifest。`result.columns/data` 包含 `shots,circuits` 和 60 个物理标签；接受 JSON 中 `result_qNN` 或 CSV/INI 中 `qNN`，总是按列名寻找。

严格拒绝：未知/重复文件、未知 circuit index、重复或缺失 shot、越界 shot 编号、非二值读出、错列/缺列、非实测理想概率和不完整成功结果。文件响应顺序可以变化，输出按原 circuit ID 关联顺序返回。

结果的位串按逻辑 q0…q59 从左向右排列；与 Qiskit 常见打印 counts 的位序不同。同一次 shot 的联合信息保存在稀疏 counts，至多包含实际已观察的状态；不补全所有可能状态，不用单比特概率乘积伪造关联。

$$
\widehat{\langle P_q\rangle}=\frac{1}{S}\sum_{s=0}^{S-1}(1-2b_{s,q}),\qquad P\in\{X,Z\}.
$$

X 电路已经在应用端追加换基，Z 电路无需换基，两者仍由设备固定 Z 读出。结果回传 requested/actual shots、完整性、映射版本、物理列、job/file 关联、120 个期望及样本标准误差。全相同样本导致的零样本方差不是零硬件不确定性的证明。

## 力接口

默认硬件力方法为 `coordinate_fd`，差分位移为 0.02 Å，可用 `--fd-step-angstrom` 调整；MD 时间步长仍由独立的 `--dt-fs` 控制。CPU 默认使用伴随法。每条测量电路默认 3,000 shots，可用 `--shots` 调整。

可选 `parameter_shift`：先在原构型计算一次 120 维特征及经典能量头的输入梯度。每次仅移位**一个 Pauli 门实例**，计算特征导数，再乘连续角的坐标 Jacobian；多次出现的共享参数按各实例 coefficient 累加，不能一起移位套单门公式。

$$
\frac{\partial\langle O\rangle}{\partial a_g}=\frac{\langle O\rangle_{a_g+\pi/2}-\langle O\rangle_{a_g-\pi/2}}{2},\qquad
\mathbf F=-\frac{\partial\widehat E}{\partial\mathbf z}\frac{\partial\mathbf z}{\partial\mathbf a}\frac{\partial\mathbf a}{\partial\mathbf R}.
$$

经典编码 Jacobian 采用中心差分，默认步长为 0.000001 Å，未声称是解析坐标导数。原构型活动列表固定；quintic support 边缘的一、二阶导数为零，避免组合数变化破坏门索引对应。

以当前图示构型为例，1,158 个逻辑 Pauli 实例，逐实例移位需要 4,634 个 X/Z 设置；共享参数仍为 48。默认 `coordinate_fd` 每次力查询为 361 个几何、722 个测量设置。0.02 Å 是面向低精度轨迹演示的初始选择，尚未经真机标定。两种方法均有有限 shots 噪声与实际硬件耗时，成功运行不能证明初始化模型的力准确。

## 融合与验证边界

`water20.fusion.register` 使用 PivotQ 的公共 Component/Invocation 接口，量子 CPU 为真实 Ray Task，QPU 为常驻串行 Actor，经典头为同一个常驻 Actor。不会调用固定三比特 QPU service。后端必须显式指定；QPU 失败不回退成 CPU。

服务器实际验证的是 CPU Task→Actor 和独立 CPU MD。离线硬件测试使用明确标为 TEST_ONLY 的合成拓扑/返回，覆盖路由、multipart、关联、完整性及异常恢复；它们不是实机标定/执行记录。当前 transpile SVG 是 native-basis-only；真正的 profile 路由在提交入口按每个绑定构型执行。
