# 三比特 QPU 局域网接入

公共入口：QuantumCircuitRequest、CircuitResult、QPUCircuitService。
measurement_basis 支持 X/Y/Z，shots 默认 3000，measurement_qubits=[0,1,2]。
probabilities 必须包含 000 到 111 全部八个状态，零概率显式为 0.0。
设备适配层确认完整性后补齐真实零值，AIMD 缺键即报错。
多比特接口后续实现。

框架服务器上的 QPUClientComponent 直接导出 QASM3，不检查电路类型、宽度或参数绑定，
不添加门或测量，不修改输入。导出失败抛出 CircuitExportError。
客户端只申请 CPU，Ray 集群各节点均为已准备好的计算服务器，无需专属资源标记；设备节点不安装本包。

设备接入集中在 device_adapter.py：在调用时直接导入 qasm_client.ExperimentClient，
将 QASM3 写入临时文件后 submit 一次，按 job_id 调用 wait，并清理客户端和文件。
地址和密钥来自构造参数 server_url/api_key 或计算节点环境 QPU_DEVICE_URL/QPU_DEVICE_API_KEY。
shots 暂映射 reps（每电路语义待确认），其他实验参数使用 SDK 默认值。

qasm_client 后续由设备方提供；_decode 按要求留空，明确抛出 DeviceProtocolNotConfiguredError。
需要在该函数补齐原始结果到 DeviceCircuitResult 的映射；已有 normalize_results 负责八状态返回。
缺配置或 SDK 时不会提交，配置后则可能已执行设备任务再因解码缺失报错，不可盲目重复提交。
默认超时/重试、实际 shots/位序/完整性、测量准备等 TODO 全部留在此文件。
close 只释放自己拥有的资源，不取消硬件任务；没有自动模拟回退。

见项目 docs/QPU_QASM3_CLIENT.md。真机包 AIMD 启动与八状态结果消费已适配，Y 科学特征另行安排。
