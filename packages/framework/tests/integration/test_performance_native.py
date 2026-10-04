"""Opt-in offline native engine checks; never submits a physical device job."""
import csv
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pivotq.errors import ExecutionError
from pivotq.performance import CPUProfile, Hardware, LinkProfile, Predictor, QPUProfile, Workload
from pivotq._internal.performance.runner import PredictionRunner

pytestmark = pytest.mark.skipif(os.environ.get("PIVOTQ_RUN_NATIVE_PREDICTIONS") != "1", reason="opt-in native engine integration")


@pytest.fixture
def predictor():
    predictor = Predictor()
    assert predictor.availability()["available"], predictor.availability()
    return predictor


def quantum_work(shots=1000):
    work = Workload()
    work.qpu("q", qubits=5, shots=shots)
    return work


def test_shots_rate_and_submission_latency(predictor):
    hardware = Hardware(qpu=QPUProfile(qubits=8, shot_rate=10000, submit_latency_seconds=0.001))
    assert predictor.predict(quantum_work(), hardware).latency_seconds == pytest.approx(0.101)
    assert predictor.predict(quantum_work(2000), hardware).latency_seconds == pytest.approx(0.201)
    assert predictor.predict(quantum_work(), replace(hardware, qpu=replace(hardware.qpu, shot_rate=5000))).latency_seconds == pytest.approx(0.201)
    assert predictor.predict(quantum_work(), replace(hardware, qpu=replace(hardware.qpu, submit_latency_seconds=0.011))).latency_seconds == pytest.approx(0.111)


def test_cpu_only_pool_parallelism_and_job_metric(predictor):
    work = Workload()
    work.cpu("left", duration_seconds=0.1, target="cpu0")
    work.cpu("right", duration_seconds=0.2, target="cpu1", job_id="second")
    result = predictor.predict(work, Hardware(cpu=CPUProfile(count=2)))
    assert result.latency_seconds == pytest.approx(0.2)
    assert result.mean_job_latency_seconds == pytest.approx(0.15)
    assert result.simulated_time_seconds == pytest.approx(0.2)
    assert sum(result.phase_seconds.values()) == pytest.approx(0.3)
    assert len(result.jobs) == 2
    single = Workload()
    single.cpu("only", duration_seconds=0.012)
    assert predictor.predict(single, Hardware()).latency_seconds == pytest.approx(0.012)


def test_target_pin_and_saved_provenance(predictor, tmp_path):
    work = Workload()
    work.qpu("quantum", qubits=5, shots=1000, target="qpu1")
    result = predictor.predict(work, Hardware(qpu=QPUProfile(qubits=8, shot_rate=10000, count=2)), output_dir=tmp_path)
    with (tmp_path / "native/output/runtime_events.csv").open() as stream:
        events = [row for row in csv.DictReader(stream) if row["event_type"] == "ComputeStart"]
    assert [row["resource_id"] for row in events] == ["qpu1"]
    assert (tmp_path / "source/model.json").is_file()
    assert len(result.model_sha256) == len(result.simulator_sha256) == 64
    assert result.engine_version == "0.1.0"
    assert json.loads((tmp_path / "prediction.json").read_text())["output_dir"] == str(tmp_path)


def test_communication_bandwidth_changes_prediction(predictor):
    work = Workload()
    work.transfer("upload", source="cpu0", target="qpu0", bytes=1000000)
    qpu = QPUProfile(qubits=8, shot_rate=10000)
    slow = Hardware(qpu=qpu, links=(LinkProfile("cpu0", "qpu0", 1), LinkProfile("qpu0", "cpu0", 1)))
    fast = replace(slow, links=(LinkProfile("cpu0", "qpu0", 2), LinkProfile("qpu0", "cpu0", 2)))
    first, second = predictor.predict(work, slow), predictor.predict(work, fast)
    assert first.latency_seconds > second.latency_seconds > 0
    assert first.communication["transfer_bytes"] == 1000000


def test_cpu_operation_model_sensitivity(predictor):
    work = Workload()
    work.cpu("compute", ops=1000000000000)
    slow = Hardware(cpu=CPUProfile(peak_flops_tflops_per_node=1))
    fast = Hardware(cpu=CPUProfile(peak_flops_tflops_per_node=2))
    assert predictor.predict(work, slow).latency_seconds > predictor.predict(work, fast).latency_seconds


def test_cpu_memory_bandwidth_uses_bits_per_second(predictor):
    work = Workload()
    work.cpu("memory", input_bytes=1000000000)
    result = predictor.predict(work, Hardware(cpu=CPUProfile(memory_bandwidth_gbps_per_node=1)))
    assert 8 <= result.latency_seconds < 8.001


def test_partial_native_completion_is_not_success(predictor, tmp_path):
    work = Workload()
    work.cpu("long", duration_seconds=10)
    preview = predictor.preview(work, Hardware())
    source = tmp_path / "source"
    source.mkdir()
    (source / "scenario.yaml").write_text(preview["scenario_yaml"].replace("simulation_time_s: 160", "simulation_time_s: 0.001"))
    (source / "task_graph.json").write_text(json.dumps(preview["task_graph"]))
    with pytest.raises(ExecutionError, match="did not complete"):
        PredictionRunner().run_task(source / "scenario.yaml", tmp_path / "failed")
    assert (tmp_path / "failed/worker.response.json").is_file()


def test_shared_raw_adapter_and_validation(predictor, tmp_path):
    work = Workload()
    work.cpu("task", duration_seconds=0.01)
    preview = predictor.preview(work, Hardware())
    (tmp_path / "scenario.yaml").write_text(preview["scenario_yaml"])
    (tmp_path / "task_graph.json").write_text(json.dumps(preview["task_graph"]))
    runner = PredictionRunner()
    runner.validate(tmp_path / "scenario.yaml")
    result = runner.run_raw(tmp_path / "scenario.yaml", tmp_path / "raw")
    assert result["interface"] == "c_api"
    assert result["csv"]["summary.csv"][0]["task_completion_ratio"] == "1"
    assert result["simulated_time_us"] > 0


def test_single_documented_example_source(predictor, tmp_path):
    example = Path(__file__).resolve().parents[2] / "examples/performance_prediction.py"
    spec = importlib.util.spec_from_file_location("performance_example", example)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.run(shots=1000, output_dir=tmp_path)
    assert result["predictions"]["cpu_qpu"]["latency_seconds"] == pytest.approx(0.104)
    assert result["predictions"]["faster_qpu"]["latency_seconds"] == pytest.approx(0.054)
    assert result["predictions"]["cpu_reference"]["latency_seconds"] == pytest.approx(0.25)
    assert not result["quality_equivalence_verified"]
