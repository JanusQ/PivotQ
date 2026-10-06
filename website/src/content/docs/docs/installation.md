---
title: 安装 PivotQ
description: 使用 Docker 镜像、源码或 wheel 安装 PivotQ，并运行 Python 程序。
---

## 支持环境

| 项目 | 当前范围 |
| --- | --- |
| Python | 3.12 |
| 已验证系统 | Linux x86-64；其他系统尚未验证 |
| 任务调度 | Ray 2.31.0；快速上手在本机启动 Ray，也可连接已有集群 |
| 教程使用的量子后端 | 默认用 CPU 模拟量子电路；通过 Provider 接口可接入 QPU |

可以使用 Docker 镜像启动工作台并运行 Python，也可以在独立 Python 环境中通过源码或 wheel 安装 SDK。运行 SDK 快速上手教程中的程序，无需下载水分子动力学模拟所用的训练数据或模型。

## 使用 Docker 安装

安装 Docker，并确保支持 Linux x86-64 容器。镜像地址为 `janusq/pivotq:latest`：

```bash
docker pull janusq/pivotq:latest

docker run --rm --init \
  --name pivotq \
  -p 127.0.0.1:8787:8787 \
  --shm-size=1g \
  -v pivotq-data:/data \
  janusq/pivotq:latest
```

启动后，在浏览器访问 `http://localhost:8787`。此终端显示工作台日志；运行记录与输出保存在 `pivotq-data` 数据卷中，容器退出后仍保留。

### 在容器中执行 Python

保持工作台容器运行，另开一个终端即可执行 Python 命令：

```bash
docker exec pivotq /app/.venv/bin/python --version
docker exec pivotq /app/.venv/bin/python -c "print('Hello, PivotQ')"
```

进入交互式 Python：

```bash
docker exec -it pivotq /app/.venv/bin/python
```

也可以进入容器终端，激活环境后使用普通的 `python` 命令：

```bash
docker exec -it pivotq bash
source /app/.venv/bin/activate
python
```

Python、依赖和计算进程都运行在容器内；宿主机只需提供 Docker。

### 运行自己的 Python 文件

在当前目录准备 `main.py`，挂载该目录并直接运行脚本：

```bash
docker run --rm --init \
  --shm-size=1g \
  --entrypoint /app/.venv/bin/python \
  -v "$PWD":/workspace \
  -w /workspace \
  janusq/pivotq:latest main.py
```

这里用 Python 替换镜像默认的工作台启动入口。`main.py` 可以导入镜像中已安装的库；写入 `/workspace` 的文件会保存在宿主机当前目录。这条命令会创建独立容器，不要求先启动工作台。

### 检查镜像中的 SDK

镜像按发布版本提供环境，源码和文档更新不会自动改变已发布镜像。运行当前 SDK 教程前，可在已启动的容器中检查：

```bash
docker exec pivotq /app/.venv/bin/python -c "import pivotq; from pivotq import QuantumCircuit, Parameter; print(pivotq.__version__)"
```

这也会检查当前镜像是否包含门户教程所需的电路与参数入口。若导入失败，可先使用下方的源码或 wheel 安装方式；后续镜像更新仍使用上面的镜像地址，重新执行 `docker pull` 并创建容器即可使用新版本。

## 从源码安装

在终端执行：

```bash
git clone https://github.com/JanusQ/PivotQ.git
cd PivotQ
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ./packages/framework
```

安装的 distribution 与 Python 导入名均为 `pivotq`。上面的命令安装本地源码；当前文档不假定 PyPI 已发布同名包。

## 构建并安装 wheel

需要将 SDK 安装到另一个 Python 环境时，可以在仓库根目录构建 wheel：

```bash
python -m pip wheel --no-deps ./packages/framework -w dist
python -m pip install ./dist/pivotq-0.1.0.dev0-py3-none-linux_x86_64.whl
```

`--no-deps` 只构建 PivotQ 的 wheel，安装时仍会解析并安装运行依赖。文件名中的版本对应当前源码，后续版本请使用实际生成的文件名。若 QPU 适配器使用 HTTP 通信，可安装可选依赖：

```bash
python -m pip install './dist/pivotq-0.1.0.dev0-py3-none-linux_x86_64.whl[qpu]'
```

wheel 提供 SDK 及性能模拟器原生文件，因此带有 Linux x86-64 平台标记；教程中的程序保留在代码仓库的 `packages/framework/examples/` 下。

## 验证安装

源码或 wheel 安装完成后，在对应 Python 环境中运行：

```bash
python -c "import pivotq; print(pivotq.__version__)"
python packages/framework/examples/hybrid_program.py --executor ray --address local
python packages/framework/examples/system_workflow.py
python packages/framework/examples/custom_backend.py
```

混合程序教程中的脚本会启动本机 Ray，通过 Worker 执行经典任务与量子后端调用，输出量子后端、迭代次数和参数更新记录。`is_simulated` 为 `true` 表示量子电路由 CPU 模拟；任务依赖仍由 Ray 调度。下一步阅读[快速上手](../quickstart/)，了解代码如何连接这些计算步骤。

后两份教程中的程序分别验证组件/工作流/执行报告和第三方 Provider；默认都在 CPU 上运行。Ray Jobs 需要独立部署的服务。性能预测原生引擎的兼容环境、输入预览和运行方式见[性能预测](../performance/#原生运行环境)。

## QPU 适配器的可选依赖

QPU 通过 Provider 接口接入，所需设备 SDK 或通信依赖由适配器决定。使用 HTTP 通信的适配器可在仓库根目录执行：

```bash
python -m pip install -e './packages/framework[qpu]'
```

该 extra 提供 HTTP 客户端依赖。设备连接配置由 Provider 实现定义；安装依赖不会连接 QPU，也不会在 QPU 上执行任务。[量子后端](../quantum-backends/)说明统一提交接口，[扩展量子后端](../providers/)说明适配器的实现与注册。

## 使用整个仓库环境

已经使用仓库统一环境的开发者，可以在仓库根目录执行：

```bash
uv sync --locked
uv run --locked python packages/framework/examples/hybrid_program.py --executor ray --address local
```

统一环境还包含工作台和水分子动力学模拟应用的依赖。无论使用独立 SDK 环境还是仓库统一环境，均通过 `import pivotq` 导入；选择一种方式管理当前环境即可。

## 更新与排错

更新源码后重新执行对应安装命令。若提示找不到 `pivotq`，先确认终端已激活同一个 Python 环境，并检查 `python -m pip show pivotq`。更多情况见[常见问题](../troubleshooting/)。
