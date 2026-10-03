"""MD bookkeeping and restart tests use an analytic toy, never report science."""
import json
import numpy as np
import torch
from water10_v4.dense_force import aimd
from water10_v4.dense_force.training import json_save


def test_50fs_frame_count_reference_metrics_and_resume(tmp_path,monkeypatch):
    positions=np.zeros((10,3,3));positions[:,0,0]=np.arange(10)*3.2
    positions[:,1]=positions[:,0]+[.95,0,0];positions[:,2]=positions[:,0]+[-.24,.92,0]
    positions=positions.reshape(30,3);calls=[]
    class Toy:
        def __init__(self,*args):pass
        def load_state_dict(self,*args):pass
        def energy_forces(self,x):
            calls.append(1);d=x-torch.tensor(positions);return 5*(d*d).sum(),-10*d
    class Reference:
        def evaluate(self,x):d=x-positions;return float(5*np.sum(d*d)),-10*d
    torch.save(dict(spec={'train':1},model={}),tmp_path/'best.pt')
    json_save(tmp_path/'status.json',dict(stage='converged_validation_plateau'))
    np.savez(tmp_path/'data.npz',positions=np.stack([positions,positions]),sample_ids=np.array(['train','validation']))
    monkeypatch.setattr(aimd,'EnergyForceModel',Toy);monkeypatch.setattr(aimd,'Reference',Reference)
    monkeypatch.setattr(aimd,'build_library',lambda *_:None)
    aimd.run_md(tmp_path,threads=1)
    out=tmp_path/'aimd_50fs';metrics=json.loads((out/'metrics.json').read_text())
    assert metrics['completed_time_fs']==50 and metrics['frames']==501
    assert metrics['trajectory_force_rmse_ev_per_A']<1e-12
    assert metrics['trajectory_energy_rmse_ev']<1e-12
    assert len(list(out.glob('frame_*.npz')))==501
    before=len(calls);aimd.run_md(tmp_path,threads=1);assert len(calls)==before
