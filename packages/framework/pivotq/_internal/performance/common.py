import csv
import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite_number(value, label, positive=False):
    require(type(value) in (int, float) and math.isfinite(value), f"{label} must be a finite number")
    require(value > 0 if positive else value >= 0, f"Invalid {label}: {value}")
    return value


def read_json(path):
    require(path.is_file(), f"Missing input file: {path}")
    require(path.stat().st_size <= 64 * 1024 * 1024, f"JSON input too large: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def empty_output(path):
    require(not path.exists() or (path.is_dir() and not any(path.iterdir())),
            f"Output directory must be new or empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def node_timeline(output, nodes):
    starts, ends = {}, {}
    for event in read_csv(output / "runtime_events.csv"):
        node_id = int(event["node_id"])
        if event["event_type"] == "ComputeStart" and event["unit"] == "resource_score":
            require(node_id not in starts, "Duplicate node start event")
            starts[node_id] = Decimal(event["time_s"])
        elif event["event_type"] == "TaskFinish":
            require(node_id not in ends, "Duplicate node completion event")
            ends[node_id] = Decimal(event["time_s"])
    require(set(starts) == set(ends) == {n["node_id"] for n in nodes},
            f"Incomplete task event timeline in {output}; inspect run.log and the simulation time limit")
    require(all(ends[node_id] >= start for node_id, start in starts.items()), "Invalid node event timestamps")
    return starts, ends


def node_durations(output, nodes):
    starts, ends = node_timeline(output, nodes)
    return {node_id: float(ends[node_id] - start) for node_id, start in starts.items()}
