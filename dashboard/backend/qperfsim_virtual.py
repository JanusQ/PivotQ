"""Task/scene generation for virtual QPU targets; no native calls or hardware access."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


def frozen_classical_model(path: Path, expected_sha256: str | None = None) -> dict:
    """Read dimensions from the selected immutable checkpoint, never GPU timings."""
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_sha256 and checksum != expected_sha256:
        raise ValueError("模型文件已变化，请重新编译后预测")
    import torch
    payload = torch.load(path, map_location="cpu", weights_only=True)["classical"]
    state = payload["state_dict"]
    weights = [(name, tensor) for name, tensor in state.items() if name.endswith("weight") and tensor.ndim == 2]
    if not weights:
        raise ValueError("冻结模型没有可识别的全连接层，无法估计 CPU 推理工作量")
    layers = [{"input": int(t.shape[1]), "output": int(t.shape[0])} for _, t in weights]
    return {"checkpoint_sha256": checksum, "layers": layers,
            "dtype_bytes": weights[0][1].element_size(),
            "parameter_bytes": sum(t.numel() * t.element_size() for t in state.values()),
            "source": "冻结 checkpoint classical.state_dict 中的实际全连接层尺寸",
            "scope": "前向全连接乘加按 2 次操作计，另计偏置；不含激活函数、归一化与 Python 调度开销"}


def cpu_inference_workload(model: dict, batch: int) -> dict:
    layers, size = model["layers"], model["dtype_bytes"]
    return {"ops": batch * sum(2 * layer["input"] * layer["output"] + layer["output"] for layer in layers),
            "input_bytes": model["parameter_bytes"] + batch * size * sum(layer["input"] for layer in layers),
            "output_bytes": batch * size * sum(layer["output"] for layer in layers),
            "batch_size": batch}


def build_virtual_case(plan: dict, program: dict | None, parameters: dict, *, classical_model: dict | None = None):
    from pivotq._internal.performance.h2o import TaskGraph, qpu_graph, validate_parameters

    stages = {stage["id"]: stage for stage in plan["stages"]}
    quantum = stages.get("quantum_features") or stages.get("circuit_execution")
    snapshot = quantum.get("target_snapshot") or {}
    if snapshot.get("id") != "fake-sc-36":
        raise ValueError("虚拟预测需要已保存的 Fake SC-36 参数快照")
    chip = snapshot["parameters"]
    logical_qubits = 3 if plan["task_id"] == "h2o-hybrid-aimd" else (program or {}).get("circuit", {}).get("qubits")
    if type(logical_qubits) is not int or not 1 <= logical_qubits <= chip["qubits"]:
        raise ValueError("任务电路宽度缺失或超过目标芯片容量")
    if snapshot.get("logical_qubits", logical_qubits) != logical_qubits:
        raise ValueError("电路宽度与计划中的目标快照不一致")
    if not 0 < chip["shot_rate"] or chip["submit_latency_us"] < 0:
        raise ValueError("芯片吞吐和提交时延无效")
    cpu = next((s["target_snapshot"]["parameters"] for s in stages.values()
                if (s.get("target_snapshot") or {}).get("kind") == "cpu"),
               {"peak_flops_tflops_per_node": 1, "memory_bandwidth_gbps_per_node": 100})
    notes = ["示例参数估算：Fake SC-36 未经实机标定；不预测科学精度。",
             "36 是芯片容量，任务仅使用实际逻辑比特数；6×6 拓扑仅展示，不计算布线、门深度或噪声影响。",
             "有效 shot 吞吐已包含电路执行、测量与复位；每批另加所选芯片的提交时延。",
             "预测对应目标硬件；CPU 数值计算用时由实际运行单独记录。"]
    request = {"backend": "qpu", "logical_qubits": logical_qubits, "chip_capacity_qubits": chip["qubits"],
               "target_id": snapshot["id"], "target_snapshot": snapshot,
               "parameters_version": snapshot["profile_version"], "parameters_sha256": snapshot["profile_sha256"],
               "validation_scope": "示例参数估算，未经实机标定", "scope_notes": notes}
    provenance = {"qpu": {"source": "保存的虚拟芯片参数快照", "calibrated": False},
                  "cpu": {"source": "假设的参考 CPU 参数", **cpu}}
    if plan["task_id"] == "h2o-hybrid-aimd":
        validate_parameters(parameters)
        steps = plan["normalized_inputs"]["steps"]
        if type(steps) is not int or not 1 <= steps <= 1000:
            raise ValueError("H₂O 性能预测支持 1 至 1000 步")
        shots, batch_size, preflight = 3000, 32, parameters["defaults"]["preflight"]
        graph = qpu_graph(parameters, steps, preflight, shots, batch_size)
        classical_cpu = stages["classical_predict"]["device"] == "cpu"
        if classical_cpu and classical_model is None:
            raise ValueError("CPU 经典推理预测需要冻结模型的层尺寸")
        for node in graph.nodes:
            if node["node_type"] == "AI_INFERENCE_STEP":
                phase = node["attrs"]["phase"]
                kind = "preflight_coarse" if phase.startswith("preflight_coarse.") else (
                    "preflight_fine" if phase.startswith("preflight_fine.") else "initial" if phase.startswith("md.initial.") else "step")
                if classical_cpu:
                    batch = parameters["qpu"]["invocations"][kind]["circuits"] // 2
                    workload = cpu_inference_workload(classical_model, batch)
                    node.update(device_type="CPU", node_type="CPU_COMPUTE", estimated_duration_us=0,
                                input_bytes=workload["input_bytes"], output_bytes=workload["output_bytes"])
                    node["attrs"].update(ops=workload["ops"])
                else:
                    # The A100 inference reference remains explicitly A100;
                    # the measured real-QPU controller profile is never relabelled.
                    seconds = parameters["gpu"]["invocations"][kind]["seconds"]["classical_actor"]
                    node["estimated_duration_us"] = max(1, round(seconds * 1e6))
            elif classical_cpu and node["device_type"] == "GPU":
                # Setup/teardown are retained reference host envelopes, not CPU
                # neural inference estimates. Their origin is disclosed below.
                node.update(device_type="CPU", node_type="CPU_COMPUTE")
        request.update(steps=steps, shots=shots, batch_size=batch_size, preflight=preflight,
                       circuits=(648 if preflight else 0) + 38 * (steps + 1),
                       reference_parameters_sha256=hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest())
        provenance["host_overheads"] = {"source": "examples/h2o/prediction_parameters.json: qpu 固定阶段、预检查、HTTP 提交、解码及批次结构",
                                        "scope": "沿用参考宿主阶段耗时，包括 actor setup/teardown；未对本机 CPU 或虚拟芯片重新标定"}
        provenance["classical"] = ({"source": "冻结模型层尺寸和批量的 CPU 工作量估计", "model": classical_model,
                                     "calibrated": False} if classical_cpu else
                                    {"source": "examples/h2o/prediction_parameters.json: gpu.invocations.*.seconds.classical_actor",
                                     "hardware": parameters["scope"]["gpu_hardware"], "scope": parameters["gpu"]["timing_scope"]})
        notes.append("单水固定阶段沿用原参考宿主开销；经典 GPU 沿用 A100 推理参考，经典 CPU 使用冻结层尺寸和假设 CPU 参数。")
        if classical_cpu:
            widths = [classical_model["layers"][0]["input"]] + [layer["output"] for layer in classical_model["layers"]]
            notes.append(
                f"经典 CPU 假设峰值 {cpu['peak_flops_tflops_per_node']} TFLOPS、访存带宽 "
                f"{cpu['memory_bandwidth_gbps_per_node']} Gbit/s；冻结模型层宽 {'→'.join(map(str, widths))}，"
                "每次乘加计 2 次操作，偏置计 1 次；按实际几何批量估计前向全连接工作量。"
                "该推理估计不含激活函数、归一化和 Python 调度开销，未经 CPU 实测标定。")
    elif plan["task_id"] == "quantum-circuit":
        shots = plan["normalized_inputs"]["shots"]
        if type(shots) is not int or not 1 <= shots <= 100000:
            raise ValueError("电路 shots 超出支持范围")
        circuit = program["circuit"]
        graph = TaskGraph("circuit_fake_sc_36")
        graph.add("circuit_execution.acquisition", "QPU_EXEC", "QPU", model=True,
                  input_bytes=len(json.dumps(circuit, ensure_ascii=True).encode()),
                  output_bytes=shots * math.ceil(logical_qubits / 8),
                  attrs={"circuit_count": 1, "shots_per_circuit": shots})
        request.update(shots=shots, batch_size=1, circuits=1, gate_count=circuit["gate_count"],
                       circuit_sha256=hashlib.sha256(json.dumps(circuit, sort_keys=True).encode()).hexdigest())
        notes.append("自编电路估计覆盖芯片执行与每批提交；不额外假设宿主编译、数据传输及后处理耗时。")
    else:
        raise ValueError("不支持的虚拟性能预测任务")
    for node in graph.nodes:
        if node["node_type"] == "QPU_EXEC":
            node["resource_constraints"] = {"qubits": logical_qubits}
    request["qpu_batch_count"] = sum(n["node_type"] == "QPU_EXEC" for n in graph.nodes)
    scene = virtual_scenario(graph.nodes, chip, cpu)
    return graph.json(), scene, request, {"calibrated": False, "label": "示例参数估算", "notes": notes,
                                         "parameter_sources": provenance, "ray_hardware_calibrated": False,
                                         "topology_used_for_routing": False,
                                         "geometry_batch_size": 19 if plan["task_id"] == "h2o-hybrid-aimd" else None,
                                         "measurement_bases": 2 if plan["task_id"] == "h2o-hybrid-aimd" else None}


def virtual_scenario(nodes: list[dict], chip: dict, cpu: dict) -> str:
    gpu = any(n["device_type"] == "GPU" for n in nodes)
    budget = sum(n["estimated_duration_us"] / 1e6 for n in nodes)
    budget += sum(n["attrs"].get("circuit_count", 0) * n["attrs"].get("shots_per_circuit", 0) / chip["shot_rate"]
                  + chip["submit_latency_us"] / 1e6 for n in nodes if n["node_type"] == "QPU_EXEC")
    hardware = ("    cpu_cluster:\n      node_count: 1\n      cores_per_node: 1\n"
                f"      peak_flops_tflops_per_node: {cpu['peak_flops_tflops_per_node']}\n"
                f"      memory_bandwidth_gbps_per_node: {cpu['memory_bandwidth_gbps_per_node']}\n"
                "    qpu:\n      count: 1\n"
                f"      qubits_per_qpu: {chip['qubits']}\n      shot_rate: {chip['shot_rate']}\n"
                f"      submit_latency_us: {chip['submit_latency_us']}\n"
                "      measurement_latency_us: 0\n      availability: 1.0\n")
    if gpu:
        hardware += "    gpu_cluster:\n      node_count: 1\n      gpus_per_node: 1\n      hbm_gb_per_gpu: 40\n"
    links = ""
    for device in (["qpu0", "gpu0"] if gpu else ["qpu0"]):
        links += f"      - src: cpu0\n        dst: {device}\n      - src: {device}\n        dst: cpu0\n"
    return ('schema_version: "v1"\nmetadata:\n  name: fake_sc_36_estimate\n'
            '  description: "Synthetic throughput estimate; no routing or noise model"\n'
            "system:\n  hardware:\n" + hardware + "  topology:\n    type: custom_graph\n"
            "    devices:\n      cpu: 1\n      qpu: 1\n" + ("      gpu: 1\n" if gpu else "") +
            "    links:\n" + links + "workload:\n  type: custom_trace\n  trace_file: task_graph.json\n  job_count: 1\n"
            "scheduler:\n  policy: earliest_finish_time\n"
            "simulation:\n  network_mode: analytical\n  utilization_sample_interval_us: 1000000\n"
            f"  power_sample_interval_us: 1000000\n  simulation_time_s: {max(60, math.ceil(budget * 2 + 60))}\n"
            "output:\n  output_format: csv\n  metrics_level: detailed\n")
