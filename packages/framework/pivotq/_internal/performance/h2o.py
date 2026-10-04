import hashlib
import json
import math
from collections import defaultdict

from .common import file_sha256, finite_number, node_durations, read_csv, require, write_json


PARAMETERS_VERSION = "h2o-prediction-v1"


class TaskGraph:
    def __init__(self, job):
        self.job = job
        self.nodes = []

    def add(self, phase, kind="CPU_COMPUTE", device="CPU", seconds=0,
            input_bytes=0, output_bytes=0, attrs=None, model=False):
        finite_number(seconds, phase)
        # A literal zero requests a hardware estimate; omit genuinely empty stages.
        if seconds == 0 and not model:
            return
        node_id = len(self.nodes) + 1
        duration = 0 if model else max(1, math.floor(seconds * 1e6 + 0.5))
        node = {"node_id": node_id, "job_id": self.job, "node_type": kind,
                "device_type": device, "dependencies": [node_id - 1] if node_id > 1 else [],
                "input_bytes": input_bytes, "output_bytes": output_bytes,
                "estimated_duration_us": duration, "attrs": {"phase": phase, **(attrs or {})}}
        if device == "QPU":
            node["resource_constraints"] = {"qubits": 3}
        self.nodes.append(node)

    def transfer(self, phase, direction, size):
        source, target = ("cpu0", "gpu0") if direction == "h2d" else ("gpu0", "cpu0")
        self.add(phase, "POINT_TO_POINT_COMM", "NETWORK_LINK", input_bytes=size, output_bytes=size,
                 attrs={"src_resource": source, "dst_resource": target}, model=True)

    def json(self):
        return {"schema_version": "v1", "nodes": self.nodes}


def gpu_query(graph, config, kind, prefix):
    template = config["invocations"][kind]
    phases = template["seconds"]
    quantum, classical = template["quantum_bytes"], template["classical_bytes"]
    graph.add(prefix + ".circuit_build", seconds=phases["circuit_build"])
    graph.add(prefix + ".qasm_prepare", seconds=phases["qasm_prepare"], output_bytes=quantum["h2d"])
    graph.transfer(prefix + ".statevector_h2d", "h2d", quantum["h2d"])
    graph.add(prefix + ".statevector", "GPU_COMPUTE", "GPU", phases["statevector"], quantum["h2d"], quantum["d2h"])
    graph.transfer(prefix + ".probabilities_d2h", "d2h", quantum["d2h"])
    graph.add(prefix + ".feature_readout", seconds=phases["feature_readout"],
              input_bytes=quantum["d2h"], output_bytes=classical["h2d"])
    graph.add(prefix + ".host_service_overhead", seconds=phases["host_service_overhead"])
    graph.transfer(prefix + ".features_h2d", "h2d", classical["h2d"])
    graph.add(prefix + ".classical_actor", "AI_INFERENCE_STEP", "GPU", phases["classical_actor"],
              classical["h2d"], classical["d2h"])
    graph.transfer(prefix + ".inference_d2h", "d2h", classical["d2h"])
    graph.add(prefix + ".force_host", seconds=phases["force_host"])


def add_stage(graph, stage, prefix=""):
    graph.add(prefix + stage["name"], stage["node_type"], stage["device_type"], stage["seconds"],
              stage["input_bytes"], stage["output_bytes"])


def qpu_batches(graph, config, template, prefix, shots, batch_size):
    remaining = template["circuits"]
    index = 0
    while remaining:
        count = min(remaining, batch_size)
        label = f"{prefix}.batch{index:03d}"
        graph.add(label + ".http_submit", seconds=config["http_submit_seconds"])
        graph.add(label + ".acquisition", "QPU_EXEC", "QPU",
                  input_bytes=round(count * template["input_bytes_per_circuit"]),
                  output_bytes=round(count * template["output_bytes_per_circuit"]),
                  attrs={"circuit_count": count, "shots_per_circuit": shots}, model=True)
        graph.add(label + ".decode", seconds=count * template["decode_seconds_per_circuit"])
        remaining -= count
        index += 1


def qpu_query(graph, config, kind, prefix, shots, batch_size):
    template = config["invocations"][kind]
    for stage in template["stages"]:
        add_stage(graph, stage, prefix + ".")
        if stage["name"] == "qasm_export":
            qpu_batches(graph, config, template, prefix, shots, batch_size)


def gpu_graph(parameters, steps, preflight):
    config = parameters["gpu"]
    graph = TaskGraph("h2o_gpu")
    for phase, duration in config["fixed_seconds"].items():
        if phase != "initial_bookkeeping":
            graph.add("lifecycle." + phase, seconds=duration)
    if preflight:
        for kind in ("preflight_coarse", "preflight_fine"):
            gpu_query(graph, config, kind, kind)
    gpu_query(graph, config, "initial", "md.initial")
    graph.add("md.initial.bookkeeping", seconds=config["fixed_seconds"]["initial_bookkeeping"])
    for index in range(1, steps + 1):
        prefix = f"md.step{index:05d}"
        gpu_query(graph, config, "step", prefix)
        graph.add(prefix + ".bookkeeping", seconds=config["step_bookkeeping_seconds"])
    return graph


def qpu_graph(parameters, steps, preflight, shots, batch_size):
    config = parameters["qpu"]
    graph = TaskGraph("h2o_qpu")
    graph.add("lifecycle.launcher_outer", seconds=config["launcher_outer_seconds"])
    graph.add("lifecycle.worker_exclusive", seconds=config["worker_exclusive_seconds"])
    for stage in config["fixed_stages"]:
        if stage["name"] in ("actor_setup", "dataset_and_ood_setup", "diagnostic_input"):
            add_stage(graph, stage, "lifecycle.")
    if preflight:
        for kind in ("preflight_coarse", "preflight_fine"):
            qpu_query(graph, config, kind, kind, shots, batch_size)
        for stage in config["fixed_stages"]:
            if stage["name"] == "preflight_absolute_difference":
                add_stage(graph, stage, "preflight.")
    for stage in config["fixed_stages"]:
        if stage["name"] == "initial_state":
            add_stage(graph, stage, "md.")
    qpu_query(graph, config, "initial", "md.initial", shots, batch_size)
    graph.add("md.initial.record", seconds=config["record_seconds_per_frame"])
    for index in range(1, steps + 1):
        prefix = f"md.step{index:05d}"
        qpu_query(graph, config, "step", prefix, shots, batch_size)
        graph.add(prefix + ".bookkeeping", seconds=config["step_bookkeeping_seconds"] + config["record_seconds_per_frame"])
    for stage in config["fixed_stages"]:
        if stage["name"] in ("plot_artifacts", "actor_teardown"):
            add_stage(graph, stage, "lifecycle.")
    return graph


def scenario_text(parameters, backend, graph):
    config = parameters["qpu"]
    hardware = ("    qpu:\n      count: 1\n      qubits_per_qpu: 3\n"
                f"      shot_rate: {config['shot_rate']}\n"
                f"      submit_latency_us: {config['control_latency_us']}\n      availability: 1.0\n")
    if backend == "gpu":
        hardware = ("    cpu_cluster:\n      node_count: 1\n      cores_per_node: 24\n"
                    "    gpu_cluster:\n      node_count: 1\n      gpus_per_node: 1\n      hbm_gb_per_gpu: 40\n")
    # QPU links only satisfy topology connectivity; no QPU network flows are modeled.
    links = ("    links:\n      - src: cpu0\n        dst: gpu0\n"
             "      - src: gpu0\n        dst: cpu0\n      - src: cpu0\n        dst: qpu0\n"
             "      - src: qpu0\n        dst: cpu0\n")
    if backend == "gpu":
        links = "    links:\n"
        for direction, endpoints in (("h2d", ("cpu0", "gpu0")), ("d2h", ("gpu0", "cpu0"))):
            rate = parameters["gpu"]["link_bytes_per_second"][direction] * 8 / 1e9
            links += (f"      - src: {endpoints[0]}\n        dst: {endpoints[1]}\n"
                      f"        bandwidth_gbps: {rate:.15g}\n        latency_us: 0\n")
    budget = sum(n["estimated_duration_us"] / 1e6 for n in graph.nodes)
    budget += sum(n["attrs"].get("circuit_count", 0) * n["attrs"].get("shots_per_circuit", 0)
                  / config["shot_rate"] + config["control_latency_us"] / 1e6
                  for n in graph.nodes if n["node_type"] == "QPU_EXEC")
    return (f'schema_version: "v1"\nmetadata:\n  name: h2o_prediction_{backend}\n'
            "system:\n  hardware:\n" + hardware + "  topology:\n    type: custom_graph\n"
            "    devices:\n      cpu: 1\n      gpu: 1\n" + ("      qpu: 1\n" if backend == "qpu" else "") + links +
            "workload:\n  type: custom_trace\n  trace_file: task_graph.json\n  job_count: 1\n"
            "scheduler:\n  policy: earliest_finish_time\n"
            "simulation:\n  network_mode: analytical\n  utilization_sample_interval_us: 1000000\n"
            f"  power_sample_interval_us: 1000000\n  simulation_time_s: {max(3600, math.ceil(budget * 2 + 60))}\n"
            "output:\n  output_format: csv\n  metrics_level: detailed\n")


def validate_parameters(parameters):
    require(isinstance(parameters, dict), "H2O prediction parameters must be a JSON object")
    require(parameters.get("schema_version") == PARAMETERS_VERSION, "Unsupported H2O prediction parameters version")
    require(parameters.get("template") == "h2o_f2_aimd_3qubit", "Unsupported task template")
    defaults = parameters.get("defaults", {})
    require(isinstance(defaults, dict), "defaults must be a JSON object")
    require(type(defaults.get("shots")) is int and 1 <= defaults["shots"] <= 1000000,
            "defaults.shots must be an integer in 1..1000000")
    require(type(defaults.get("batch_size")) is int and 1 <= defaults["batch_size"] <= 324,
            "defaults.batch_size must be an integer in 1..324")
    require(type(defaults.get("preflight")) is bool, "defaults.preflight must be boolean")
    finite_number(parameters["qpu"]["shot_rate"], "shot_rate", True)
    require(type(parameters["qpu"]["shot_rate"]) is int, "shot_rate must be an integer")
    finite_number(parameters["qpu"]["control_latency_us"], "control latency", True)
    require(type(parameters["qpu"]["control_latency_us"]) is int, "control latency must be integer microseconds")
    for rate in parameters["gpu"]["link_bytes_per_second"].values():
        finite_number(rate, "link rate", True)


def request_scope(backend, steps, preflight, shots, batch_size):
    reasons = []
    if not preflight:
        reasons.append("Preflight disabled; lifecycle coefficients retain the measured cold-run context")
    if backend == "gpu" and not 10 <= steps <= 1000:
        reasons.append("GPU step count outside measured 10..1000 range")
    if backend == "qpu":
        reasons.append("QPU has same-run batch checks only; independent full-task validation unavailable")
        if steps != 1:
            reasons.append("QPU step count differs from the single measured 1-step task")
        if shots != 3000 or batch_size != 32:
            reasons.append("QPU shots/batch setting differs from measured 3000/32; linear extrapolation")
    return reasons


def write_case(parameters, backend, steps, folder, preflight=True, shots=3000, batch_size=32):
    validate_parameters(parameters)
    require(backend in ("gpu", "qpu"), "Backend must be gpu or qpu")
    require(type(steps) is int and 1 <= steps <= 1000, "steps must be an integer in 1..1000")
    require(type(shots) is int and 1 <= shots <= 1000000, "shots must be an integer in 1..1000000")
    require(type(batch_size) is int and 1 <= batch_size <= 324, "batch_size must be in 1..324")
    require(type(preflight) is bool, "preflight must be boolean")
    batches = (2 * math.ceil(324 / batch_size) if preflight else 0) + (steps + 1) * math.ceil(38 / batch_size)
    require(backend != "qpu" or 3 * batches + (steps + 3) * 12 < 100000,
            "Requested QPU graph is too large; use a larger batch size")
    graph = gpu_graph(parameters, steps, preflight) if backend == "gpu" else qpu_graph(parameters, steps, preflight, shots, batch_size)
    write_json(folder / "task_graph.json", graph.json())
    (folder / "scenario.yaml").write_text(scenario_text(parameters, backend, graph), encoding="utf-8")
    request = {"backend": backend, "steps": steps, "preflight": preflight, "logical_qubits": 3,
               "shots": shots if backend == "qpu" else None, "batch_size": batch_size if backend == "qpu" else None,
               "circuits": (648 if preflight else 0) + 38 * (steps + 1),
               "scope_notes": request_scope(backend, steps, preflight, shots, batch_size),
               "validation_scope": ("independent GPU checks at this step count" if backend == "gpu"
                                    and preflight and steps in (100, 1000) else "not independently validated at these task settings"),
               "parameters_version": parameters["schema_version"],
               "parameters_sha256": hashlib.sha256(json.dumps(parameters, sort_keys=True, allow_nan=False).encode()).hexdigest()}
    write_json(folder / "request.json", request)
    return graph, request


def execute_case(library, folder, graph, request, parameters):
    library.validate(folder / "scenario.yaml", folder / "validate.log")
    output = folder / "output"
    library.run(folder / "scenario.yaml", output, folder / "run.log")
    summary = read_csv(output / "summary.csv")[0]
    require(float(summary["task_completion_ratio"]) == 1, "Simulator did not complete every node")
    durations = node_durations(output, graph.nodes)
    result = summarize_case(parameters, request, graph.nodes, durations, summary)
    result["simulator_sha256"] = file_sha256(library.path)
    result["engine_version"] = library.version
    write_json(folder / "prediction.json", result)
    return result


def summarize_case(parameters, request, nodes, durations, summary):
    phases = defaultdict(float)
    stages = defaultdict(float)
    for node in nodes:
        phases[node["attrs"]["phase"]] += durations[node["node_id"]]
        stages[node["attrs"]["phase"].rsplit(".", 1)[-1]] += durations[node["node_id"]]
    total = sum(durations.values())
    # Summary CSV uses six significant digits; event timestamps retain microseconds.
    require(abs(total - float(summary["average_e2e_time_s"])) <= max(1e-6, total * 5e-6),
            "Serial template timeline does not match E2E")
    qpu = [n for n in nodes if n["node_type"] == "QPU_EXEC"]
    acquisition = sum(durations[n["node_id"]] for n in qpu) - len(qpu) * parameters["qpu"]["control_latency_us"] / 1e6
    transfers = [n for n in nodes if n["node_type"] == "POINT_TO_POINT_COMM"]
    transfer_time = sum(durations[n["node_id"]] for n in transfers)
    transfer_bytes = sum(n["input_bytes"] for n in transfers)
    return {**request, "latency_seconds": total,
            "md_seconds": sum(t for name, t in phases.items() if name.startswith("md.")),
            "phase_seconds": dict(phases), "stage_seconds": dict(stages), "throughput_jobs_per_hour": 3600 / total,
            "end_to_end_circuits_per_second": request["circuits"] / total,
            "end_to_end_shots_per_second": request["circuits"] * request["shots"] / total if qpu else None,
            "qpu_acquisition_seconds": acquisition if qpu else None,
            "qpu_batch_count": len(qpu), "transfer_bytes": transfer_bytes if transfers else None,
            "transfer_seconds": transfer_time if transfers else None,
            "cpu_gpu_effective_bandwidth_gbps": transfer_bytes * 8 / transfer_time / 1e9 if transfer_time else None,
            "qpu_network_bandwidth_gbps": None, "scientific_quality_predicted": False,
            "simulator_wall_seconds": float(summary["wall_clock_time_s"]),
            "main_bottleneck": summary["main_bottleneck"],
            "metric_scope": "Serial task-equivalent throughput; phase wall occupancy, not pure GPU kernel utilization"}


def comparison(results):
    return {"predictions": results, "quality_equivalence_verified": False}
