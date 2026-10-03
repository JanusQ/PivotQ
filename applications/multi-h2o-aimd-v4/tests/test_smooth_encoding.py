"""Smooth encoding tests do not invoke any 30-qubit simulation."""
import json
from pathlib import Path
import numpy as np
import torch
from water10_v4.data import load_panel
from water10_v4.dense_force.geometry import build_angles

ROOT=Path(__file__).resolve().parents[1]


def inputs():
    spec=json.loads((ROOT/'models/final/best_model.json').read_text())
    sid=json.loads((ROOT/'models/final/circuit_source/display_manifest.json').read_text())['sample_id']
    x=torch.tensor(load_panel([sid])['positions_angstrom'][0],dtype=torch.float64,requires_grad=True)
    theta={k:torch.tensor(v,dtype=torch.float64,requires_grad=True) for k,v in spec['theta'].items()}
    def angles(x):return build_angles(x,theta,spec['templates'],spec['normalizer'],spec['radii'])
    return x,theta,angles


def test_translation_invariance_and_zero_total_force_chain():
    x,theta,angles=inputs();g,a=angles(x);gg,b=angles(x+x.new_tensor([7.,-3.,2.]))
    assert [(v['axis'],v['qubits']) for v in g]==[(v['axis'],v['qubits']) for v in gg]
    torch.testing.assert_close(a,b,atol=1e-12,rtol=0)
    weights=torch.linspace(-.2,.3,len(a),dtype=torch.float64)
    force=-torch.autograd.grad(a@weights,x,create_graph=True)[0]
    torch.testing.assert_close(force.sum(0),torch.zeros(3,dtype=torch.float64),atol=1e-12,rtol=0)
    assert len(theta)==48


def test_encoding_coordinate_and_mixed_derivatives():
    x,theta,angles=inputs();g,a=angles(x)
    weights=torch.linspace(-.2,.3,len(a),dtype=torch.float64)
    energy=torch.sin(a)@weights
    force=-torch.autograd.grad(energy,x,create_graph=True)[0]
    loss=(force**2).mean();key=next(k for k in theta if k.startswith('b2_'))
    analytic=torch.autograd.grad(loss,theta[key],allow_unused=True)[0]
    # Independently verify coordinate derivative; all active gates remain identical.
    d=torch.zeros_like(x);d[0,0]=1e-6
    plus=angles(x+d)[1];minus=angles(x-d)[1]
    estimate=-((torch.sin(plus)@weights)-(torch.sin(minus)@weights))/(2e-6)
    torch.testing.assert_close(force[0,0],estimate,atol=1e-7,rtol=1e-6)
    assert analytic is not None and torch.isfinite(analytic)


def test_fusion_loader_dispatches_new_encoding(tmp_path):
    import hashlib
    from water10_v4.dense_force.geometry import ENCODING_VERSION
    from water10_v4.integration.fusion_framework.model import FrozenModel
    x,_,angles=inputs();spec=json.loads((ROOT/'models/final/best_model.json').read_text())
    spec['encoding_version']=ENCODING_VERSION
    path=tmp_path/'model.json';path.write_text(json.dumps(spec))
    model=FrozenModel(path,hashlib.sha256(path.read_bytes()).hexdigest())
    gates=model.gates(x.detach().numpy()[None])[0];expected,a=angles(x)
    np.testing.assert_allclose([g['angle'] for g in gates],a.detach().numpy(),atol=1e-14,rtol=0)
    assert [g['axis'] for g in gates]==[g['axis'] for g in expected]
