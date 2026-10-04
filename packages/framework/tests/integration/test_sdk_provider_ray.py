"""Third-party providers defined outside PivotQ run on real local Ray workers."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.skipif(importlib.util.find_spec("ray") is None, reason="Ray is not installed")
def test_user_provider_tasks_actors_measurements_and_failure_identity(tmp_path):
    script = tmp_path / "provider_program.py"
    script.write_text(textwrap.dedent('''
        import os
        import sys
        from pathlib import Path
        from pivotq import Runtime
        from pivotq.providers import BackendCapabilities, ProviderResult
        from pivotq.errors import ResultUnknownError
        assert "ray" not in sys.modules and "qiskit" not in sys.modules

        class Provider:
            def __init__(self, *, closed_path):
                self.closed_path = closed_path
                self.sequence = 0

            def run(self, request):
                from qiskit.quantum_info import Statevector
                assert request.circuit.num_clbits == 0
                self.sequence += 1
                state = Statevector.from_instruction(request.circuit)
                state.seed(request.seed)
                return ProviderResult(
                    request.shots, "offline_ray_samples",
                    counts={str(k): int(v) for k, v in state.sample_counts(shots=request.shots).items()},
                    metadata={"pid": os.getpid(), "sequence": self.sequence},
                )

            def close(self):
                with open(self.closed_path, "a") as handle:
                    handle.write("closed\\n")

        class UnknownProvider:
            def __init__(self, *, attempts_path):
                self.attempts_path = attempts_path

            def run(self, request):
                with open(self.attempts_path, "a") as handle:
                    handle.write(request.request_id + "\\n")
                raise ResultUnknownError("offline response lost", backend_job_id="offline-job")

            def close(self):
                pass

        def prepare():
            from qiskit import QuantumCircuit
            circuit = QuantumCircuit(3, 2)
            circuit.x(0)
            circuit.h(2)
            circuit.measure(0, 1)
            circuit.measure(2, 0)
            return circuit

        def consume(result):
            assert result.bit_order == "c[n-1]...c0"
            assert set(result.counts) == {"10", "11"}
            assert sum(result.counts.values()) == 1024
            return result.metadata

        root = Path(sys.argv[1])
        driver_pid = os.getpid()
        caps = BackendCapabilities(8, True, supports_seed=True)
        with Runtime(executor="ray", address="local") as runtime:
            runtime.register_quantum_backend("user-task", Provider, capabilities=caps)
            task = runtime.quantum_backend("user-task", closed_path=str(root / "task-closed.txt"))
            circuit = runtime.submit(prepare)
            first = task.submit(circuit, shots=1024, seed=4)
            final = runtime.submit(consume, first)
            metadata = runtime.get(final)
            assert metadata["pid"] != driver_pid and metadata["sequence"] == 1
            runtime.release(final, first, circuit)

            # A simulated actor exercises actual worker reuse and serial call
            # ordering while retaining the same provider protocol.
            runtime.register_quantum_backend("user-actor", Provider, capabilities=caps, execution="actor")
            actor = runtime.quantum_backend("user-actor", closed_path=str(root / "actor-closed.txt"))
            refs = [actor.submit(prepare(), seed=5) for _ in range(3)]
            results = [runtime.get(ref) for ref in refs]
            assert [result.metadata["sequence"] for result in results] == [1, 2, 3]
            assert len({result.metadata["pid"] for result in results}) == 1
            runtime.release(*refs)

            # Declared physical-provider failure is fully offline: only this
            # fixture writes a local file; it never creates a device client.
            runtime.register_quantum_backend("offline-unknown", UnknownProvider,
                capabilities=BackendCapabilities(8, False))
            unknown = runtime.quantum_backend("offline-unknown", attempts_path=str(root / "attempts.txt"))
            failure = unknown.submit(prepare())
            downstream = runtime.submit(consume, failure)
            for _ in range(2):
                try:
                    runtime.get(downstream)
                    raise AssertionError("unknown execution unexpectedly succeeded")
                except ResultUnknownError as error:
                    assert error.backend_job_id == "offline-job"
                    assert error.framework_job_id.startswith("sdk-")
            runtime.release(downstream, failure)
        assert (root / "task-closed.txt").read_text().splitlines() == ["closed"]
        assert (root / "actor-closed.txt").read_text().splitlines() == ["closed"]
        assert len((root / "attempts.txt").read_text().splitlines()) == 1
        import ray
        assert not ray.is_initialized()
        print("PIVOTQ_PROVIDER_RAY_PASS")
    '''), encoding="utf-8")
    environment = _environment()
    completed = subprocess.run(
        [sys.executable, "-B", str(script), str(tmp_path)], env=environment,
        cwd=tmp_path, capture_output=True, text=True, timeout=150,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PIVOTQ_PROVIDER_RAY_PASS" in completed.stdout


@pytest.mark.skipif(importlib.util.find_spec("ray") is None, reason="Ray is not installed")
def test_documented_custom_provider_example_runs_on_ray(tmp_path):
    example = Path(__file__).resolve().parents[2] / "examples/custom_backend.py"
    completed = subprocess.run(
        [sys.executable, "-B", str(example), "--executor", "ray"], env=_environment(),
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    records = [json.loads(line) for line in completed.stdout.splitlines() if line.startswith("{")]
    assert len(records) == 1
    result = records[0]
    assert result["backend"] == "custom-simulator" and result["is_simulated"]
    assert set(result["counts"]) == {"10", "11"}
    assert sum(result["counts"].values()) == result["shots"] == 1024


def _environment():
    environment = dict(os.environ)
    framework_root = str(Path(__file__).resolve().parents[2])
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [framework_root, environment.get("PYTHONPATH")]))
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.pop("RAY_ADDRESS", None)
    return environment
