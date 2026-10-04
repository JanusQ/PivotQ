"""A small CPU–quantum feedback loop, independent of the AIMD application.

Run after installing PivotQ: python examples/hybrid_program.py
The parameter feedback is a programming example, not a VQE optimizer.
"""
from __future__ import annotations

import argparse
import json

import pivotq as pq
from qiskit import QuantumCircuit


def build_circuit(theta: float) -> QuantumCircuit:
    circuit = QuantumCircuit(3)
    circuit.ry(theta, 0)
    circuit.cx(0, 1)
    circuit.cx(1, 2)
    circuit.measure_all()
    return circuit


def update_parameter(theta: float, result: pq.QuantumResult) -> tuple[float, float]:
    probability = result.probabilities.get("111", 0.0)
    error = probability - 0.5
    return theta - 0.5 * error, abs(error)


def run(*, executor="local", backend="simulator", address=None,
        steps=30, shots=2048, seed=7):
    if steps < 1 or shots < 1:
        raise ValueError("steps and shots must be positive")
    records = []
    with pq.Runtime(executor=executor, address=address) as runtime:
        quantum = runtime.quantum_backend(backend)
        theta = 1.0
        for step in range(steps):
            circuit = runtime.submit(build_circuit, theta)
            measurement = quantum.submit(
                circuit, shots=shots,
                seed=seed + step if backend == "simulator" else None,
            )
            updated = runtime.submit(update_parameter, theta, measurement)
            theta, error = runtime.get(updated)
            result = runtime.get(measurement)
            records.append({"step": step, "theta": theta, "error": error})
            runtime.release(updated, measurement, circuit)
            if error < 0.02:
                break
    return {
        "backend": result.backend,
        "is_simulated": result.is_simulated,
        "iterations": len(records),
        "converged": records[-1]["error"] < 0.02,
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor", choices=("local", "ray"), default="local")
    parser.add_argument("--backend", default="simulator", help="Quantum backend name")
    parser.add_argument("--address", help="Ray address, e.g. local or auto")
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--shots", type=int, default=2048)
    parser.add_argument("--seed", type=int, default=7, help="Simulator sampling seed")
    args = parser.parse_args()
    print(json.dumps(run(**vars(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
