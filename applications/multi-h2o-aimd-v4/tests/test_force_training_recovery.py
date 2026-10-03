"""Exercise optimizer/checkpoint orchestration with cheap analytic stand-ins."""
from concurrent.futures import Future
from pathlib import Path
import numpy as np
import torch
from water10_v4.dense_force import training as tr
from water10_v4.dense_force.geometry import ENCODING_VERSION


class Toy(torch.nn.Module):
    def __init__(self,*args):
        super().__init__();self.quantum=torch.nn.Parameter(torch.zeros(1,dtype=torch.float64))
        self.classical=torch.nn.ParameterDict({'bias':torch.nn.Parameter(torch.zeros(1,dtype=torch.float64))})
    def export(self):return {'theta':self.quantum.detach().tolist()}


def test_resume_partial_batch_without_repeating_completed_gradient(tmp_path,monkeypatch):
    spec=dict(seed=916,train=3,validation=2,encoding_version=ENCODING_VERSION)
    model=Toy();(tmp_path/'lib').mkdir();(tmp_path/'lib/test.so').touch()
    tr.json_save(tmp_path/'acceptance.json',dict(status='passed',peak_rss_bytes=1))
    first=int(np.random.default_rng(917).permutation(3)[0]);second=int(np.random.default_rng(917).permutation(3)[1])
    def row(index,training):
        return dict(index=index,energy_mse=1.,force_mse=2.,loss=3.,seconds=.01,peak_rss_bytes=1,
                    gradients={k:torch.ones_like(p) for k,p in model.named_parameters()} if training else {})
    state=dict(spec=spec,model=model.state_dict(),optimizer=None,epoch=1,position=0,updates=0,history=[],
               best_score=None,bad_epochs=0,pending={str(first):row(first,True)},batch_indices=[first,second],train_sums=[0.,0.],workers=1)
    tr.checkpoint(tmp_path/'latest.pt',state)
    calls=[]
    class Pool:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def submit(self,fn,index,weights,training):
            calls.append((index,training));f=Future();f.set_result(row(index,training));return f
    monkeypatch.setattr(tr,'EnergyForceModel',Toy);monkeypatch.setattr(tr,'ProcessPoolExecutor',Pool)
    monkeypatch.setattr(tr,'resource_cap',lambda *_:2);monkeypatch.setattr(tr,'_STOP',False)
    monkeypatch.setattr(tr.signal,'signal',lambda *_:None)
    tr.train(tmp_path,threads=1,batch_size=2,patience=1)
    latest=torch.load(tmp_path/'latest.pt',weights_only=False)
    assert latest['epoch']==3 and latest['position']==0 and not latest['pending']
    assert len(latest['history'])==2 and latest['updates']>=3
    assert sum(i==first and training for i,training in calls)==1 # second epoch only
    assert (tmp_path/'epoch_0001.pt').exists() and (tmp_path/'epoch_0002.pt').exists()
    assert (tmp_path/'best.pt').exists()
    assert not torch.equal(latest['model']['quantum'],state['model']['quantum'])
