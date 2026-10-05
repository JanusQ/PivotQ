from copy import deepcopy
from dataclasses import replace
import json

import httpx
import numpy as np
import pytest
from qiskit import qasm3

from water20.hardware import CircuitRequest, HardwareProfile, HardwareNotReady, prepare
from water20.model import ROOT
from water20.protocol import decode
from water20.qpu import QPUClient, ExecutionUnknown


def fake_profile():
    """Test topology only; never stored as the application's physical profile."""
    return HardwareProfile("TEST_ONLY.synthetic-line", tuple(f"q{100+q}" for q in range(60)),
                           tuple((i, i+1) for i in range(59)), tuple(range(60)), 100000, 1000000)


def requests():
    return tuple(CircuitRequest(f"test.{basis}", basis, f"test-{basis}.qasm",
        'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[60] q;\nrx(0.3) q[0];\n',
        tuple(f"q{100+q}" for q in range(60)), "TEST_ONLY.synthetic-line", 1, 1) for basis in ("X", "Z"))


def response(items=None, shots=4):
    items = items or requests()
    # Scramble columns and file order to exercise explicit associations.
    columns = ["circuits"]+[f"result_q{100+q}" for q in reversed(range(60))]+["shots"]
    rows = []
    for circuit in range(len(items)):
        for shot in range(shots):
            bits = [0]*60
            bits[0] = bits[59] = shot % 2  # Same-shot joint correlation.
            rows.append([circuit]+list(reversed(bits))+[shot])
    return dict(job_id="job-test", status="succeeded", backend="circuit", error=None,
                parameters=dict(reps=shots, measure_base="Z"),
                files=[dict(index=i, name=r.filename) for i, r in reversed(list(enumerate(items)))],
                result=dict(columns=columns, data=rows))


def test_observed_counts_joint_correlation_bit_order_and_uncertainty():
    results = decode(response(), requests(), 4, "job-test")
    assert [r["basis"] for r in results] == ["X", "Z"]
    for result in results:
        assert len(result["counts"]) == 2
        assert set(result["counts"]) == {"0"*60, "1"+"0"*58+"1"}
        assert result["actual_shots"] == 4 and result["complete"]
        assert result["expectations"][0] == result["expectations"][59] == 0
        assert result["expectations"][1:59] == [1]*58
        assert len(result["standard_error"]) == 60


@pytest.mark.parametrize("fault", ["duplicate_shot", "missing_shot", "nonbinary", "fractional_shot",
    "wrong_column", "duplicate_column", "missing_column", "wrong_job", "ideal", "missing_file",
    "duplicate_file", "unknown_file", "wrong_shots", "wrong_measure_base", "failed", "backend_mock"])
def test_reject_invalid_or_partial_device_records(fault):
    record = response()
    table = record["result"]
    if fault == "duplicate_shot": table["data"].append(table["data"][0])
    elif fault == "missing_shot": table["data"].pop()
    elif fault == "nonbinary": table["data"][0][1] = 2
    elif fault == "fractional_shot": table["data"][0][-1] = .5
    elif fault == "wrong_column": table["columns"][1] = "result_q999"
    elif fault == "duplicate_column": table["columns"][1] = table["columns"][2]
    elif fault == "missing_column": table["columns"].pop()
    elif fault == "wrong_job": record["job_id"] = "other"
    elif fault == "ideal": record["result"] = {"ideal_prob_P000": 1}
    elif fault == "missing_file": record["files"].pop()
    elif fault == "duplicate_file": record["files"][1] = dict(record["files"][0])
    elif fault == "unknown_file": record["files"][0]["name"] = "other.qasm"
    elif fault == "wrong_shots": record["parameters"]["reps"] = 3
    elif fault == "wrong_measure_base": record["parameters"]["measure_base"] = "X"
    elif fault == "failed": record["status"] = "failed"
    elif fault == "backend_mock": record["backend"] = "mock"
    with pytest.raises(ValueError):
        decode(record, requests(), 4, "job-test")


def test_logical_physical_reordering_is_explicit():
    items = list(requests())
    order = list(items[0].logical_readout_labels)
    order[0], order[7] = order[7], order[0]
    items[0] = replace(items[0], logical_readout_labels=tuple(order))
    results = decode(response(items), items, 4, "job-test")
    assert results[0]["expectations"][0] == 1
    assert results[0]["expectations"][7] == 0
    assert results[1]["expectations"][0] == 0


def test_actual_native_topology_routing_and_final_layout():
    profile = fake_profile()
    gates = [dict(axis="Y", qubits=[0], angle=.4), dict(axis="XZ", qubits=[0, 59], angle=.7)]
    prepared = prepare(gates, profile, "routing-test")
    assert [r.basis for r in prepared] == ["X", "Z"]
    for request in prepared:
        circuit = qasm3.loads(request.qasm)
        assert circuit.num_qubits == 60 and not circuit.num_clbits and not circuit.parameters
        assert set(request.logical_readout_labels) == set(profile.physical_labels)
        for item in circuit.data:
            assert item.operation.name in ("rx", "rz", "cz")
            if item.operation.name == "cz":
                a, b = [circuit.find_bit(q).index for q in item.qubits]
                assert abs(a-b) == 1
    with pytest.raises(HardwareNotReady):
        prepare(gates, replace(profile, max_gates=1), "over-budget")


def test_unconfirmed_actual_profile_cannot_submit():
    with pytest.raises(HardwareNotReady):
        HardwareProfile.load(ROOT/"configs/hardware_profile.template.json")


def test_http_multipart_journal_reuse_and_no_duplicate_posts(tmp_path):
    counts = dict(post=0, poll=0)
    record = response()
    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json=dict(status="ok", backend="circuit", limits=dict(max_circuits=32, max_file_bytes=1048576)))
        if request.method == "POST":
            counts["post"] += 1
            content = request.content
            assert content.count(b'name="files"') == 2
            assert b'name="parameters"' in content
            for field in (b'"reps": 4', b'"measure_base": "Z"', b'"use_DD": true', b'"DD_type": "X"', b'"parallel": true'):
                assert field in content
            return httpx.Response(200, json=dict(job_id="job-test", status="queued"))
        counts["poll"] += 1
        return httpx.Response(200, json=record)
    client = httpx.Client(base_url="http://TEST_ONLY.invalid", transport=httpx.MockTransport(handler))
    adapter = QPUClient(fake_profile(), tmp_path, client=client)
    first = adapter.execute(requests(), 4, "test-request")
    second = adapter.execute(requests(), 4, "test-request")
    assert first == second and counts == dict(post=1, poll=1)
    with pytest.raises(ExecutionUnknown):
        adapter.execute(requests(), 5, "test-request")
    adapter.close()


def test_unknown_post_outcome_never_resubmits(tmp_path):
    calls = []
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=dict(status="ok", backend="circuit"))
        calls.append("POST")
        raise httpx.ReadTimeout("TEST_ONLY uncertain outcome", request=request)
    adapter = QPUClient(fake_profile(), tmp_path,
        client=httpx.Client(base_url="http://TEST_ONLY.invalid", transport=httpx.MockTransport(handler)))
    for _ in range(2):
        with pytest.raises(ExecutionUnknown):
            adapter.execute(requests(), 4, "uncertain")
    assert calls == ["POST"]
    adapter.close()


@pytest.mark.parametrize("state", ["failed", "interrupted", "mystery"])
def test_terminal_or_unknown_states_do_not_retry(tmp_path, state):
    calls = []
    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json=dict(status="ok", backend="circuit"))
        calls.append(request.method)
        return httpx.Response(200, json=dict(job_id="job-test", status=state, error={"code": "TEST_ONLY"}))
    adapter = QPUClient(fake_profile(), tmp_path,
        client=httpx.Client(base_url="http://TEST_ONLY.invalid", transport=httpx.MockTransport(handler)))
    with pytest.raises((RuntimeError, ExecutionUnknown)):
        adapter.execute(requests(), 4, "status-test")
    assert calls == ["POST"]
    adapter.close()


def test_max_file_size_checked_before_any_post(tmp_path):
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json=dict(status="ok", backend="circuit", limits=dict(max_file_bytes=4)))
    adapter = QPUClient(fake_profile(), tmp_path,
        client=httpx.Client(base_url="http://TEST_ONLY.invalid", transport=httpx.MockTransport(handler)))
    with pytest.raises(HardwareNotReady):
        adapter.execute(requests(), 4, "oversized")
    assert calls == ["GET"]
    adapter.close()
