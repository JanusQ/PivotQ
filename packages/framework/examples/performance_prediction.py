"""Predict independently authored CPU/QPU models; no application or QPU is run."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json

from pivotq.performance import CPUProfile, Hardware, Predictor, QPUProfile, Workload


def run(*, native_runtime=None, library=None, shots=1024, shot_rate=10000, output_dir=None):
    workload = Workload("feedback_iteration")
    prepared = workload.cpu("prepare", duration_seconds=0.002)
    measured = workload.qpu("quantum", qubits=5, shots=shots, depends_on=[prepared])
    workload.cpu("update", duration_seconds=0.001, depends_on=[measured])

    hardware = Hardware(
        cpu=CPUProfile(count=1, cores_per_node=4),
        qpu=QPUProfile(qubits=8, shot_rate=shot_rate, submit_latency_seconds=0.001,
                       source="Illustrative throughput; not measured on a physical QPU"),
    )
    cpu_workload = Workload("cpu_reference")
    cpu_workload.cpu("classical_algorithm", duration_seconds=0.25)
    predictor = Predictor(native_runtime=native_runtime, library=library)
    predictions = predictor.compare({
        "cpu_reference": (cpu_workload, Hardware(cpu=hardware.cpu)),
        "cpu_qpu": (workload, hardware),
        "faster_qpu": (workload, replace(hardware, qpu=replace(hardware.qpu, shot_rate=2 * shot_rate))),
    }, output_dir=output_dir)
    return {"quality_equivalence_verified": False,
            "predictions": {name: prediction.to_dict() for name, prediction in predictions.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-runtime", help="Existing private Linux runtime directory, if required")
    parser.add_argument("--library", help="Override the bundled native engine")
    parser.add_argument("--shots", type=int, default=1024)
    parser.add_argument("--shot-rate", type=int, default=10000)
    parser.add_argument("--out", dest="output_dir", help="New or empty directory for input snapshots, CSV and JSON")
    print(json.dumps(run(**vars(parser.parse_args())), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
