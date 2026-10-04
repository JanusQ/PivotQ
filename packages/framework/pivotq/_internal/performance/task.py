import json
import shutil
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from .common import (file_sha256, node_timeline, read_csv, read_json,
                     require, write_json)


def snapshot_fields(text):
    # Read the simulator's normalized snapshot, not arbitrary user YAML.
    fields, lines, parents = {}, {}, []
    for index, line in enumerate(text.splitlines()):
        content = line.strip()
        if not content or content.startswith(("#", "-")) or ":" not in content:
            continue
        indent = len(line) - len(line.lstrip())
        while parents and parents[-1][0] >= indent:
            parents.pop()
        key, value = (part.strip() for part in content.split(":", 1))
        path = ".".join([parent[1] for parent in parents] + [key])
        if not value:
            parents.append((indent, key))
        elif "links" not in [parent[1] for parent in parents]:
            fields[path] = (json.loads(value) if value[:1] in '"-0123456789[{'
                            or value in ("true", "false", "null") else value)
            lines[path] = index
    return fields, lines


def copy_references(snapshot, inputs):
    fields, locations = snapshot_fields(snapshot)
    require(fields.get("workload.type") == "custom_trace",
            "predict_task requires workload.type=custom_trace and a task graph JSON")
    lines, sources = snapshot.splitlines(), {}
    references = (("workload.trace_file", "task_graph.json"),
                  ("reference.quality_profile_csv", "quality_profile.csv"))
    for field, name in references:
        if field not in fields:
            continue
        source = Path(fields[field])
        require(source.is_file(), f"Missing {field}: {source}")
        shutil.copyfile(source, inputs / name)
        sources[field] = {"path": str(source), "sha256": file_sha256(inputs / name)}
        line = lines[locations[field]]
        lines[locations[field]] = line.split(":", 1)[0] + ": " + json.dumps(name)
    require("workload.trace_file" in sources, "The scenario must reference a task graph JSON")
    # Snapshots write unset link limits as zero; the importer requires them omitted.
    unset_limits = {"        max_active_flows: 0", "        queue_capacity_bytes: 0"}
    portable = "\n".join(line for line in lines if line not in unset_limits) + "\n"
    (inputs / "scenario.yaml").write_text(portable, encoding="utf-8")
    return fields, sources


def validate_workload(nodes, fields):
    for node in nodes:
        if node["estimated_duration_us"]:
            continue
        attrs, kind = node.get("attrs", {}), node["node_type"]
        label = f"Node {node['node_id']} ({kind})"
        if kind in ("CPU_COMPUTE", "HPC_COMPUTE", "GPU_COMPUTE", "AI_TRAINING_STEP",
                    "AI_INFERENCE_STEP", "OPTIMIZER_STEP"):
            key = "tensor_ops" if node["device_type"] == "GPU" else "ops"
            size = node["input_bytes"] + node["output_bytes"]
            require(attrs.get(key, 0) > 0 or size > 0,
                    f"{label} needs positive {key}, memory bytes, or estimated_duration_us")
            if node["device_type"] == "GPU" and size > 0:
                require(fields.get("system.hardware.gpu_cluster.hbm_bandwidth_tbps_per_gpu", 0) > 0,
                        f"{label} needs GPU hbm_bandwidth_tbps_per_gpu to account for memory bytes")
        if kind == "QPU_EXEC":
            require(attrs.get("circuit_count", 0) > 0 and "shots_per_circuit" in attrs,
                    f"{label} needs circuit_count and shots_per_circuit, or estimated_duration_us")
            require(node.get("resource_constraints", {}).get("qubits", 0) > 0,
                    f"{label} needs resource_constraints.qubits")
            if not fields.get("system.hardware.qpu.shot_rate", 0):
                require(attrs.get("transpiled_circuit_depth", attrs.get("circuit_depth", 0)) > 0,
                        f"{label} needs circuit depth when QPU shot_rate is not configured")


def model_sources(nodes, fields):
    parameters = {
        "CPU": ("cpu_cluster", ("peak_flops_tflops_per_node", "memory_bandwidth_gbps_per_node")),
        "HPC": ("cpu_cluster", ("peak_flops_tflops_per_node", "memory_bandwidth_gbps_per_node")),
        "GPU": ("gpu_cluster", ("compute_tflops_per_gpu", "hbm_bandwidth_tbps_per_gpu",
                                "kernel_launch_overhead_us")),
        "QPU": ("qpu", ("shot_rate", "submit_latency_us", "measurement_latency_us")),
        "DPU": ("dpu", ("rdma_bandwidth_gbps", "reduction_throughput_gbps", "compression_throughput_gbps")),
        "STORAGE": ("storage", ("read_bandwidth_gbps", "write_bandwidth_gbps", "metadata_latency_us")),
    }
    explicit = [n["node_id"] for n in nodes if n["estimated_duration_us"]]
    devices = {n["device_type"] for n in nodes if not n["estimated_duration_us"]}
    defaults = []
    for device in sorted(devices & parameters.keys()):
        section, names = parameters[device]
        for name in names:
            field = f"system.hardware.{section}.{name}"
            if name == "compute_tflops_per_gpu" and fields.get("system.hardware.gpu_cluster.fp16_tflops_per_gpu", 0):
                continue
            configured = field in fields if name == "kernel_launch_overhead_us" else fields.get(field, 0) > 0
            if not configured:
                defaults.append(field)
    return {"explicit_duration_nodes": explicit,
            "model_duration_nodes": [n["node_id"] for n in nodes if not n["estimated_duration_us"]],
            "hardware_fields": {k: v for k, v in fields.items() if k.startswith("system.hardware.")},
            "fields_using_builtin_defaults": defaults,
            "scope": "Configured values and explicit durations are caller supplied; intrinsic model overheads remain in effect. GPU memory modeling is disabled without HBM bandwidth. QPU shot_rate includes circuit execution."}


def prepare_task(library, scenario, folder):
    folder.mkdir(parents=True, exist_ok=True)
    inputs = folder / "inputs"
    library.export_trace(scenario, inputs, folder / "trace.log")
    snapshot = (inputs / "scenario_snapshot.yaml").read_text(encoding="utf-8")
    fields, sources = copy_references(snapshot, inputs)
    shutil.copyfile(scenario, inputs / "source_scenario.yaml")
    sources["scenario"] = {"path": str(scenario), "sha256": file_sha256(inputs / "source_scenario.yaml")}
    # Revalidate the copies so the run uses exactly the inputs checked here.
    library.validate(inputs / "scenario.yaml", folder / "validate.log")
    graph = read_json(inputs / "task_graph.json")
    validate_workload(graph["nodes"], fields)
    return {"folder": folder, "nodes": graph["nodes"], "fields": fields, "sources": sources}


def job_timings(nodes, starts, ends):
    by_id = {n["node_id"]: n for n in nodes}
    jobs = defaultdict(list)
    for node in nodes:
        jobs[node["job_id"]].append(node)
    results = []
    for job, members in sorted(jobs.items()):
        entries = [n for n in members if not any(by_id[dep]["job_id"] == job for dep in n["dependencies"])]
        arrival = Decimal(min(n.get("attrs", {}).get("arrival_time_us", 0) for n in entries)) / 1000000
        first_start = min(starts[n["node_id"]] for n in members)
        finish = max(ends[n["node_id"]] for n in members)
        require(finish >= first_start >= arrival, f"Invalid job timeline for {job}")
        results.append({"job_id": job, "arrival_seconds": float(arrival), "start_seconds": float(first_start),
                        "finish_seconds": float(finish), "latency_seconds": float(finish - arrival)})
    return results


def communication_metrics(output):
    flows = {}
    for row in read_csv(output / "communication.csv"):
        flow = flows.setdefault(row["flow_id"], {"src": row["src"], "dst": row["dst"], "path": row["path"],
                                                "bytes": int(row["message_bytes"]), "times": []})
        flow["times"].append(Decimal(row["time_s"]))
    if not flows:
        return None
    paths = {}
    for flow in flows.values():
        key = (flow["src"], flow["dst"], flow["path"])
        path = paths.setdefault(key, {"src": key[0], "dst": key[1], "path": key[2],
                                      "transfer_bytes": 0, "flow_seconds": Decimal(0), "flow_count": 0})
        path["transfer_bytes"] += flow["bytes"]
        path["flow_seconds"] += max(flow["times"]) - min(flow["times"])
        path["flow_count"] += 1
    for path in paths.values():
        path["flow_seconds"] = float(path["flow_seconds"])
        path["effective_bandwidth_gbps"] = (path["transfer_bytes"] * 8 / path["flow_seconds"] / 1e9
                                            if path["flow_seconds"] > 0 else None)
    return {"transfer_bytes": sum(p["transfer_bytes"] for p in paths.values()), "paths": list(paths.values()),
            "scope": "Bytes counted once per flow, including collective flows. Path bandwidth uses cumulative flow lifetimes; it is not physical link capacity."}


def summarize_task(prepared, library):
    output, nodes = prepared["folder"] / "output", prepared["nodes"]
    summary = read_csv(output / "summary.csv")[0]
    require(float(summary["task_completion_ratio"]) == 1,
            f"Simulation did not complete every task; inspect {prepared['folder'] / 'run.log'} and simulation_time_s")
    starts, ends = node_timeline(output, nodes)
    jobs = job_timings(nodes, starts, ends)
    duration_by_device, phases = defaultdict(float), defaultdict(float)
    for node in nodes:
        duration = float(ends[node["node_id"]] - starts[node["node_id"]])
        duration_by_device[node["device_type"]] += duration
        phases[node.get("attrs", {}).get("phase", node["node_type"])] += duration
    finish = float(max(ends.values()))
    return {"schema_version": "task-prediction-v1", "backend": "custom", "job_count": len(jobs), "jobs": jobs,
            "latency_seconds": sum(j["latency_seconds"] for j in jobs) / len(jobs),
            "latency_scope": "Mean job arrival-to-completion time; see jobs for individual latencies",
            "simulated_time_seconds": finish, "throughput_jobs_per_hour": 3600 * len(jobs) / finish if finish else None,
            "phase_seconds": dict(phases), "device_node_seconds": dict(duration_by_device),
            "main_bottleneck": summary["main_bottleneck"], "communication": communication_metrics(output),
            "parameter_sources": model_sources(nodes, prepared["fields"]), "source_files": prepared["sources"],
            "validation_scope": "No independent real-device accuracy validation for this task",
            "scientific_quality_predicted": False, "simulator_sha256": file_sha256(library.path), "engine_version": library.version,
            "simulator_wall_seconds": float(summary["wall_clock_time_s"]),
            "metric_scope": "Phase/device node seconds may overlap. Throughput is for the supplied workload and resource counts. No external platform queue is added."}


def execute_task(library, prepared, backend="custom"):
    folder = prepared["folder"]
    library.run(folder / "inputs/scenario.yaml", folder / "output", folder / "run.log")
    result = summarize_task(prepared, library)
    result["backend"] = backend
    write_json(folder / "prediction.json", result)
    return result


def validate_comparison(prepared):
    for backend, case in prepared.items():
        nodes = case["nodes"]
        require(len({n["job_id"] for n in nodes}) == 1, "GPU/QPU comparison requires one job per path")
        devices = {n["device_type"] for n in nodes}
        require(backend.upper() in devices, f"The {backend} scenario needs a {backend.upper()} task")
        require(backend != "gpu" or "QPU" not in devices, "The GPU-only path must not contain QPU tasks")


def compare_tasks(results):
    return {"schema_version": "task-comparison-v1", "predictions": results,
            "quality_equivalence_verified": False,
            "comparison_scope": "Caller supplies equivalent tasks and timing boundaries."}
