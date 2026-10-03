"""Probe original encoding at a translation-induced sign boundary, unchanged."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import resource
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from qiskit_aer import AerSimulator
from water10_v4.data import load_panel
from water10_v4.integration.fusion_framework.model import FrozenModel
from water10_v4.revision import build_block_circuit
from water10_v4.statevector import settings, require_memory


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--evaluate-energy', action='store_true')
    p.add_argument('--threads', type=int, default=8)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    path=ROOT/'models/final/best_model.json'
    model=FrozenModel(path,hashlib.sha256(path.read_bytes()).hexdigest())
    sid=json.loads((ROOT/'models/final/circuit_source/display_manifest.json').read_text())['sample_id']
    xyz=load_panel([sid])['positions_angstrom'][0]
    gates=model.gates(xyz[None])[0]
    # Select an active 2B x-coordinate feature on an actually interacting water.
    target=next(g for g in gates if g['stage']=='encoding' and g['body']==2 and g['feature']==0)
    mol=target['molecules'][0]
    center=xyz.copy();center[:,0]+=model.state['normalizer']['oxygen_mean'][0]-xyz[3*mol,0]
    report=dict(status='running',model_sha256=model.sha256,sample_id=sid,
                probe='rigid translation of all atoms along x; intramolecular and intermolecular distances unchanged',
                encoding_changed=False,quantum_parameters_changed=False,
                target_molecules=target['molecules'],target_weight=target['weight'],
                expected_angle_jump_rad=.2,rows=[],energy_evaluated=a.evaluate_energy)
    def save():
        (a.output/'continuity.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    save()
    opts=settings();opts['max_parallel_threads']=a.threads
    sim=AerSimulator(**opts) if a.evaluate_energy else None
    for eps in (1e-3,1e-5,1e-7):
        row=dict(epsilon_A=eps,sides=[])
        for sign in (-1,1):
            pos=center.copy();pos[:,0]+=sign*eps
            gg=model.gates(pos[None])[0]
            selected=next(g for g in gg if g['stage']=='encoding' and g['body']==2 and g['feature']==0 and g['molecules']==target['molecules'])
            side=dict(sign=sign,raw_angle_rad=selected['encoding_raw_angle'],angle_rad=selected['angle'])
            if sim is not None:
                require_memory();start=time.monotonic()
                result=sim.run(build_block_circuit(gg),shots=1,seed_simulator=916).result()
                if not result.success:raise RuntimeError(str(result.status))
                z=[[float(result.data(0)[f'{axis}{q}']) for axis in ('X','Z') for q in range(30)]]
                side.update(energy_ev=float(model.energy(z)[0]),seconds=time.monotonic()-start,
                            process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
            row['sides'].append(side)
        row['angle_jump_rad']=row['sides'][1]['angle_rad']-row['sides'][0]['angle_rad']
        if sim is not None:
            row['energy_jump_ev']=row['sides'][1]['energy_ev']-row['sides'][0]['energy_ev']
            row['apparent_total_force_x_ev_per_A']=-row['energy_jump_ev']/(2*eps)
        report['rows'].append(row);save();print(json.dumps(row),flush=True)
    report['status']='completed';save()

if __name__=='__main__':main()
