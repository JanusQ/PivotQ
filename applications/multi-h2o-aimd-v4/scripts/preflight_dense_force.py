"""Full 30-qubit acceptance and timing; save every completed phase immediately."""
import argparse,json,hashlib,resource,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import torch
from qiskit import QuantumCircuit
from qiskit.quantum_info import Pauli
from qiskit_aer import AerSimulator
from water10_v4.data import load_panel
from water10_v4.circuit import append_rotation
from water10_v4.statevector import settings
from water10_v4.dense_force.adjoint import DenseAdjoint,build_library
from water10_v4.dense_force.geometry import build_angles,ENCODING_VERSION
from water10_v4.dense_force.model import EnergyForceModel


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--threads',type=int,default=8);a=p.parse_args()
    a.output.mkdir(exist_ok=False,parents=True)
    spec=json.loads((ROOT/'models/final/best_model.json').read_text());spec['encoding_version']=ENCODING_VERSION;spec['seed']=916
    sid=json.loads((ROOT/'models/final/circuit_source/display_manifest.json').read_text())['sample_id']
    panel=load_panel([sid],include_forces=True);x=torch.tensor(panel['positions_angstrom'][0],dtype=torch.float64)
    library=build_library(a.output/'lib');model=EnergyForceModel(spec,library,a.threads)
    g,angles=build_angles(x,{k:model.quantum[j] for j,k in enumerate(model.keys)},spec['templates'],spec['normalizer'],spec['radii'])
    engine=DenseAdjoint(g,30,a.threads,library)
    report=dict(status='running',sample_id=sid,num_qubits=30,amplitudes=2**30,encoding_version=ENCODING_VERSION,threads=a.threads,phases=[])
    def save(phase,**extra):
        report.update(phase=phase,**extra);(a.output/'preflight.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
    save('dense_forward');t=time.monotonic();z=engine.forward(angles.detach().numpy());report['phases'].append(dict(name='dense_forward',seconds=time.monotonic()-t))
    save('qiskit_reference');qc=QuantumCircuit(30)
    for gate,angle in zip(g,angles.detach().numpy()):append_rotation(qc,gate['axis'],gate['qubits'],angle)
    for axis in ('X','Z'):
        for q in range(30):qc.save_expectation_value(Pauli(axis),[q],label=f'{axis}{q}')
    opts=settings();opts['max_parallel_threads']=a.threads
    result=AerSimulator(**opts).run(qc,shots=1).result()
    if not result.success:raise RuntimeError(str(result.status))
    ref=np.array([result.data(0)[f'{axis}{q}'] for axis in ('X','Z') for q in range(30)])
    error=float(np.max(abs(ref-z)));np.testing.assert_allclose(z,ref,atol=2e-10,rtol=0)
    save('energy_force',readout_reference_error=error);t=time.monotonic()
    energy,force=model.energy_forces(x,training=True)
    assert bool(torch.isfinite(force).all())
    totalforce=force.detach().sum(0).numpy();assert float(np.max(abs(totalforce)))<1e-8
    report['phases'].append(dict(name='energy_force',seconds=time.monotonic()-t))
    save('force_loss_backward',energy_ev=float(energy.detach()),force_rms=float(force.detach().square().mean().sqrt()),net_force=totalforce.tolist())
    loss=((energy-float(panel['energy_ev'][0]))/spec['normalizer']['energy_scale_ev'])**2+((force-torch.tensor(panel['forces_ev_per_angstrom'][0]))**2).mean()
    t=time.monotonic();loss.backward()
    assert all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in model.parameters())
    report['phases'].append(dict(name='force_loss_backward',seconds=time.monotonic()-t))
    save('completed',status='passed',quantum_gradient_norm=float(model.quantum.grad.norm()),peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,optimizer_updates=0)

if __name__=='__main__':main()
