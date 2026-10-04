# QPerfSim 交付物使用与模块对接说明

当前 Python 预测实现已并入唯一发行包 `pivotq`，公开入口为 `pivotq.performance`。请先按仓库或网站安装说明安装 `pivotq`；本目录的两个 Python 命令和 `_prediction` 导入转发到包内实现，参数和结果文件约定继续保留。Dashboard 与 SDK 共享隔离预测 Worker。此处 `lib/`、头文件及参考参数保留交付原件，包内副本的动态库字节和摘要与原件一致。

随包原生引擎支持 Linux x86-64：Ubuntu 24.04 可直接加载；Ubuntu 22.04 可通过 `FUSION_QPERFSIM_RUNTIME` 指定已有的兼容运行库目录。程序不会下载或替换系统运行库。下文的平台文件名表描述原生接口的命名约定；当前仓库仅交付 Linux 动态库。

QPerfSim 根据设备配置和任务信息估算执行时延、吞吐及通信开销。合作方负责生成任务图，平台读取预测结果并负责展示和执行路径选择。预测按无外部平台排队、资源可用处理，任务图内部的依赖和配置的资源容量仍参与模拟。

本文随QperfSim包放置为 `README.md`。下文所有命令均在QperfSim包根目录执行，输出目录均使用新目录。

| 对接方 | 提供的输入 | 调用入口 | 读取的结果 |
|---|---|---|---|
| 水分子任务模块 | 步数、执行路径及可选的 shots、批大小 | `scripts/predict_h2o.py` | 各路径的 `prediction.json` 和汇总 `comparison.json` |
| 通用任务模块 | 设备配置 YAML 和已经规约的任务图 JSON | `scripts/predict_task.py` | `prediction.json`；双路径调用另有 `comparison.json` |
| C/C++ 模块 | 与脚本相同格式的场景 YAML 和任务图 | `include/fusion_api.h` 声明的动态库接口 | 模拟器 CSV、配置快照和时间查询接口 |

**QperfSim包保留以下目录关系。** 两个 Python 入口共同使用 `_prediction` 内的模块，由 `native.py` 通过标准库 `ctypes` 直接加载动态库。

```text
QPerfSim/
├── README.md
├── lib/
│   └── libfusion.so
├── include/
│   └── fusion_api.h
├── scripts/
│   ├── predict_h2o.py
│   ├── predict_task.py
│   └── _prediction/
│       ├── __init__.py
│       ├── native.py
│       ├── common.py
│       ├── h2o.py
│       └── task.py
└── examples/
    ├── h2o/
    │   └── prediction_parameters.json
    └── generic_quantum/
        ├── gpu/
        │   ├── scenario.yaml
        │   └── task_graph.json
        └── qpu/
            ├── scenario.yaml
            └── task_graph.json
```

`scripts/` 需要完整保留。`examples/h2o/prediction_parameters.json` 保存已校准的水分子参数；`examples/generic_quantum/` 提供通用任务的输入样例，其中的设备数值为演示配置。头文件供 C/C++ 编译时使用，Python 运行时直接加载库文件。

当前脚本随 `pivotq` 使用 Python 3.12，预测实现本身仅依赖标准库。系统的解释器命令为 `python` 时，将示例中的 `python3` 替换为 `python`。动态库必须与运行进程的操作系统和处理器架构匹配，并具备其所需的系统运行库。执行性能预测本身无需连接真实 GPU 或 QPU。

| 操作系统 | `lib/` 中的库文件 |
|---|---|
| Linux | `libfusion.so` |
| macOS | `libfusion.dylib` |
| Windows | `QPerfSim.dll` |

脚本默认使用安装在 `pivotq` 内的原生库。指定其他交付文件时，用 `--library` 指定文件；该选项的相对路径按启动命令时的工作目录解析。

**水分子预测由 `predict_h2o.py` 自动构造任务图。** 例如，估算 100 步实验在两条路径上的耗时：

```bash
python3 scripts/predict_h2o.py --steps 100 --backend both --out results/h2o_100
```

| 参数 | 含义与默认值 |
|---|---|
| `--steps` | 必填，分子动力学步数，整数 `1..1000` |
| `--backend` | `gpu`、`qpu` 或 `both`，默认 `both` |
| `--parameters` | 默认读取包内 `examples/h2o/prediction_parameters.json` |
| `--shots` | QPU 每条电路的采样次数，整数 `1..1000000`；默认从参数文件读取，随包值为 `3000` |
| `--batch-size` | QPU 每批电路数，整数 `1..324`；默认从参数文件读取，随包值为 `32` |
| `--preflight` / `--no-preflight` | 开启或关闭实验预检查；默认从参数文件读取，随包值为开启 |
| `--library` | 动态库文件路径，省略时按上述目录查找 |
| `--out` | 必填，结果目录，需要新建或为空 |

例如，只计算 QPU 路径，并显式指定参数：

```bash
python3 scripts/predict_h2o.py --steps 1 --backend qpu --shots 3000 --batch-size 32 --preflight --out results/h2o_qpu
```

水分子参数适用于 H2O F2 AIMD 三量子位模板。GPU 参数对应一张 A100-PCIE-40GB，以及两颗 Xeon Silver 4214、共 24 个物理核的测量环境；软件环境和计时口径记录在参数文件中。GPU 测量覆盖 10、100、1000 步，QPU 测量设置为 1 步、3000 shots、批大小 32。改变任务模板或设备时，需要提供匹配的参数文件。

改变 QPU 步数、shots 或批大小时，脚本按已有参数外推，并通过 `scope_notes` 说明适用范围。QPU 整任务独立精度验证仍待完成，±30% 是误差目标。调用方应保留 `validation_scope` 和 `scope_notes`，便于判断结果的适用条件。

**通用任务由 `predict_task.py` 读取调用方准备的输入。** 单路径预测与 GPU/QPU 对比的命令分别如下。

```bash
python3 scripts/predict_task.py --scenario examples/generic_quantum/gpu/scenario.yaml --out results/task_gpu
```

```bash
python3 scripts/predict_task.py --gpu-scenario examples/generic_quantum/gpu/scenario.yaml --qpu-scenario examples/generic_quantum/qpu/scenario.yaml --out results/task_compare
```

`--scenario` 用于单路径。双路径比较同时提供 `--gpu-scenario` 和 `--qpu-scenario`，每条路径各包含一个作业。GPU 路径需包含 GPU 任务并保持 QPU 任务为空；QPU 路径需包含 QPU 任务。两条路径的计算目标、前后处理范围和结果要求由调用方对齐。

通用入口同样接受 `--library` 和 `--out`。它读取已生成的任务图，量子电路解析和任务图生成由任务模块完成。

| 输入文件或字段 | 调用方填写的内容 |
|---|---|
| `scenario.yaml` 的 `system.hardware` | CPU、GPU、QPU 数量及有效计算速度、访存带宽、shot 吞吐等设备参数 |
| `scenario.yaml` 的 `system.topology` | 设备间的连接、链路带宽和时延 |
| `scenario.yaml` 的 `workload` | `type` 填 `custom_trace`，`trace_file` 指向任务图，`job_count` 等于不同 `job_id` 的数量 |
| `task_graph.json` | 顶层 `schema_version` 填 `v1`，`nodes` 数组描述任务步骤及其依赖 |

`workload.trace_file` 的相对路径按其所在的 YAML 文件目录解析。可以直接复制随包的 GPU/QPU 示例，修改设备配置、节点和工作量。每个节点都需要下列字段。

| 节点字段 | 填写约定 |
|---|---|
| `node_id` | 全图唯一的正整数编号 |
| `job_id` | 作业标识，同一作业内保持一致 |
| `node_type`、`device_type` | 任务与设备类型，例如 `GPU_COMPUTE` 配 `GPU`、`QPU_EXEC` 配 `QPU` |
| `dependencies` | 前置节点编号数组，入口节点填 `[]`，依赖构成无环图 |
| `input_bytes`、`output_bytes` | 输入、输出字节数，非负整数 |
| `estimated_duration_us` | 普通计算节点填正整数时直接采用该时长；填 `0` 时根据设备和工作量估算 |

需要按模型估算时，CPU/HPC 工作量放在 `attrs.ops`，GPU 工作量放在 `attrs.tensor_ops`。使用 GPU 输入输出字节数计入访存时，同时填写 `system.hardware.gpu_cluster.hbm_bandwidth_tbps_per_gpu`。QPU 填写 `attrs.circuit_count`、`attrs.shots_per_circuit` 和 `resource_constraints.qubits`；未配置 QPU `shot_rate` 时，还需填写 `transpiled_circuit_depth` 或 `circuit_depth`。

非零的 `estimated_duration_us` 优先于设备公式。跨设备传输通过独立通信节点描述，参考示例中的 `POINT_TO_POINT_COMM`，填写 `src_resource`、`dst_resource` 和传输字节数，并将其纳入任务依赖。通信节点的 `estimated_duration_us` 填 `0`，其耗时由链路计算。

通用输入中的省略项会按模拟器内置默认值处理，结果中的 `parameter_sources` 列出已配置硬件、显式时长节点、模型估算节点及部分默认字段。用于实际平台比较时，应填写与目标设备匹配的性能参数。

**平台通过结果文件读取预测值。** 每次请求使用独立输出目录，等待脚本退出码为 `0` 后再读取结果；失败时保留标准错误和已生成的日志用于排查。

| 调用方式 | 主要结果位置 |
|---|---|
| 水分子入口，任意 backend | `<out>/<backend>/prediction.json`；根目录始终生成 `comparison.json` |
| 通用入口，单路径 | `<out>/prediction.json` |
| 通用入口，双路径 | `<out>/gpu/prediction.json`、`<out>/qpu/prediction.json`、`<out>/comparison.json` |

水分子输出同时保留 `request.json`、生成的 `scenario.yaml` 和 `task_graph.json`。通用输出在 `inputs/` 中保存可复跑的 `scenario.yaml`、任务图及相关输入副本。每条路径的 `output/` 保存 `summary.csv`、`runtime_events.csv` 等底层结果，路径根目录保存校验、运行日志；通用入口另有 `trace.log`。

| 结果字段 | 含义与单位 |
|---|---|
| `latency_seconds` | 任务预计时延，秒；通用入口包含多个作业时为平均作业时延，逐作业结果见 `jobs` |
| `throughput_jobs_per_hour` | 给定任务及资源配置下的作业吞吐，作业/小时 |
| `phase_seconds` | 各阶段节点耗时，秒；并行阶段可以重叠，总和可能大于任务时延 |
| `main_bottleneck` | 模型识别的主要瓶颈 |
| `simulator_wall_seconds` | 模拟器自身计算这次预测的实际运行时间，秒 |
| `simulator_sha256` | 本次调用的动态库文件摘要，用于核对交付版本 |
| 水分子的 `parameters_version`、`parameters_sha256` | 参数格式版本和解析后参数内容的摘要 |
| 水分子的 `end_to_end_circuits_per_second`、`end_to_end_shots_per_second` | 端到端电路吞吐和 QPU shot 吞吐 |
| 水分子的 `cpu_gpu_effective_bandwidth_gbps` | CPU/GPU 数据量除以累计传输时间得到的有效带宽，Gbps |
| 通用结果的 `communication` | 通信总字节数及各路径的有效带宽；路径带宽按累计流存续时间计算，Gbps |

界面展示预计任务耗时使用 `latency_seconds`。吞吐和有效带宽对应本次任务的计算口径；硬件峰值参数在输入配置中维护。结果里的 `null` 表示该指标不适用或缺少依据，例如水分子的 `qpu_network_bandwidth_gbps`，界面应显示“暂无估计”。

`comparison.json` 的 `predictions` 数组汇总各路径的性能结果，每项通过 `backend` 标识路径。平台根据这些指标完成展示和执行路径选择。汇总文件保留 `quality_equivalence_verified=false`，计算结果质量等价性由任务模块确认。水分子单路径调用时，数组仅包含所选路径的结果。

**C/C++ 模块使用公开头文件链接动态库。** `FusionSim*` 是不透明实例句柄，调用方通过下列函数完成操作。

| 函数 | 调用约定 |
|---|---|
| `fusion_version()` | 返回库版本字符串，调用方保留只读引用 |
| `fusion_validate(path)` | 校验场景与任务图，成功返回 `1`，失败返回 `0` |
| `fusion_validate_error()`、`fusion_last_error()` | 返回分配的错误字符串，读取后调用 `fusion_free_string()` 释放 |
| `fusion_create(path)` | 根据场景创建实例，失败返回空指针 |
| `fusion_export_trace(sim, out)` | 导出任务图 CSV 和配置快照，输出目录需新建或为空；成功返回 `0` |
| `fusion_run_simulation(sim, out)` | 执行模拟并写出 CSV，成功返回 `0`，失败返回非零值 |
| `fusion_simulated_time_us(sim)` | 返回模拟时间轴推进的时长，微秒；逐作业时延以结果文件为准 |
| `fusion_wall_clock_s(sim)` | 返回最近一次模拟的实际计算耗时，秒 |
| `fusion_destroy(sim)` | 释放实例，允许传入空指针 |
| `fusion_free_string(text)` | 释放库返回的错误字符串 |

错误信息按调用线程保存，应在失败后立即读取。每个并行请求使用独立实例和输出目录，同一实例串行调用。版本字符串由库管理，错误字符串由调用方通过库接口释放。

`fusion_run_simulation` 会覆盖目标目录中的同名结果文件，调用方应为每次请求创建独立目录。返回 `0` 表示本次模拟及结果写出成功，还需检查 `summary.csv` 的 `task_completion_ratio` 为 `1`，确认所有节点完成。直接调用库时，JSON 汇总由接入方处理；使用两个预测脚本可直接获得上述 JSON。

下面的完整示例保存为QperfSim包根目录下的 `client.cpp`。

```cpp
#include "fusion_api.h"

#include <cstdio>
#include <filesystem>
#include <system_error>

int report_error(const char* operation)
{
    char* message = fusion_last_error();
    std::fprintf(stderr, "%s failed: %s\n", operation,
                 message && message[0] ? message : "no error details");
    fusion_free_string(message);
    return 1;
}

int main(int argc, char** argv)
{
    if (argc != 3) {
        std::fprintf(stderr, "usage: client <scenario.yaml> <new-output-directory>\n");
        return 2;
    }
    std::error_code error;
    const bool exists = std::filesystem::exists(argv[2], error);
    if (error || exists) {
        std::fprintf(stderr, "Cannot use output directory %s; choose a new writable path\n", argv[2]);
        return 2;
    }
    if (fusion_validate(argv[1]) != 1) {
        return report_error("fusion_validate");
    }
    FusionSim* sim = fusion_create(argv[1]);
    if (!sim) {
        return report_error("fusion_create");
    }
    if (fusion_run_simulation(sim, argv[2]) != 0) {
        const int status = report_error("fusion_run_simulation");
        fusion_destroy(sim);
        return status;
    }
    std::printf("simulated_time_us=%llu simulator_wall_seconds=%.6f\n",
                static_cast<unsigned long long>(fusion_simulated_time_us(sim)),
                fusion_wall_clock_s(sim));
    fusion_destroy(sim);
    return 0;
}
```

Linux 下使用以下命令编译并运行。生成的 `client` 与 `lib/` 位于同一级目录。

```bash
g++ -std=c++17 client.cpp -Iinclude -Llib -lfusion -Wl,-rpath,'$ORIGIN/lib' -o client
./client examples/generic_quantum/gpu/scenario.yaml results/native_gpu
```

macOS 下使用以下命令。

```bash
clang++ -std=c++17 client.cpp -Iinclude -Llib -lfusion -Wl,-rpath,@executable_path/lib -o client
./client examples/generic_quantum/gpu/scenario.yaml results/native_gpu
```

Windows 的 C/C++ 接入需额外提供与编译器匹配的 DLL 导入库，运行时将 `QPerfSim.dll` 放在应用程序可搜索的位置。Python 入口通过 `--library` 或包内 `lib/` 直接加载 DLL。接入方编译时使用头文件默认的动态链接声明。

**排查时先查看脚本标准错误及对应路径的日志。** 常见情况如下。

| 现象 | 处理方式 |
|---|---|
| `Shared library not found` | 检查包内 `lib/`，或通过 `--library` 指定实际文件 |
| `Cannot load shared library` | 核对操作系统、架构和系统运行库依赖 |
| 提示缺少 `fusion_export_trace` 等函数 | 同步使用同批交付的脚本、动态库和头文件 |
| `Output directory must be new or empty` | 为本次请求换一个独立输出目录 |
| 场景或任务图文件不存在 | 检查 YAML 的位置及相对它解析的 `workload.trace_file` |
| 提示缺少工作量或设备参数 | 按错误指向的节点补充工作量、shots、量子位数或带宽 |
| 模拟未完成全部任务 | 检查依赖和设备容量，并调整 `simulation.simulation_time_s`；中间输出仅用于排查 |

脚本、动态库、头文件和参数文件应使用同一批交付内容。每个平台使用匹配操作系统与处理器架构的包。
