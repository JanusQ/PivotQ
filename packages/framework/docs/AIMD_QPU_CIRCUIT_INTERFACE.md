# AIMD 三比特 QPU 电路接口

当前协议：`qasm3-full-3q-v1`，D-102 / P8.1-QPU-FULL-PROBABILITIES-1。

## 输入

```python
from pivotq._internal.qpu_integration import QuantumCircuitRequest, QPUCircuitService

request = QuantumCircuitRequest(
    circuit_id="sample-001.Y", circuit=y_circuit, measurement_basis="Y",
)
results = QPUCircuitService(framework, context).run_quantum_circuits(
    step=0, circuits=[request], shots=3000,
)
```

电路由 AIMD 构造。现阶段保留三逻辑比特约定，多比特以后实现。
框架只校验请求 ID、X/Y/Z 元数据、step 和正整数 shots，不预检电路类型、宽度、
参数绑定、门或测量。QASM3 导出失败明确报错，导出成功不等于设备接受。
框架不添加基变换；Y 电路需由应用包含正确的基变换。末端测量如何补齐仍待设备协议。
函数签名不变，shots 默认 3000，step 在同一 run 内每次调用唯一，范围 0..999999。

## 输出

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

结果保持提交顺序，字符从左到右对应逻辑 q0、q1、q2，按 000 到 111 返回全部八个状态。
零概率显式为 0.0；设备适配层确认完整分布后才补齐零值。AIMD 缺键即报错。
不接受未知完整性、截断分布、错误位序、实际 shots 不符或缺失电路结果。
设备实际返回 counts 时，先检查计数和，再除以实际 shots；不覆盖实际 shots。

## 当前可用范围

服务由服务器侧客户端 Actor 支撑；设备不部署融合框架。
真实网络协议、输入输出映射和测量准备集中在 `device_adapter.py`，目前明确报未配置错误。
本轮只支持离线契约验证，不能直接执行真机。

真机包 AIMD 启动脚本已适配服务器侧客户端，结果校验已恢复八状态要求。
AIMD 仍使用 Z/X 的 14 维特征；Y 科学特征另行安排。设备协议仍未实现。

完整部署、失败与待补事项见 [QPU 局域网客户端说明](QPU_QASM3_CLIENT.md)。
