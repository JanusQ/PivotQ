"""One frozen-model dense forward plus force-label audit; no optimizer updates."""
import argparse
import hashlib
import json
import os
import resource
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import psutil
import qiskit
import qiskit_aer
from qiskit_aer import AerSimulator
from water10_v4.data import load_panel
from water10_v4.integration.fusion_framework.model import FrozenModel
from water10_v4.revision import build_block_circuit
from water10_v4.statevector import settings, require_memory


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--threads', type=int, default=8)
    a = p.parse_args()
    if a.threads < 1: raise ValueError('threads must be positive')
    a.output.mkdir(parents=True, exist_ok=False)
    path = ROOT/'models/final/best_model.json'
    model = FrozenModel(path, hashlib.sha256(path.read_bytes()).hexdigest())
    sid = json.loads((ROOT/'models/final/circuit_source/display_manifest.json').read_text())['sample_id']
    panel = load_panel([sid], include_forces=True)
    circuit = build_block_circuit(model.gates(panel['positions_angstrom'])[0])
    opts = settings(); opts['max_parallel_threads'] = a.threads
    report = dict(status='running', purpose='forward timing only; old frozen model; no training',
                  sample_id=sid, settings=opts, force_shape=list(panel['forces_ev_per_angstrom'].shape),
                  qiskit=qiskit.__version__, aer=qiskit_aer.__version__, python=sys.version,
                  memory_available_before=psutil.virtual_memory().available,
                  model_sha256=model.sha256, primitive_gates=len(circuit.data)-60,
                  optimizer_updates=0, test_labels_accessed=False)
    target = a.output/'preflight.json'
    target.write_text(json.dumps(report, indent=2))
    require_memory()
    proc = psutil.Process(); peak = [proc.memory_info().rss]; stop = threading.Event()
    def sample():
        while not stop.wait(.05): peak[0] = max(peak[0], proc.memory_info().rss)
    watcher = threading.Thread(target=sample, daemon=True); watcher.start()
    t0 = time.monotonic()
    try:
        result = AerSimulator(**opts).run(circuit, shots=1, seed_simulator=916).result()
        if not result.success: raise RuntimeError(str(result.status))
        z = [float(result.data(0)[f'{axis}{q}']) for axis in ('X','Z') for q in range(30)]
        report.update(status='completed', readouts=z, energy_ev=float(model.energy([z])[0]),
                      aer_metadata=result.results[0].metadata)
    except BaseException as error:
        report.update(status='failed', error=repr(error)); raise
    finally:
        stop.set(); watcher.join()
        report.update(wall_seconds=time.monotonic()-t0, peak_rss_bytes=max(peak[0],resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024))
        target.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, default=str), flush=True)

if __name__ == '__main__': main()
