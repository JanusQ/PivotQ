"""A reusable CPU/quantum workflow with a stateful actor and execution report.

Run: python examples/system_workflow.py
Ray: python examples/system_workflow.py --executor ray --address local
This example uses only a quantum simulator and is independent of AIMD.
"""

from __future__ import annotations

import argparse
import json

import pivotq as pq


def build_circuit(theta: float):
    from qiskit import QuantumCircuit
    circuit = QuantumCircuit(3)
    circuit.ry(theta, 0)
    circuit.cx(0, 1)
    circuit.cx(1, 2)
    circuit.measure_all()
    return circuit


class History:
    def __init__(self):
        self.values = []

    def record(self, measurement: pq.QuantumResult):
        self.values.append(measurement.probabilities.get("111", 0.0))
        return {"steps": len(self.values), "probabilities": list(self.values)}


def make_workflow():
    workflow = pq.Workflow("quantum-feedback")
    theta = workflow.input("theta")
    circuit = workflow.task(build_circuit, theta, name="prepare")
    measurement = workflow.quantum("quantum", circuit, shots=512, seed=7, name="measure")
    recorded = workflow.component("history", "record", measurement, name="record")
    workflow.output("history", recorded)
    return workflow


def run(*, executor="local", address=None, report_path=None):
    workflow = make_workflow()
    with pq.Runtime(executor=executor, address=address, trace=True) as runtime:
        history = runtime.actor(History, methods=("record",), name="history")
        quantum = runtime.quantum_backend("simulator")
        for theta in (0.5, 1.0):
            execution = runtime.run(workflow, inputs={"theta": theta},
                                    bindings={"history": history, "quantum": quantum})
            ready, pending = runtime.wait(execution.refs, num_returns=len(execution.refs), timeout=60)
            if pending:
                raise RuntimeError("example workflow did not finish before the wait timeout")
            result = runtime.get(execution.outputs["history"])
            assert runtime.status(execution.outputs["history"]) is pq.InvocationStatus.SUCCEEDED
            execution.release()
    report = runtime.report()
    if report_path is not None:
        report.export(report_path)
    return {"result": result, "trace_records": len(report.records),
            "report_available_after_close": report.closed,
            "is_simulated": True, "dropped_records": report.dropped_records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor", choices=("local", "ray"), default="local")
    parser.add_argument("--address")
    parser.add_argument("--report-path")
    print(json.dumps(run(**vars(parser.parse_args())), indent=2))


if __name__ == "__main__":
    main()
