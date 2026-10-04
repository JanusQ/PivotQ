"""Run an ordinary user script through real local Ray workers."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.skipif(importlib.util.find_spec("ray") is None, reason="Ray is not installed")
def test_script_functions_cloudpickle_and_shared_runtime(tmp_path):
    script = tmp_path / "user_program.py"
    script.write_text(textwrap.dedent('''
        import sys
        from pivotq import Runtime, Workflow, InvocationStatus
        assert "ray" not in sys.modules
        assert "qiskit" not in sys.modules

        def prepare(value):
            return {"value": value * 2}

        def make_loss(offset):
            def loss(value):
                return value["value"] + offset
            return loss

        def build_quantum_circuit():
            from qiskit import QuantumCircuit
            circuit = QuantumCircuit(5)
            circuit.h(0)
            for target in range(1, 5):
                circuit.cx(0, target)
            circuit.x(0)
            circuit.measure_all()
            return circuit

        def consume_quantum_result(result):
            from pivotq import QuantumResult
            assert isinstance(result, QuantumResult)
            assert result.backend == "simulator" and result.is_simulated
            assert result.bit_order == "c[n-1]...c0"
            assert result.shots == 1024
            assert set(result.counts) == {"00001", "11110"}
            assert sum(result.counts.values()) == 1024
            assert result.probabilities == {
                bits: count / 1024 for bits, count in result.counts.items()
            }
            return result.probabilities["11110"]

        class Accumulator:
            def __init__(self):
                self.value = 0.0

            def add(self, value):
                self.value += value
                return self.value

        first = Runtime(executor="ray", address="local", trace=True)
        second = Runtime(executor="ray")
        try:
            prepared = first.submit(prepare, 3)
            loss = first.submit(make_loss(1), prepared)
            assert first.get(loss) == 7
            first.release(loss, prepared)
            circuit = first.submit(build_quantum_circuit)
            quantum = first.quantum_backend("simulator")
            measurement = quantum.submit(circuit, shots=1024, seed=13)
            probability = first.submit(consume_quantum_result, measurement)
            assert abs(first.get(probability) - 0.5) < 0.06
            first.release(probability, measurement, circuit)
            accumulator = first.actor(Accumulator, methods=("add",), name="accumulator")
            workflow = Workflow("script-hybrid")
            circuit_node = workflow.task(build_quantum_circuit, name="circuit")
            measurement_node = workflow.quantum("quantum", circuit_node, shots=1024, seed=13)
            probability_node = workflow.task(consume_quantum_result, measurement_node)
            accumulated_node = workflow.component("accumulator", "add", probability_node)
            workflow.output("total", accumulated_node)
            totals = []
            for _ in range(2):
                execution = first.run(workflow, bindings={"quantum": quantum, "accumulator": accumulator})
                ready, pending = first.wait(execution.refs, num_returns=len(execution.refs), timeout=30)
                assert len(ready) == 4 and not pending
                assert first.status(execution.outputs["total"]) is InvocationStatus.SUCCEEDED
                totals.append(first.get(execution.outputs["total"]))
                execution.release()
            assert totals[1] == 2 * totals[0]
            other = second.submit(prepare, 4)
            assert second.get(other) == {"value": 8}
            first.close()
            report = first.report()
            assert report.closed and len(report.records) == 13
            assert {row["trace_context"].get("workflow.name") for row in report.records} >= {"script-hybrid"}
            assert second.get(second.submit(prepare, 5)) == {"value": 10}
            print("PIVOTQ_SCRIPT_RAY_PASS", flush=True)
        finally:
            first.close()
            second.close()
        import ray
        assert not ray.is_initialized()
    '''), encoding="utf-8")
    environment = dict(os.environ)
    framework_root = str(Path(__file__).resolve().parents[2])
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [framework_root, environment.get("PYTHONPATH")]))
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.pop("RAY_ADDRESS", None)
    completed = subprocess.run([sys.executable, "-B", str(script)],
                               env=environment, cwd=tmp_path,
                               capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PIVOTQ_SCRIPT_RAY_PASS" in completed.stdout
