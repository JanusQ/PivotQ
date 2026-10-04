# QPU 局域网客户端交接说明

当前返回约定：P8.1-QPU-FULL-PROBABILITIES-1 / D-102，三比特完整八状态概率。
D-100 的服务器侧 QASM3 导出、X/Y/Z 与 D-101 启动适配保持不变。
当前调度按 D-103 取消服务器专属标记，Driver 和组件使用原有 CPU/GPU 需求。
D-104 已按设备示例实现 qasm_client 的文件提交和等待；SDK 待提供，结果解析仍留空。
配置后调用可能执行设备任务并在解码时报错，尚不能完成 AIMD 真机计算。多比特接口后续单独实现。

## 1. 部署和调用链

```text
AIMD → QPUCircuitService → Ray 管理的 QPUClientComponent（框架服务器）
     → QASM3 临时文件 → QPUDeviceAdapter → qasm_client → 设备局域网服务
     ← list[CircuitResult] ← 完整结果校验及八状态补齐
```

设备侧不安装 pivotq._internal，不创建框架 Actor。框架服务器上的客户端 Actor 负责通信，
保留 Component/Invocation/Trace/清理机制。它不持有物理设备资源令牌。

注册入口仍是 `pivotq._internal.qpu_integration.registration:register_components`，
组件 ID 仍是 `qpu-circuits`，Actor 只申请 CPU:1，不附加服务器专属资源。
用户确认 Ray 集群只包含具备运行条件的计算服务器，因此按 CPU/GPU 可用容量调度。
部署时各计算节点需要相同框架、必要依赖和可见的应用文件；设备只提供局域网服务。

框架通用 Job Driver 保留 CPU:0.2，真机包 AIMD Driver 默认 CPU:1；
AIMD 的 CPU/GPU 组件保留原有请求。提交器不再提供服务器标记参数或传递相应环境变量。
去掉放置约束不会自动准备节点环境，也不保证 Driver 和两个 Actor 落在同一台服务器。

每个服务实例允许一个在途调用，客户端 Actor 的 max_concurrency=1，直接并发调用不另建等待队列。
这不是全局硬件独占保证；多作业排队、设备并发和准入仍待设备协议确认。
同一个 Actor 的 Ray 邮箱没有在此引入新的全局容量控制，调用方应使用同步服务入口。

## 2. AIMD 公共接口

```python
from pivotq._internal.qpu_integration import QuantumCircuitRequest, QPUCircuitService

# y_circuit 由应用构造，已包含应用需要的 Y 基变换。
request = QuantumCircuitRequest(
    circuit_id="sample-001.Y", circuit=y_circuit, measurement_basis="Y",
)
results = QPUCircuitService(framework, context).run_quantum_circuits(
    step=0, circuits=[request], shots=3000,
)
```

公共名称与函数签名不变；`measurement_basis` 取值为严格大写 X/Y/Z。
该字段是应用提供的元数据，框架校验并回传，不根据标签添加 H、S† 或其他基变换。
shots 是每条电路的采样次数，默认 3000；必须为正整数。
step 在同一 run 内每次调用唯一，范围 0..999999，用于构造内部请求关联 ID。

本轮按用户最终确认继续保留三比特输入输出约定。调用方负责提供约定的电路；
框架不额外检查电路类型、宽度、参数绑定、门集合或测量结构，直接调用 Qiskit QASM3 导出器。
这不代表多比特设备接口已经实现，也不代表成功导出的程序必然被设备接受。

返回示例（完整八状态，零概率显式返回）：

```python
{
    "circuit_id": "sample-001.Y",
    "shots": 3000,
    "measurement_basis": "Y",
    "measurement_qubits": [0, 1, 2],
    "probabilities": {
        "000": 0.0, "001": 0.25, "010": 0.0, "011": 0.0,
        "100": 0.75, "101": 0.0, "110": 0.0, "111": 0.0,
    },
}
```

每条结果使用三位 bitstring，字符从左到右对应逻辑 q0、q1、q2。
必须包含 000 到 111 全部八个键，零概率为 0.0；AIMD 按键读取，缺键即报错。
设备原始结果若省略真实零值，适配层仅在确认完整性后补齐，不把未知数据补零。
禁止返回被截断的 top-k 分布或把未知/未返回的数据当作零。

设备适配器必须确认结果完整、实际 shots 等于请求值、实际逻辑测量映射为 [0,1,2]，
再转换设备位序。框架校验缺失/重复/未知 circuit_id，并恢复提交顺序。
counts 必须是非负整数且总和等于实际 shots，再转换为概率；概率必须有限、在 [0,1] 内，
总和在 1e-6 绝对容差内为 1。完整性必须由设备协议证明，概率和为 1 本身不够。
不会把实际 shots 覆盖成请求值，不反推 counts，不自动重归一化部分结果。

## 3. QASM3 导出

`qasm3_export.py` 调用 `qiskit.qasm3.dumps()`，返回 UTF-8 可编码的文件内容；
批内文件名为 `circuit-000000.qasm` 等，与电路 ID 分开，避免将 ID 当作文件路径。
不写远端路径、不添加测量、不删除操作、不重编译、不修改应用电路。
导出器拒绝输入时抛出 `CircuitExportError`，错误摘要不含电路正文。

末端 measure 是否由文件提供仍待确认：当前内容忠实保留输入。需要额外测量准备时，
在下一节的适配文件中按已确认的设备要求处理副本，不能静默让两端各补一次。

## 4. 设备客户端和唯一待补文件

实现及未知项都集中在 `pivotq/_internal/qpu_integration/device_adapter.py`。

`_exchange()` 已按设备示例实现：

1. 读取 `QPU_DEVICE_URL` 和 `QPU_DEVICE_API_KEY`，也可用构造参数 `server_url`、`api_key` 覆盖。没有示例 IP 或密钥默认值。
2. 实际调用时执行 `from qasm_client import ExperimentClient`；普通框架导入无需预装该 SDK。安装方式由设备方后续提供。
3. 在临时目录写入 UTF-8 QASM3 文件，通过 `with ExperimentClient(url, api_key=key)` 建立客户端。
4. 调用一次 `client.submit(paths, parameters={"reps": shots})`，取得 `job["job_id"]` 后调用 `client.wait(job_id)`；只接受 `status == "succeeded"`。
5. 客户端退出后清理临时文件，返回内部 `DeviceJobResponse`，保留任务编号、电路元数据、请求 shots 和原始结果供解码。

`reps` 暂映射为每电路 shots，需设备方确认含义；不传 `theta`、`cosine_env`、`read_delay_ns`，使用 SDK 默认值。
地址和密钥必须在运行 Actor 的计算节点可见。现有 AIMD 提交器不会自动转发本地终端的这些变量；
应在每个计算节点启动 Ray 前配置其继承环境，或由部署方显式配置作业环境。不要把密钥写进源码或提交日志。

`_decode()` 按用户要求留空并抛出 `DeviceProtocolNotConfiguredError`，错误带 `job_id`。
待设备提供原生结果示例后，在此映射电路 ID、实际 shots、逻辑位序、counts/概率和分布完整性，
返回 `DeviceCircuitResult`；已有 `normalize_results()` 再生成 AIMD 的八状态格式。
任务 succeeded 不等于分布完整，不能用请求 shots 冒充实际采样数。上述两个 dataclass 都不是对端报文约定。

待确认项还包括 SDK 默认超时/内部重试/取消/去重、批量限制、QASM3 方言和末端测量要求；
没有猜测 HTTP 路径、上传编码或额外 SDK 参数。缺少配置或 SDK 时在提交前报错；配置齐全后可以执行上传/等待，
**但设备成功后仍会停在未完成的 `_decode()`，不能直接用于完整 AIMD 运行。**

测试通过显式 factory 注入
`tests.fixtures.qpu_device_fake.RecordingDeviceAdapter`，该 fixture 返回固定 counts，
或在单元测试中注入假的 qasm_client，仅验证通信契约，不模拟量子计算或产生科学结果。

## 5. 失败与清理

框架不会自动重试设备提交。超时/断线可能发生在设备已接受请求之后，应按请求和设备任务编号对账。
request_id 本身不提供幂等性；已有 wait(job_id)，持久化恢复查询和取消仍待 SDK 资料。
SDK 内部重试与超时默认值尚未核实；框架不把一次 submit 调用宣称为设备仅执行一次。
日志只记录请求/任务编号，异常只输出阶段和异常类型，不输出 SDK 错误正文或原始结果。
Actor close 仅释放自己拥有的客户端资源，不终止共享设备服务，不宣称硬件执行被取消。
60 秒等待提醒继续保留；Trace 表示框架调用生命周期，不是设备执行时间的权威证明。

## 6. AIMD 与发布包的衔接

真机包 AIMD 启动配置已按 D-101 适配；D-102 恢复八状态严格校验，三比特 Z/X 电路及
14 维特征不变。D-104 不修改 AIMD 接口或代码；Y 科学特征与多比特仍待后续决定。
SDK 与结果解析仍未齐备，不能直接完成真机计算。

当前活动实现维护在 PivotQ 的 `packages/framework/pivotq/`。`real-qpu-test-package` 为独立历史交付快照，保留其原接口与来源哈希，不随本次 SDK 包迁移改写。
包内 AIMD 仅适配启动链路和结果契约；checkpoint、数据、科学电路、候选副本与历史源码不改。

## 7. 离线验收

D-104 的假 SDK 测试覆盖文件内容/生命周期、默认参数、任务等待、异常不重提和解码明确占位；
完整回归结果见主仓库 docs/codex/PROGRESS.md 和真机包 manifests。实际 SDK 和设备均未验证。

D-103 历史结果：主仓库 250 passed、3 skipped、145 subtests；真机包框架 239 passed、
3 skipped、140 subtests；AIMD 40 passed、5 subtests。覆盖无服务器标记的资源请求、CPU/GPU 配额、
旧参数拒绝和旧环境变量不影响注册，同时保持 QASM3 与三比特完整概率契约。

D-102 历史结果：主仓库 251 passed、3 skipped、145 subtests；真机包框架 240 passed、
3 skipped、140 subtests；AIMD 47 passed、5 subtests。已验证完整八状态、显式零值与缺键拒绝。

目标环境：Python 3.12 / Ray 2.31.0 / Qiskit 2.5.1。
聚焦测试为 test_qpu_qasm3_export.py、test_qpu_device_adapter.py 和 test_aimd_qpu_integration.py；
随后运行活动 unit 和离线 wheel 冷导入检查。测试不初始化 Ray、不连接网络、不执行真实设备。
D-100 阶段主仓库 250 passed、3 skipped、145 subtests；真机包副本 239 passed、3 skipped、
140 subtests，均包含一项离线 wheel 检查。三个 skip 都是已归档的旧 Job 清理契约。
测试入口禁止 ray.init 和 socket 连接；使用固定本地 IP 替代 Ray 错误类型的路由探测。
实际命令与日志索引见主仓库 docs/codex/PROGRESS.md；设备联调与多节点放置验证另行安排。
