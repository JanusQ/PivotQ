"""Resumable 50 fs NVE validation with same-geometry MB-pol references."""
import argparse,hashlib,json,os
from pathlib import Path
import numpy as np
import torch
from ase import Atoms,units
from ase.calculators.calculator import Calculator,all_changes
from ase.md.verlet import VelocityVerlet
from ase.md.velocitydistribution import MaxwellBoltzmannDistribution,Stationary,ZeroRotation
from ase.io import write
from .model import EnergyForceModel
from .adjoint import build_library
from .reference import Reference
from .training import json_save


class EnergyCalculator(Calculator):
    implemented_properties=['energy','forces']
    def __init__(self,model):super().__init__();self.model=model
    def calculate(self,atoms=None,properties=('energy','forces'),system_changes=all_changes):
        super().calculate(atoms,properties,system_changes)
        e,f=self.model.energy_forces(torch.tensor(atoms.positions,dtype=torch.float64))
        self.results=dict(energy=float(e.detach()),forces=f.detach().numpy())


def run_md(run,threads=8):
    run=Path(run);status=json.loads((run/'status.json').read_text())
    if status['stage']!='converged_validation_plateau':raise RuntimeError('Training has not reached its validation stopping criterion')
    out=run/'aimd_50fs';out.mkdir(exist_ok=True)
    path=run/'best.pt';digest=hashlib.sha256(path.read_bytes()).hexdigest()
    state=torch.load(path,weights_only=False,map_location='cpu')
    model=EnergyForceModel(state['spec'],build_library(run/'lib'),threads);model.load_state_dict(state['model'])
    reference=Reference();data=np.load(run/'data.npz');index=state['spec']['train'];seed=916
    metadata=dict(model_sha256=digest,sample_id=str(data['sample_ids'][index]),split='validation',
                  dt_fs=.1,target_steps=500,target_time_fs=50.,initial_temperature_K=300.,seed=seed,
                  ensemble='NVE',forces='negative analytic energy gradient',reference='MB-pol at each predicted geometry',
                  note='short-time validation only; not proof of long-time dynamics accuracy')
    if (out/'metadata.json').exists():
        if json.loads((out/'metadata.json').read_text())!=metadata:raise ValueError('MD resume metadata mismatch')
    else:json_save(out/'metadata.json',metadata)
    files=sorted(out.glob('frame_*.npz'));start=0
    atoms=Atoms(numbers=[8,1,1]*10,positions=data['positions'][index],pbc=False)
    if files:
        last=np.load(files[-1]);start=int(last['step']);atoms.positions=last['positions'];atoms.set_velocities(last['velocities'])
    else:
        MaxwellBoltzmannDistribution(atoms,temperature_K=300.,rng=np.random.default_rng(seed))
        Stationary(atoms);ZeroRotation(atoms)
    atoms.calc=EnergyCalculator(model)
    def save_frame(step):
        e=atoms.get_potential_energy();force=atoms.get_forces();kinetic=atoms.get_kinetic_energy()
        ref_e,ref_f=reference.evaluate(atoms.positions)
        oxy=atoms.positions[::3];distance=np.linalg.norm(oxy[:,None]-oxy[None,:],axis=-1);np.fill_diagonal(distance,np.inf)
        xyz=atoms.positions.reshape(10,3,3);b=xyz[:,1:]-xyz[:,0,None,:];oh=np.linalg.norm(b,axis=-1)
        angle=np.degrees(np.arccos(np.clip((b[:,0]*b[:,1]).sum(1)/(oh[:,0]*oh[:,1]),-1,1)))
        values=dict(step=step,time_fs=step*.1,positions=atoms.positions,velocities=atoms.get_velocities(),forces=force,
                    potential_ev=e,kinetic_ev=kinetic,total_ev=e+kinetic,temperature_K=atoms.get_temperature(),
                    reference_energy_ev=ref_e,reference_forces=ref_f,oh_lengths_A=oh,hoh_angles_deg=angle,
                    min_oo_A=float(distance.min()),net_force=force.sum(0),torque=np.cross(atoms.positions-atoms.get_center_of_mass(),force).sum(0))
        target=out/f'frame_{step:06d}.npz';tmp=target.with_suffix('.tmp')
        with tmp.open('wb') as f:np.savez(f,**values);f.flush();os.fsync(f.fileno())
        tmp.replace(target);json_save(out/'status.json',dict(status='running',completed_steps=step,time_fs=step*.1))
        if not np.isfinite(e+kinetic) or not np.isfinite(force).all():raise FloatingPointError('Nonfinite MD state')
        if oh.min()<.5 or oh.max()>2 or distance.min()<1:
            json_save(out/'status.json',dict(status='unstable_geometry',completed_steps=step,time_fs=step*.1))
            raise RuntimeError('MD geometry left supported water domain; preserve partial trajectory')
    if not files:save_frame(0)
    dynamics=VelocityVerlet(atoms,timestep=.1*units.fs)
    for step in range(start+1,501):
        if (run/'STOP').exists():return
        dynamics.run(1);save_frame(step)
    frames=[np.load(p) for p in sorted(out.glob('frame_*.npz'))]
    assert len(frames)==501
    trajectory=[]
    for row in frames:
        a=Atoms(numbers=atoms.numbers,positions=row['positions']);a.set_velocities(row['velocities']);trajectory.append(a)
    write(out/'trajectory.extxyz',trajectory)
    total=np.array([float(r['total_ev']) for r in frames]);t=np.array([float(r['time_fs']) for r in frames])
    de=np.array([float(r['potential_ev']-r['reference_energy_ev']) for r in frames])
    df=np.array([r['forces']-r['reference_forces'] for r in frames])
    metrics=dict(completed_time_fs=50.,frames=501,max_abs_total_energy_drift_ev=float(np.max(abs(total-total[0]))),
                 drift_slope_ev_per_fs=float(np.polyfit(t,total-total[0],1)[0]),
                 trajectory_energy_rmse_ev=float(np.sqrt(np.mean(de**2))),trajectory_force_rmse_ev_per_A=float(np.sqrt(np.mean(df**2))),
                 trajectory_force_mae_ev_per_A=float(np.mean(abs(df))),scope='one 50 fs validation trajectory')
    json_save(out/'metrics.json',metrics);json_save(out/'status.json',dict(status='completed',**metrics))


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--threads',type=int,default=8);a=p.parse_args();run_md(a.run,a.threads)
if __name__=='__main__':main()
