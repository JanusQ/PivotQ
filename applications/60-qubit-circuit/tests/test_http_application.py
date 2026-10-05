"""Full application over localhost HTTP, with an exact TEST_ONLY device.

This verifies actual multipart transport/QASM/readout contracts, not real QPU.
"""
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

import h5py
import numpy as np
from qiskit import qasm3

from water20.hardware import HardwareProfile
from water20.model import Model, ROOT
from water20.potential import Potential
from water20.qpu import QPUClient
from water20.simulator import ExactSimulator, native_gates


def test_complete_water20_qasm_http_energy_path(tmp_path):
    model = Model()
    with h5py.File(ROOT/"dataset_water20_mbpol_v1/water20.h5") as h:
        positions = h["positions_angstrom"][0]
    expected = ExactSimulator().evaluate(model.gates(positions)[0])
    labels = tuple(f"q{500+i}" for i in range(60))
    profile = HardwareProfile("TEST_ONLY.complete-graph-reversed-layout", labels,
        tuple((i, j) for i in range(60) for j in range(i+1, 60)), tuple(reversed(range(60))), 100000, 1000000)
    requests_seen, features_seen, errors = [], [], []
    shots = 4096

    class Device(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_json(self, document, status=200):
            body = json.dumps(document).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.send_json(dict(status="ok", backend="circuit", limits=dict(max_circuits=32, max_file_bytes=1048576, max_qubits=60)))

        def do_POST(self):
            try:
                assert self.path == "/v1/jobs"
                body = self.rfile.read(int(self.headers["Content-Length"]))
                message = BytesParser(policy=default).parsebytes(b"Content-Type: "+self.headers["Content-Type"].encode()+b"\r\n\r\n"+body)
                parts = list(message.iter_parts())
                parameters = next(json.loads(p.get_payload(decode=True)) for p in parts if p.get_param("name", header="content-disposition") == "parameters")
                assert parameters == dict(reps=shots, measure_base="Z", use_DD=True, DD_type="X", parallel=True)
                files = [p for p in parts if p.get_param("name", header="content-disposition") == "files"]
                assert len(files) == 2
                rng = np.random.default_rng(20261004)
                rows, manifest = [], []
                for index, upload in enumerate(files):
                    circuit = qasm3.loads(upload.get_payload(decode=True).decode())
                    assert circuit.num_qubits == 60 and not circuit.num_clbits and not circuit.parameters
                    assert all(item.operation.name in ("rx", "rz", "cz") for item in circuit.data)
                    simulator = ExactSimulator()
                    physical_features = simulator.evaluate(native_gates(circuit))
                    features_seen.append(physical_features[60:][list(reversed(range(60)))])
                    # Exact joint sampling from each *actual* connected factor,
                    # rather than multiplying independent one-wire marginals.
                    bits = np.zeros((shots, 60), dtype=int)
                    for factor in simulator.factors:
                        probabilities = abs(factor.state)**2
                        probabilities /= probabilities.sum()
                        draws = rng.choice(len(probabilities), size=shots, p=probabilities)
                        for local, slot in enumerate(factor.qubits):
                            bits[:, slot] = (draws >> local) & 1
                    rows.extend([[s, index]+list(map(int, bits[s])) for s in range(shots)])
                    manifest.append(dict(index=index, name=upload.get_filename()))
                requests_seen.append(dict(files=len(files), parameters=parameters))
                self.send_json(dict(job_id="TEST_ONLY.http-60", status="succeeded", backend="circuit", error=None,
                    parameters=parameters, files=manifest,
                    result=dict(columns=["shots", "circuits"]+["result_"+q for q in labels], data=rows)))
            except Exception as exc:
                errors.append(exc)
                self.send_json(dict(error=type(exc).__name__), 500)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Device)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    sampler = QPUClient(profile, tmp_path/"journal", url=f"http://127.0.0.1:{server.server_port}")
    sampler.shots = shots
    try:
        potential = Potential(model, sampler)
        energy = potential.energy(positions)
        assert np.isfinite(energy)
        assert requests_seen == [dict(files=2, parameters=dict(reps=shots, measure_base="Z", use_DD=True, DD_type="X", parallel=True))]
        # Verify routed X/Z transforms before finite-shot sampling.
        np.testing.assert_allclose(np.concatenate(features_seen), expected, atol=1e-10)
        assert sampler.last_metadata["complete"]
        assert sampler.last_metadata["n_qubits"] == 60
        assert len(sampler.last_metadata["job_ids"]) == 2
        assert not errors
    finally:
        sampler.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
