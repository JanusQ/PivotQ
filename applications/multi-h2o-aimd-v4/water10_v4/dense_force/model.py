"""Single energy head; forces are negative coordinate derivatives of that head."""
import hashlib
import json
from pathlib import Path

import torch
from .geometry import build_angles,ENCODING_VERSION
from .adjoint import DenseAdjoint
from .autograd import readouts
from ..circuit import parameter_keys


class EnergyForceModel(torch.nn.Module):
    @classmethod
    def from_json(cls,path,library,threads=8,expected_sha256=None):
        """Load the complete exported checkpoint without pickle or random weights."""
        raw=Path(path).read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None and digest!=expected_sha256:
            raise ValueError('Model SHA256 mismatch')
        spec=json.loads(raw)
        if not isinstance(spec,dict) or not all(k in spec for k in
                ('encoding_version','templates','theta','normalizer','radii','network')):
            raise ValueError('Expected a complete energy-force JSON model')
        if spec['encoding_version']!=ENCODING_VERSION:
            raise ValueError('Unsupported encoding; use the experimental continuous-encoding model')
        if isinstance(threads,bool) or not isinstance(threads,int) or threads<1:
            raise ValueError('threads must be a positive integer')
        keys=parameter_keys(spec['templates'])
        if len(keys)!=48 or set(keys)!=set(spec['theta']):
            raise ValueError('Expected exactly 48 matching shared quantum parameters')
        theta=torch.as_tensor([spec['theta'][k] for k in keys],dtype=torch.float64)
        if theta.shape!=(48,) or not bool(torch.isfinite(theta).all()):
            raise ValueError('Invalid quantum parameters')
        network=spec['network'];widths=[60,64,32,1]
        if network.get('widths')!=widths or set(network.get('p',{}))!={
                f'{kind}{j}' for kind in ('W','b') for j in range(3)}:
            raise ValueError('Expected complete 60-64-32-1 tanh network parameters')
        weights={}
        for j,(a,b) in enumerate(zip(widths,widths[1:])):
            for name,shape in ((f'W{j}',(a,b)),(f'b{j}',(b,))):
                value=torch.as_tensor(network['p'][name],dtype=torch.float64)
                if value.shape!=shape or not bool(torch.isfinite(value).all()):
                    raise ValueError(f'Invalid classical parameter {name}; expected {shape}')
                weights[name]=value
        normalizer=spec['normalizer']
        for name,shape,positive in (
                ('energy_mean_ev',(),False),('energy_scale_ev',(),True),
                ('oh_mean',(),False),('oh_scale',(),True),
                ('oxygen_mean',(3,),False),('oxygen_scale',(3,),True)):
            value=torch.as_tensor(normalizer[name],dtype=torch.float64)
            if value.shape!=shape or not bool(torch.isfinite(value).all()) \
                    or (positive and not bool((value>0).all())):
                raise ValueError(f'Invalid normalizer {name}')
        for name in ('pair_radii','triple_radii'):
            value=torch.as_tensor(spec['radii'][name],dtype=torch.float64)
            if value.shape!=(2,) or not bool(torch.isfinite(value).all()) \
                    or not bool(0<value[0]<value[1]):
                raise ValueError(f'Invalid {name}')
        model=cls(spec,library,threads)
        with torch.no_grad():
            for name,value in weights.items():
                model.classical[name].copy_(value)
        model.model_sha256=digest
        model.eval()
        return model

    def __init__(self,spec,library,threads=8):
        super().__init__();self.spec=spec;self.library=library;self.threads=threads
        self.keys=parameter_keys(spec['templates'])
        if len(self.keys)!=48:raise ValueError('Expected 48 shared quantum parameters')
        if spec['encoding_version']!=ENCODING_VERSION:raise ValueError('Unsupported encoding')
        self.quantum=torch.nn.Parameter(torch.tensor([spec['theta'][k] for k in self.keys],dtype=torch.float64))
        widths=[60,64,32,1];self.classical=torch.nn.ParameterDict()
        generator=torch.Generator().manual_seed(spec.get('seed',916))
        for j,(a,b) in enumerate(zip(widths,widths[1:])):
            w=torch.randn(a,b,generator=generator,dtype=torch.float64)*(2/(a+b))**.5
            self.classical[f'W{j}']=torch.nn.Parameter(w)
            self.classical[f'b{j}']=torch.nn.Parameter(torch.zeros(b,dtype=torch.float64))

    def energy(self,positions):
        theta={k:self.quantum[j] for j,k in enumerate(self.keys)}
        gates,angles=build_angles(positions,theta,self.spec['templates'],self.spec['normalizer'],self.spec['radii'])
        engine=DenseAdjoint(gates,30,self.threads,self.library)
        z=readouts(angles,engine)
        for j in range(3):
            z=z@self.classical[f'W{j}']+self.classical[f'b{j}']
            if j<2:z=torch.tanh(z)
        norm=self.spec['normalizer']
        return norm['energy_mean_ev']+norm['energy_scale_ev']*z[0]

    def energy_forces(self,positions,training=False):
        x=positions.detach().clone().requires_grad_(True)
        energy=self.energy(x)
        force=-torch.autograd.grad(energy,x,create_graph=training)[0]
        return energy,force

    def export(self):
        out=dict(self.spec)
        out.update(theta={k:float(self.quantum[j].detach()) for j,k in enumerate(self.keys)},
                   network=dict(widths=[60,64,32,1],p={k:v.detach().tolist() for k,v in self.classical.items()}),
                   backend=dict(method='dense_statevector_adjoint',num_qubits=30,precision='complex128',truncation=False))
        return out
