# PivotQ Python SDK

PivotQ 用普通 Python 函数组合 CPU 计算和量子电路执行。用户选择执行后端，
通过结果引用连接依赖，用 Python 的循环、条件和函数组织自己的混合程序。

## 安装与运行

支持 Linux x86-64、Python 3.12；Ray 版本为 2.31.0，Qiskit 为 2.5.1。
从 PivotQ 仓库根目录执行：

```bash
python3.12 -m venv .venv-sdk
. .venv-sdk/bin/activate
python -m pip install ./packages/framework
python packages/framework/examples/hybrid_program.py
```

也可以安装本地构建的 pivotq wheel。目前不以 PyPI 上的同名包作为安装来源。
设备 HTTP 通信需要可选依赖：`python -m pip install "./packages/framework[qpu]"`。

```python
import pivotq as pq

def double(value):
    return value * 2

with pq.Runtime(executor="local") as runtime:
    first = runtime.submit(double, 3)
    second = runtime.submit(double, first)
    print(runtime.get(second))  # 12
    runtime.release(second, first)
```

量子电路通过 `runtime.quantum_backend("simulator")` 或已注册的 QPU Provider
提交。`backend.submit(circuit, shots=1024)` 返回结果引用，可以直接传给经典任务。
`runtime.get(ref)` 返回业务结果，失败时抛出结构化异常；重复取值不会自动释放结果。

完整可执行例子见 [hybrid_program.py](examples/hybrid_program.py)。其参数反馈规则用于
展示编程流程，不代表 VQE 优化器。运行本机 Ray 版本：

```bash
python packages/framework/examples/hybrid_program.py --executor ray --address local
```

## 使用指南

完整文档与门户共同维护在仓库的 `website/src/content/docs/`，通过网站的“参考文档”
阅读安装、快速上手、组件与 Actor、工作流、量子 Provider、集群作业、性能预测和执行报告。网站本地预览：

```bash
cd website
npm ci
npm run dev
```

访问 `http://127.0.0.1:4321/docs/`。网站与 SDK 使用同一份可执行示例源码。

- [system_workflow.py](examples/system_workflow.py)：可复用任务图、状态 Actor 和执行报告。
- [custom_backend.py](examples/custom_backend.py)：从用户代码注册量子 Provider，支持本地和 Ray。
- [performance_prediction.py](examples/performance_prediction.py)：独立 CPU/QPU 工作量与硬件配置对比；需兼容的原生运行环境。

公开模块还包括 `pivotq.providers`、`pivotq.jobs`、`pivotq.performance` 和 `pivotq.errors`。
完整接口见 [API 参考](../../website/src/content/docs/docs/api.md)。

## 执行边界

- 公开 SDK 提供 CPU 与 QPU 编程接口。普通 Python 函数在 CPU 上执行，QPU 接收电路。
- 本地执行器用于调试：独立任务可以并行，依赖任务的提交可能等待上游；Ray 提供分布式依赖调度。
- CPU 模拟器执行有限次数采样；默认最多 20 比特，支持已绑定幺正电路及末尾测量。
- QPU 通过统一 Provider 接口接入，位宽等能力由适配器声明。设备只返回概率时 `counts=None`，不推算原始计数。
- 使用 Qiskit 位序：显式测量按经典位从高到低排列；没有测量指令则测量全部量子位。
- 未知设备执行状态不会自动重提或转为模拟计算；结束软件任务不代表物理设备任务已取消。

## 从内部开发版迁移

发行包和顶层命名空间统一为 `pivotq`，不再提供 `ray_quantum` 导入。
原实现收在 `pivotq._internal`，供仓库内应用桥接使用，不属于外部 SDK 的稳定接口。
新的集群作业入口为 `python -m pivotq.jobs.driver`。部署时先结束旧作业，再为 Driver
和所有 Worker 安装相同版本；旧进程、Actor、ObjectRef 和 pickle 对象不跨版本迁移。
现有环境中旧 `ray-quantum` 发行包应卸载；仓库统一环境通过 `uv sync` 更新。

## 开发验证

在本目录安装 `python -m pip install -e ".[test,qpu]"` 后运行 `python -m pytest -q`。
SDK 测试覆盖用户函数、任务依赖、量子模拟、离线 QPU 契约、独立 wheel 及本机 Ray。
真机与远程集群验证独立进行。历史 `qasm_client` 测试对应已替换的 SDK，既有失败需与新增
回归分别记录，不作为 HTTP 设备已经通过验证的证据。
