"""User-facing model validation is independent of native engine availability."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

import pytest

from pivotq.errors import ExecutionError, TimeoutError, UnavailableError
from pivotq.performance import CPUProfile, Hardware, LinkProfile, Predictor, QPUProfile, Workload
from pivotq._internal.performance.runner import PredictionRunner


def hybrid():
    work = Workload("hybrid")
    ready = work.cpu("prepare", duration_seconds=0.01)
    work.qpu("quantum", qubits=5, shots=1000, depends_on=[ready])
    return work, Hardware(qpu=QPUProfile(qubits=8, shot_rate=10000))


def test_preview_never_runs_native_and_does_not_mutate_inputs():
    work, hardware = hybrid()
    before = work.to_dict(), hardware.to_dict()
    with patch("subprocess.run", side_effect=AssertionError("must not spawn")), patch("ctypes.CDLL", side_effect=AssertionError("must not load")):
        preview = Predictor(library="/missing/library", native_runtime="/missing/runtime").preview(work, hardware)
    assert preview["task_graph"]["nodes"][1]["resource_constraints"]["qubits"] == 5
    assert before == (work.to_dict(), hardware.to_dict())
    assert len(preview["model_sha256"]) == 64
    assert "GPU" not in json.dumps(preview)


def test_workload_and_hardware_roundtrip_preserves_prediction_input():
    work, hardware = hybrid()
    work.transfer("upload", source="cpu0", target="qpu0", bytes=4096, depends_on=["prepare"])
    hardware = replace(hardware, links=(LinkProfile("cpu0", "qpu0", 1), LinkProfile("qpu0", "cpu0", 1)))
    assert Predictor().preview(work, hardware) == Predictor().preview(Workload.from_dict(work.to_dict()), Hardware.from_dict(hardware.to_dict()))


def test_diamond_dependency_graph_and_multi_job_are_preserved():
    work = Workload()
    root = work.cpu("root", duration_seconds=0.1)
    left = work.cpu("left", duration_seconds=0.2, depends_on=[root])
    right = work.cpu("right", duration_seconds=0.3, depends_on=[root], job_id="second")
    work.cpu("join", duration_seconds=0.1, depends_on=[left, right])
    graph = Predictor().preview(work, Hardware())
    assert graph["task_graph"]["nodes"][-1]["dependencies"] == [2, 3]
    assert graph["scenario"]["workload"]["job_count"] == 2


@pytest.mark.parametrize("factory", [
    lambda: CPUProfile(count=0), lambda: CPUProfile(cores_per_node=True),
    lambda: CPUProfile(peak_flops_tflops_per_node=float("nan")),
    lambda: QPUProfile(qubits=0, shot_rate=1), lambda: QPUProfile(qubits=1, shot_rate=1.5),
    lambda: QPUProfile(qubits=1, shot_rate=1, submit_latency_seconds=-1),
    lambda: LinkProfile("cpu0", "cpu0", 1), lambda: LinkProfile("cpu0", "qpu0", 0),
    lambda: Workload().cpu("zero", duration_seconds=0), lambda: Workload().cpu("unknown"),
    lambda: Workload().cpu("ambiguous", duration_seconds=1, ops=1000),
    lambda: Workload().qpu("bad", qubits=1, shots=True),
    lambda: Workload().transfer("empty", source="cpu0", target="qpu0", bytes=0),
])
def test_invalid_public_model_values_are_rejected(factory):
    with pytest.raises((ValueError, TypeError)):
        factory()


def test_missing_dependencies_and_cycles_rejected_before_native():
    work = Workload()
    work.cpu("first", duration_seconds=1, depends_on=["second"])
    with pytest.raises(ValueError, match="Unknown dependencies"):
        Predictor().preview(work, Hardware())
    work.cpu("second", duration_seconds=1, depends_on=["first"])
    with pytest.raises(ValueError, match="cycle"):
        Predictor().preview(work, Hardware())


def test_model_work_requires_corresponding_explicit_hardware_rates():
    work = Workload()
    work.cpu("ops", ops=10000, input_bytes=100)
    with pytest.raises(ValueError, match="peak_flops"):
        Predictor().preview(work, Hardware())
    with pytest.raises(ValueError, match="memory_bandwidth"):
        Predictor().preview(work, Hardware(cpu=CPUProfile(peak_flops_tflops_per_node=1)))


def test_targets_capacity_and_directed_link_routes_are_validated():
    work, hardware = hybrid()
    with pytest.raises(ValueError, match="sufficient qubits"):
        Predictor().preview(work, Hardware())
    with pytest.raises(ValueError, match="sufficient qubits"):
        Predictor().preview(work, replace(hardware, qpu=QPUProfile(qubits=2, shot_rate=10000)))
    work.transfer("send", source="cpu0", target="qpu0", bytes=100)
    with pytest.raises(ValueError, match="directed communication route"):
        Predictor().preview(work, replace(hardware, links=(LinkProfile("qpu0", "cpu0", 1),)))
    pinned = Workload()
    pinned.cpu("bad", duration_seconds=1, target="qpu0")
    with pytest.raises(ValueError, match="Invalid cpu target"):
        Predictor().preview(pinned, hardware)


def test_public_preview_maps_target_to_native_attrs():
    work = Workload()
    work.qpu("quantum", qubits=5, shots=1000, target="qpu1")
    preview = Predictor().preview(work, Hardware(qpu=QPUProfile(qubits=8, shot_rate=10000, count=2)))
    assert preview["task_graph"]["nodes"][0]["attrs"]["resource_id"] == "qpu1"


def test_missing_runtime_is_explicit_and_preview_still_works():
    predictor = Predictor(native_runtime="/nonexistent/pivotq-runtime")
    assert not predictor.availability()["available"]
    work, hardware = hybrid()
    assert predictor.preview(work, hardware)
    with pytest.raises(UnavailableError, match="loader not found"):
        predictor.predict(work, hardware)


def test_timeout_is_structured_and_no_retries_occur(tmp_path):
    runner = PredictionRunner(timeout=0.1)
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 0.1)) as execute:
        with pytest.raises(TimeoutError):
            runner.run_task("input.yaml", tmp_path)
    assert execute.call_count == 1
    assert json.loads((tmp_path / "worker.response.json").read_text())["category"] == "timeout"


@pytest.mark.parametrize("response_text", ["{truncated", "[]", '{"ok": true}', '{"ok": true, "result": 4}'])
def test_malformed_worker_responses_preserve_logs_and_raise_structured_error(tmp_path, response_text):
    def malformed(command, **kwargs):
        Path(command[-1]).write_text(response_text)
        return subprocess.CompletedProcess(command, 0, "native stdout", "native stderr")
    with patch("subprocess.run", side_effect=malformed):
        with pytest.raises(ExecutionError, match="Invalid performance worker response"):
            PredictionRunner().run_task("unused.yaml", tmp_path)
    assert (tmp_path / "worker.stderr.log").read_text() == "native stderr"
    assert json.loads((tmp_path / "worker.response.json").read_text())["raw_response"] == response_text


def test_existing_results_are_never_overwritten(tmp_path):
    (tmp_path / "keep.txt").write_text("retained")
    with pytest.raises(ValueError, match="new or empty"):
        Predictor().predict(*hybrid(), output_dir=tmp_path)
    assert (tmp_path / "keep.txt").read_text() == "retained"


def test_packaged_binary_matches_delivered_original():
    from pivotq._internal.performance.common import ROOT, file_sha256
    source = Path(__file__).resolve().parents[3] / "perf-sim/lib/libfusion.so"
    assert file_sha256(ROOT / "lib/libfusion.so") == "151dca174a7a4596d03d4728cefbf23e74b55a8a4c3f0add5ad36706672264a9"
    if source.exists():
        assert file_sha256(source) == file_sha256(ROOT / "lib/libfusion.so")


def test_positive_submicrosecond_values_round_up_without_creating_traffic():
    work = Workload()
    work.cpu("tiny", duration_seconds=1e-9, input_bytes=100)
    work.qpu("q", qubits=1, shots=1)
    preview = Predictor().preview(work, Hardware(qpu=QPUProfile(qubits=1, shot_rate=10000, submit_latency_seconds=1e-9)))
    assert preview["task_graph"]["nodes"][0]["estimated_duration_us"] == 1
    assert preview["scenario"]["system"]["hardware"]["qpu"]["submit_latency_us"] == 1
    assert len(preview["task_graph"]["nodes"]) == 2


def test_library_precedence_preserves_deployment_configuration(tmp_path):
    library = tmp_path / "lib/libfusion.so"
    library.parent.mkdir()
    library.write_bytes(b"test asset")
    with patch.dict(os.environ, {"QPERFSIM_ROOT": str(tmp_path), "QPERFSIM_LIBRARY": "/explicit/env.so"}):
        assert PredictionRunner(library="/explicit/argument.so").library == Path("/explicit/argument.so")
        assert PredictionRunner().library == Path("/explicit/env.so")
        os.environ.pop("QPERFSIM_LIBRARY")
        assert PredictionRunner().library == library
