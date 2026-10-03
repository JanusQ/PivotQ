"""Frozen-checkpoint energy inference in eV, on the same single 30q circuit."""
import json
from pathlib import Path
from .data import features,encode_features
from .circuit import instances
from .backend import Backend
from .experiment import load_net,predict

class Water10V4:
    def __init__(self,checkpoint,ledger_path,backend=None):
        self.path=Path(checkpoint);self.state=json.loads(self.path.read_text())
        radii_path=next(p/'radii.json' for p in (self.path.parent,self.path.parent.parent) if (p/'radii.json').exists())
        self.radii=json.loads(radii_path.read_text())
        self.net=load_net(self.state['network'])
        self.backend=backend or Backend(ledger_path)
    def energy(self,positions_angstrom):
        f=encode_features(features(positions_angstrom,**self.radii),self.state['normalizer'])
        gates=instances(self.state['templates'],f,self.state['theta'])
        z=self.backend.evaluate(gates,'energy_inference')
        n=self.state['normalizer']
        return float(n['energy_mean_ev']+n['energy_scale_ev']*predict(self.net,z[None])[0])
