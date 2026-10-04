"""Independent CPU/QPU workload models and offline performance prediction.

Models describe work and hardware parameters; they do not run application
functions or connect to quantum hardware. Times in this API are seconds.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import math
from pathlib import Path
import tempfile
from typing import Any, Mapping


def _number(value, name, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError(f"{name} must be a finite {'positive' if positive else 'nonnegative'} number")
    return value


def _integer(value, name, *, positive=False):
    if type(value) is not int or (value <= 0 if positive else value < 0):
        raise ValueError(f"{name} must be a {'positive' if positive else 'nonnegative'} integer")
    return value


def _microseconds(seconds):
    return int((Decimal(str(seconds)) * 1000000).to_integral_value(rounding=ROUND_CEILING))


def _label(value, name):
    if not isinstance(value, str) or not value or len(value) > 64 or value != value.strip() or any(c in value for c in ";=\n\r"):
        raise ValueError(f"{name} must be a nonempty label of at most 64 characters without ;, = or newlines")
    return value


def _provenance(source, calibrated):
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must explain where the hardware parameters came from")
    if type(calibrated) is not bool:
        raise ValueError("calibrated must be boolean")


@dataclass(frozen=True)
class CPUProfile:
    """A homogeneous CPU pool; per-node rates use TFLOP/s and gigabits/s."""
    count: int = 1
    cores_per_node: int = 1
    peak_flops_tflops_per_node: float | None = None
    memory_bandwidth_gbps_per_node: float | None = None
    source: str = "Caller supplied; no measured calibration asserted"
    calibrated: bool = False

    def __post_init__(self):
        _integer(self.count, "CPU count", positive=True)
        _integer(self.cores_per_node, "cores_per_node", positive=True)
        for name in ("peak_flops_tflops_per_node", "memory_bandwidth_gbps_per_node"):
            if getattr(self, name) is not None:
                _number(getattr(self, name), name, positive=True)
        _provenance(self.source, self.calibrated)


@dataclass(frozen=True)
class QPUProfile:
    """Homogeneous QPUs using effective shot throughput plus per-batch submission time.

shot_rate includes acquisition, measurement and reset. Gate routing, noise,
external service queues and scientific accuracy are outside this model.
"""
    qubits: int
    shot_rate: int
    count: int = 1
    submit_latency_seconds: float = 0.0
    source: str = "Caller supplied; no measured calibration asserted"
    calibrated: bool = False

    def __post_init__(self):
        _integer(self.qubits, "QPU qubits", positive=True)
        _integer(self.count, "QPU count", positive=True)
        _integer(self.shot_rate, "shot_rate", positive=True)
        _number(self.submit_latency_seconds, "submit_latency_seconds")
        _provenance(self.source, self.calibrated)


@dataclass(frozen=True)
class LinkProfile:
    """A directed link; bandwidth is gigabits/second and latency is seconds."""
    source: str
    target: str
    bandwidth_gbps: float
    latency_seconds: float = 0.0

    def __post_init__(self):
        _label(self.source, "link source")
        _label(self.target, "link target")
        if self.source == self.target:
            raise ValueError("link endpoints must differ")
        _number(self.bandwidth_gbps, "bandwidth_gbps", positive=True)
        _number(self.latency_seconds, "latency_seconds")


@dataclass(frozen=True)
class Hardware:
    cpu: CPUProfile = field(default_factory=CPUProfile)
    qpu: QPUProfile | None = None
    links: tuple[LinkProfile, ...] = ()

    def __post_init__(self):
        if not isinstance(self.cpu, CPUProfile) or (self.qpu is not None and not isinstance(self.qpu, QPUProfile)):
            raise TypeError("hardware requires CPUProfile and optional QPUProfile")
        object.__setattr__(self, "links", tuple(self.links))
        if any(not isinstance(link, LinkProfile) for link in self.links):
            raise TypeError("links must contain LinkProfile objects")
        devices = self.device_ids
        pairs = set()
        for link in self.links:
            if link.source not in devices or link.target not in devices:
                raise ValueError("link endpoint is not a CPU/QPU instance in this hardware")
            if (link.source, link.target) in pairs:
                raise ValueError("duplicate directed link")
            pairs.add((link.source, link.target))

    @property
    def device_ids(self):
        return tuple(f"cpu{i}" for i in range(self.cpu.count)) + tuple(f"qpu{i}" for i in range(self.qpu.count if self.qpu else 0))

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        return cls(cpu=CPUProfile(**value["cpu"]), qpu=QPUProfile(**value["qpu"]) if value.get("qpu") else None,
                   links=tuple(LinkProfile(**link) for link in value.get("links", ())))


class Workload:
    """A user-authored dependency graph, independent of executable Python code.

Each builder returns the node name to use in depends_on. Forward references
are permitted; preview/predict validates the completed graph.
"""
    def __init__(self, name="workload"):
        self.name = _label(name, "workload name")
        self._nodes = []

    @property
    def nodes(self):
        return deepcopy(self._nodes)

    def _add(self, name, kind, depends_on, job_id, target, fields):
        _label(name, "node name")
        _label(job_id, "job_id")
        if any(node["name"] == name for node in self._nodes):
            raise ValueError(f"Duplicate node name: {name}")
        if isinstance(depends_on, str):
            raise TypeError("depends_on must be a sequence of node names")
        dependencies = list(depends_on)
        for dependency in dependencies:
            _label(dependency, "dependency")
        if len(dependencies) != len(set(dependencies)) or name in dependencies:
            raise ValueError("dependencies cannot contain duplicates or the node itself")
        if target is not None:
            _label(target, "target")
        self._nodes.append({"name": name, "kind": kind, "depends_on": dependencies,
                            "job_id": job_id, "target": target, **fields})
        return name

    def cpu(self, name, *, duration_seconds=None, ops=None, input_bytes=0, output_bytes=0,
            depends_on=(), target=None, job_id="job0"):
        """Use an explicit duration or an operations/memory model.

Input/output sizes do not create communication tasks. With an explicit
duration they are payload metadata; use transfer() to model transport.
"""
        if duration_seconds is not None and ops is not None:
            raise ValueError("Specify duration_seconds or ops, not both")
        if duration_seconds is not None:
            _number(duration_seconds, "duration_seconds", positive=True)
        if ops is not None:
            _number(ops, "ops", positive=True)
        _integer(input_bytes, "input_bytes")
        _integer(output_bytes, "output_bytes")
        if duration_seconds is None and not (ops or input_bytes or output_bytes):
            raise ValueError("CPU task needs a positive duration or operations/memory workload")
        return self._add(name, "cpu", depends_on, job_id, target,
                         dict(duration_seconds=duration_seconds, ops=ops, input_bytes=input_bytes, output_bytes=output_bytes))

    def qpu(self, name, *, qubits, shots, circuit_count=1, input_bytes=0, output_bytes=0,
            depends_on=(), target=None, job_id="job0"):
        for value, label in ((qubits, "qubits"), (shots, "shots"), (circuit_count, "circuit_count")):
            _integer(value, label, positive=True)
        _integer(input_bytes, "input_bytes")
        _integer(output_bytes, "output_bytes")
        return self._add(name, "qpu", depends_on, job_id, target,
                         dict(qubits=qubits, shots=shots, circuit_count=circuit_count, input_bytes=input_bytes, output_bytes=output_bytes))

    def transfer(self, name, *, source, target, bytes, depends_on=(), job_id="job0"):
        _label(source, "source")
        _label(target, "target")
        if source == target:
            raise ValueError("transfer endpoints must differ")
        _integer(bytes, "bytes", positive=True)
        return self._add(name, "transfer", depends_on, job_id, None, dict(source=source, destination=target, bytes=bytes))

    def to_dict(self):
        return {"schema_version": "pivotq-workload-v1", "name": self.name, "nodes": self.nodes}

    @classmethod
    def from_dict(cls, value):
        if value.get("schema_version") != "pivotq-workload-v1":
            raise ValueError("Unsupported workload schema_version")
        workload = cls(value["name"])
        for raw in value["nodes"]:
            node = dict(raw)
            kind, name = node.pop("kind"), node.pop("name")
            if kind not in ("cpu", "qpu", "transfer"):
                raise ValueError(f"Unsupported task kind: {kind}")
            if kind == "transfer":
                node.pop("target", None)
                node["target"] = node.pop("destination")
            getattr(workload, kind)(name, **node)
        return workload


def _yaml_lines(value, indent=0):
    """Emit the fixed native scenario schema; scalar strings remain quoted."""
    prefix = " " * indent
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                yield f"{prefix}{key}:"
                yield from _yaml_lines(item, indent + 2)
            else:
                yield f"{prefix}{key}: {json.dumps(item, ensure_ascii=False, allow_nan=False)}"
    elif isinstance(value, list):
        for item in value:
            lines = list(_yaml_lines(item, indent + 2))
            yield prefix + "- " + lines[0].lstrip()
            yield from lines[1:]


def _compile(workload, hardware):
    if not isinstance(workload, Workload) or not isinstance(hardware, Hardware):
        raise TypeError("prediction requires a Workload and Hardware")
    nodes = workload.nodes
    if not nodes or len(nodes) > 100000:
        raise ValueError("workload must have between 1 and 100000 nodes")
    indices = {node["name"]: index + 1 for index, node in enumerate(nodes)}
    pending = {node["name"]: set(node["depends_on"]) for node in nodes}
    unknown = set().union(*pending.values()) - indices.keys()
    if unknown:
        raise ValueError(f"Unknown dependencies: {sorted(unknown)}")
    # Kahn validation is iterative and handles long serial scientific workloads.
    followers = {name: [] for name in indices}
    for name, dependencies in pending.items():
        for dependency in dependencies:
            followers[dependency].append(name)
    ready = [name for name, dependencies in pending.items() if not dependencies]
    seen = 0
    while ready:
        name = ready.pop()
        seen += 1
        for follower in followers[name]:
            pending[follower].remove(name)
            if not pending[follower]:
                ready.append(follower)
    if seen != len(nodes):
        raise ValueError("workload dependencies contain a cycle")
    devices = hardware.device_ids
    native_nodes, budget = [], 0.0
    transfers = [node for node in nodes if node["kind"] == "transfer"]
    adjacency = {device: set() for device in devices}
    for link in hardware.links:
        adjacency[link.source].add(link.target)
    for transfer in transfers:
        source, target = transfer["source"], transfer["destination"]
        if source not in devices or target not in devices:
            raise ValueError("transfer endpoint is absent from hardware")
        reachable, frontier = {source}, [source]
        while frontier:
            for other in adjacency[frontier.pop()] - reachable:
                reachable.add(other)
                frontier.append(other)
        if target not in reachable:
            raise ValueError(f"No configured directed communication route: {source} -> {target}")
    for node in nodes:
        kind, target = node["kind"], node["target"]
        if target is not None and (target not in devices or not target.startswith(kind)):
            raise ValueError(f"Invalid {kind} target: {target}")
        attrs = {"phase": node["name"]}
        if target:
            attrs["resource_id"] = target
        result = dict(node_id=indices[node["name"]], job_id=node["job_id"],
                      dependencies=[indices[name] for name in node["depends_on"]],
                      input_bytes=node.get("input_bytes", 0), output_bytes=node.get("output_bytes", 0),
                      estimated_duration_us=0, attrs=attrs)
        if kind == "cpu":
            result.update(node_type="CPU_COMPUTE", device_type="CPU")
            duration = node["duration_seconds"]
            if duration is not None:
                result["estimated_duration_us"] = _microseconds(duration)
                budget += duration
            else:
                if node["ops"]:
                    rate = hardware.cpu.peak_flops_tflops_per_node
                    if rate is None:
                        raise ValueError("CPU operations require peak_flops_tflops_per_node")
                    attrs["ops"] = node["ops"]
                    budget += node["ops"] / (rate * 1e12)
                size = node["input_bytes"] + node["output_bytes"]
                if size:
                    rate = hardware.cpu.memory_bandwidth_gbps_per_node
                    if rate is None:
                        raise ValueError("CPU memory workload requires memory_bandwidth_gbps_per_node")
                    budget += size * 8 / (rate * 1e9)
        elif kind == "qpu":
            if hardware.qpu is None or node["qubits"] > hardware.qpu.qubits:
                raise ValueError("QPU task needs a QPU profile with sufficient qubits")
            result.update(node_type="QPU_EXEC", device_type="QPU", resource_constraints={"qubits": node["qubits"]})
            attrs.update(circuit_count=node["circuit_count"], shots_per_circuit=node["shots"])
            budget += node["circuit_count"] * node["shots"] / hardware.qpu.shot_rate + hardware.qpu.submit_latency_seconds
        else:
            result.update(node_type="POINT_TO_POINT_COMM", device_type="NETWORK_LINK", input_bytes=node["bytes"], output_bytes=node["bytes"])
            attrs.update(src_resource=node["source"], dst_resource=node["destination"])
            budget += node["bytes"] * 8 / min(link.bandwidth_gbps * 1e9 for link in hardware.links) + sum(link.latency_seconds for link in hardware.links)
        native_nodes.append(result)
    cpu = {"node_count": hardware.cpu.count, "cores_per_node": hardware.cpu.cores_per_node}
    for key in ("peak_flops_tflops_per_node", "memory_bandwidth_gbps_per_node"):
        if getattr(hardware.cpu, key) is not None:
            cpu[key] = getattr(hardware.cpu, key)
    native_hardware, native_devices = {"cpu_cluster": cpu}, {"cpu": hardware.cpu.count}
    if hardware.qpu:
        qpu = hardware.qpu
        native_hardware["qpu"] = dict(count=qpu.count, qubits_per_qpu=qpu.qubits, shot_rate=qpu.shot_rate,
                                      submit_latency_us=_microseconds(qpu.submit_latency_seconds), measurement_latency_us=0, availability=1.0)
        native_devices["qpu"] = qpu.count
    links = [dict(src=link.source, dst=link.target, bandwidth_gbps=link.bandwidth_gbps,
                  latency_us=_microseconds(link.latency_seconds)) for link in hardware.links]
    structural_links = False
    if not links:
        # The native validator requires connectivity even for one CPU. A switch
        # supplies connectivity only; without transfer tasks these links carry no traffic.
        native_devices["switch"] = 1
        links = [dict(src=source, dst=target, bandwidth_gbps=1, latency_us=0)
                 for device in devices for source, target in ((device, "switch0"), ("switch0", device))]
        structural_links = True
    else:
        connected = {devices[0]}
        changed = True
        while changed:
            changed = False
            for link in links:
                if link["src"] in connected or link["dst"] in connected:
                    old = len(connected)
                    connected.update((link["src"], link["dst"]))
                    changed |= len(connected) != old
        if connected != set(devices):
            raise ValueError("Configured links must connect all hardware instances")
    scenario = dict(schema_version="v1", metadata={"name": workload.name},
                    system={"hardware": native_hardware, "topology": {"type": "custom_graph", "devices": native_devices, "links": links}},
                    workload={"type": "custom_trace", "trace_file": "task_graph.json", "job_count": len({node["job_id"] for node in nodes})},
                    scheduler={"policy": "earliest_finish_time"},
                    simulation={"network_mode": "analytical", "simulation_time_s": max(60, math.ceil(budget * 10 + 60))},
                    output={"output_format": "csv", "metrics_level": "detailed"})
    model = {"workload": workload.to_dict(), "hardware": hardware.to_dict()}
    return {"task_graph": {"schema_version": "v1", "nodes": native_nodes}, "scenario": scenario,
            "scenario_yaml": "\n".join(_yaml_lines(scenario)) + "\n", "model": model,
            "model_sha256": hashlib.sha256(json.dumps(model, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
            "scope_notes": ["Independent workload estimate; no application code or hardware is executed.",
                            "No external queue, quantum routing, gate-depth, noise or scientific-quality model.",
                            "Phase totals may overlap. CPU/QPU instances within each pool share one profile.",
                            "Explicit durations and submission/link latencies round upward to integer microseconds."],
            "structural_links_only": structural_links}


@dataclass(frozen=True)
class PredictionResult:
    latency_seconds: float
    mean_job_latency_seconds: float
    throughput_jobs_per_hour: float | None
    jobs: tuple[dict[str, Any], ...]
    phase_seconds: dict[str, float]
    communication: dict[str, Any] | None
    main_bottleneck: str
    parameter_sources: dict[str, Any]
    validation_scope: str
    scope_notes: tuple[str, ...]
    simulator_sha256: str
    engine_version: str
    simulator_wall_seconds: float
    simulated_time_seconds: float
    model_sha256: str
    hardware: dict[str, Any]
    output_dir: str | None = None
    scientific_quality_predicted: bool = False

    def to_dict(self):
        return asdict(self)


class Predictor:
    def __init__(self, *, library=None, native_runtime=None, timeout=180):
        from ._internal.performance.runner import PredictionRunner
        self._runner = PredictionRunner(library=library, native_runtime=native_runtime, timeout=timeout)

    def availability(self):
        return self._runner.probe()

    def preview(self, workload, hardware):
        """Validate and compile without loading the native engine or writing files."""
        return _compile(workload, hardware)

    def predict(self, workload, hardware, *, output_dir=None):
        preview = self.preview(workload, hardware)
        if output_dir is None:
            with tempfile.TemporaryDirectory(prefix="pivotq-prediction-") as folder:
                return self._predict(preview, Path(folder), persistent=False)
        folder = Path(output_dir).expanduser().resolve()
        if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
            raise ValueError("output_dir must be new or empty")
        folder.mkdir(parents=True, exist_ok=True)
        return self._predict(preview, folder, persistent=True)

    def _predict(self, preview, folder, *, persistent):
        source = folder / "source"
        source.mkdir()
        (source / "scenario.yaml").write_text(preview["scenario_yaml"], encoding="utf-8")
        (source / "task_graph.json").write_text(json.dumps(preview["task_graph"], ensure_ascii=False, indent=2), encoding="utf-8")
        (source / "model.json").write_text(json.dumps(preview["model"], ensure_ascii=False, indent=2), encoding="utf-8")
        record = self._runner.run_task(source / "scenario.yaml", folder / "native")
        sources = record["parameter_sources"]
        sources["hardware_fields"] = {key: value for key, value in sources["hardware_fields"].items()
                                      if key.startswith(("system.hardware.cpu_cluster.", "system.hardware.qpu."))}
        sources["scope"] = "Explicit task durations and CPU/QPU profiles are caller supplied; native intrinsic overheads remain."
        configured = {f"system.hardware.{section}.{name}" for section, values in preview["scenario"]["system"]["hardware"].items()
                      for name in values}
        sources["fields_using_builtin_defaults"] = [name for name in sources["fields_using_builtin_defaults"] if name not in configured]
        result = PredictionResult(latency_seconds=record["simulated_time_seconds"], mean_job_latency_seconds=record["latency_seconds"],
            throughput_jobs_per_hour=record["throughput_jobs_per_hour"],
            jobs=tuple(record["jobs"]), phase_seconds=record["phase_seconds"], communication=record["communication"],
            main_bottleneck=record["main_bottleneck"], parameter_sources=sources, validation_scope=record["validation_scope"],
            scope_notes=tuple(preview["scope_notes"]), simulator_sha256=record["simulator_sha256"], engine_version=record["engine_version"],
            simulator_wall_seconds=record["simulator_wall_seconds"], simulated_time_seconds=record["simulated_time_seconds"],
            model_sha256=preview["model_sha256"], hardware=preview["model"]["hardware"], output_dir=str(folder) if persistent else None)
        (folder / "prediction.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        return result

    def compare(self, models: Mapping[str, tuple[Workload, Hardware]], *, output_dir=None):
        """Compare caller-supplied alternatives; no quality equivalence is assumed."""
        if not models:
            raise ValueError("compare requires at least one model")
        for name, model in models.items():
            _label(name, "comparison name")
            if not isinstance(model, (tuple, list)) or len(model) != 2:
                raise ValueError("each comparison value must be (workload, hardware)")
            self.preview(*model)
        if output_dir is not None:
            folder = Path(output_dir).expanduser().resolve()
            if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
                raise ValueError("output_dir must be new or empty")
            folder.mkdir(parents=True, exist_ok=True)
        else:
            folder = None
        results = {name: self.predict(*model, output_dir=folder / f"case-{index:03d}" if folder else None)
                   for index, (name, model) in enumerate(models.items())}
        if folder:
            (folder / "comparison.json").write_text(json.dumps({"quality_equivalence_verified": False,
                "predictions": {name: result.to_dict() for name, result in results.items()}}, ensure_ascii=False, indent=2), encoding="utf-8")
        return results


__all__ = ["Workload", "Hardware", "CPUProfile", "QPUProfile", "LinkProfile", "Predictor", "PredictionResult"]
