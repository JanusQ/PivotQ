"""Virtual hardware coverage, task widths, model provenance and native sensitivity."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend.circuit_parser import parse_quantum_circuit
from backend.hardware_profiles import target_snapshot
from backend.models import StagePlan, WorkflowPlan
from backend.qperfsim import QPerfSimClient, QPerfSimUnavailable
from backend.qperfsim_virtual import build_virtual_case, cpu_inference_workload

ROOT = Path(__file__).resolve().parents[3]
PERF = ROOT / "packages/perf-sim"
sys.path.insert(0, str(PERF / "scripts"))
PARAMETERS = json.loads((PERF / "examples/h2o/prediction_parameters.json").read_text())
BELL = parse_quantum_circuit("circuit = QuantumCircuit(2)\ncircuit.h(0)\ncircuit.cx(0,1)\ncircuit.measure([0,1])")


def circuit_plan(shots=1000):
    return WorkflowPlan("quantum-circuit", "1.0", {"shots": shots, "seed": 42}, (
        StagePlan("circuit_execution", "电路执行", "qpu", (), {}, "fake-sc-36", target_snapshot("fake-sc-36", 2)),))


def h2o_plan(classical="cpu", steps=1):
    return WorkflowPlan("h2o-hybrid-aimd", "1.0", {"steps": steps, "checkpoint_id": "hybrid_model.pt"}, (
        StagePlan("quantum_features", "量子", "qpu", (), {}, "fake-sc-36", target_snapshot("fake-sc-36", 3)),
        StagePlan("classical_predict", "经典", classical, (), {}, classical + "-0", target_snapshot(classical + "-0"))))


class VirtualPredictionTests(unittest.TestCase):
    def test_small_circuit_requests_two_qubits_on_36_qubit_scene(self):
        graph, scene, request, scope = build_virtual_case(circuit_plan().as_dict(), {"circuit": BELL}, PARAMETERS)
        node = graph["nodes"][0]
        self.assertEqual(node["resource_constraints"]["qubits"], 2)
        self.assertEqual(node["attrs"], {"phase": "circuit_execution.acquisition", "circuit_count": 1, "shots_per_circuit": 1000})
        self.assertIn("qubits_per_qpu: 36", scene)
        self.assertEqual(request["logical_qubits"], 2)
        self.assertFalse(scope["calibrated"])
        self.assertFalse(scope["topology_used_for_routing"])

    def test_saved_profile_is_used_and_inconsistent_width_is_rejected(self):
        plan = circuit_plan().as_dict()
        plan["stages"][0]["target_snapshot"]["parameters"]["shot_rate"] = 2500
        _, scene, request, _ = build_virtual_case(plan, {"circuit": BELL}, PARAMETERS)
        self.assertIn("shot_rate: 2500", scene)
        self.assertEqual(request["target_snapshot"]["parameters"]["shot_rate"], 2500)
        plan["stages"][0]["target_snapshot"]["logical_qubits"] = 36
        with self.assertRaisesRegex(ValueError, "不一致"):
            build_virtual_case(plan, {"circuit": BELL}, PARAMETERS)

    def test_classical_cpu_work_comes_from_dimensions_and_batch(self):
        model = {"layers": [{"input": 14, "output": 32}, {"input": 32, "output": 32}, {"input": 32, "output": 1}],
                 "dtype_bytes": 8, "parameter_bytes": 12552}
        work = cpu_inference_workload(model, 19)
        self.assertEqual(work["ops"], 19 * (2 * (14 * 32 + 32 * 32 + 32) + 65))
        graph, scene, request, scope = build_virtual_case(h2o_plan().as_dict(), None, PARAMETERS, classical_model=model)
        classical = [n for n in graph["nodes"] if n["attrs"]["phase"].endswith(".classical")]
        self.assertEqual(len(classical), 4)
        self.assertEqual(classical[-1]["attrs"]["ops"], work["ops"])
        self.assertTrue(all(n["device_type"] == "CPU" and n["estimated_duration_us"] == 0 for n in classical))
        self.assertEqual(request["circuits"], 724)
        self.assertEqual(request["qpu_batch_count"], 26)
        self.assertEqual(request["shots"], 3000)
        self.assertEqual(request["batch_size"], 32)
        self.assertIn("peak_flops_tflops_per_node: 1", scene)
        self.assertFalse(scope["parameter_sources"]["classical"]["calibrated"])
        self.assertTrue(any("1 TFLOPS" in note and "100 Gbit/s" in note and "14→32→32→1" in note and "2 次" in note for note in scope["notes"]))

    def test_classical_gpu_keeps_a100_source(self):
        graph, _, _, scope = build_virtual_case(h2o_plan("gpu").as_dict(), None, PARAMETERS)
        classical = [n for n in graph["nodes"] if n["attrs"]["phase"].endswith(".classical")]
        self.assertEqual(classical[-1]["estimated_duration_us"], round(PARAMETERS["gpu"]["invocations"]["step"]["seconds"]["classical_actor"] * 1e6))
        self.assertIn("A100", scope["parameter_sources"]["classical"]["hardware"]["gpu"])

    def test_preview_does_not_use_native_or_private_loader(self):
        client = QPerfSimClient(PERF)
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"FUSION_QPERFSIM_RUNTIME": "/missing/loader"}), patch.object(client, "availability", return_value={"available": False, "reason": "native-unavailable"}):
            preview = client.predict(circuit_plan(), Path(temp) / "preview", preview=True, program={"circuit": BELL})
            self.assertNotIn("result", preview)
            self.assertTrue(Path(preview["task_graph_path"]).is_file())
            with self.assertRaisesRegex(QPerfSimUnavailable, "native-unavailable"):
                client.predict(circuit_plan(), Path(temp) / "run", program={"circuit": BELL})

    def test_model_coverage_is_independent_of_cpu_execution(self):
        self.assertIsNone(QPerfSimClient.prediction_reason(circuit_plan()))
        self.assertIsNone(QPerfSimClient.prediction_reason(h2o_plan("cpu")))
        plan = circuit_plan()
        cpu = replace(plan.stages[0], device="cpu", target_id="cpu-0", target_snapshot=target_snapshot("cpu-0", 2))
        self.assertIsNotNone(QPerfSimClient.prediction_reason(replace(plan, stages=(cpu,))))


@unittest.skipUnless(os.environ.get("QHAI_RUN_NATIVE_PREDICTIONS") == "1", "opt-in native prediction integration")
class VirtualNativePredictionTests(unittest.TestCase):
    def test_shots_throughput_and_submission_sensitivity(self):
        from backend.paths import configure_defaults
        from backend.circuit_runner import simulate
        configure_defaults()
        client = QPerfSimClient(PERF)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            baseline = circuit_plan()
            slower = deepcopy(baseline)
            slower.stages[0].target_snapshot["parameters"]["shot_rate"] = 5000
            delayed = deepcopy(baseline)
            delayed.stages[0].target_snapshot["parameters"]["submit_latency_us"] = 11000
            ideal, baseline_counts = simulate(BELL, 1000, 42, device="cpu")
            self.assertEqual(set(ideal), {"00", "11"})
            self.assertAlmostEqual(ideal["00"], 0.5)
            for label, plan, expected in (("base", baseline, 0.101), ("shots", circuit_plan(2000), 0.201),
                                          ("slower", slower, 0.201), ("delayed", delayed, 0.111)):
                result = client.predict(plan, folder / label, program={"circuit": BELL})["result"]["prediction"]
                self.assertAlmostEqual(result["latency_seconds"], expected, places=6)
                self.assertEqual(result["task_completion_ratio"], 1)
                self.assertEqual(result["logical_qubits"], 2)
                probabilities, counts = simulate(BELL, plan.normalized_inputs["shots"], 42, device="cpu")
                self.assertEqual(probabilities, ideal)
                self.assertEqual(sum(counts.values()), plan.normalized_inputs["shots"])
                if label != "shots":
                    self.assertEqual(counts, baseline_counts)

    def test_h2o_cpu_and_gpu_classical_complete(self):
        from backend.paths import configure_defaults
        configure_defaults()
        client = QPerfSimClient(PERF)
        with tempfile.TemporaryDirectory() as temp:
            for classical in ("cpu", "gpu"):
                result = client.predict(h2o_plan(classical), Path(temp) / classical)
                prediction = result["result"]["prediction"]
                self.assertEqual(prediction["task_completion_ratio"], 1)
                self.assertEqual(prediction["qpu_batch_count"], 26)
                self.assertAlmostEqual(prediction["qpu_acquisition_seconds"], 217.2, places=6)
                self.assertFalse(result["model_scope"]["calibrated"])
                if classical == "cpu":
                    model = result["model_scope"]["parameter_sources"]["classical"]["model"]
                    self.assertEqual([layer["input"] for layer in model["layers"]], [14, 32, 32])


if __name__ == "__main__":
    unittest.main()
