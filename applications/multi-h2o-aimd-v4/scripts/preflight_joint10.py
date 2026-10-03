"""Actual-geometry precision and exact gradient checks before optimization."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from water10_v4 import parallel_training as pt
from water10_v4.circuit import instances
from water10_v4.backend import Backend
from water10_v4.revision import build_block_circuit
from water10_v4.parallel_chunks import full_gradient
if len(sys.argv) != 2: raise SystemExit('Usage: python '+sys.argv[0]+' <new-run-directory>')
def main():
    run=Path(sys.argv[1]);state=pt.load_state(run/'initial.pkl');plan=state['plan'];theta=state['theta'];keys=plan['keys']
    with np.load(run/'dataset.npz') as a:arrays={k:a[k] for k in a.files}
    counts=60+18*(arrays['w2']>0).sum(1)+24*(arrays['w3']>0).sum(1)
    idx=int(np.argsort(counts[:plan['train']],kind='stable')[plan['train']//2]);f={k:arrays[k][idx] for k in ('x1','x2','x3','w2','w3')}
    g=instances(plan['templates'],f,theta);fast=pt.FastSimulator();z,jac=fast.compute(g,keys,True)
    old=Backend(run/'reference_preflight.jsonl',max_calls=200,wall_seconds=600,builder=build_block_circuit)
    zold=old.evaluate(g,'reference_forward');np.testing.assert_allclose(z,zold,atol=1e-12,rtol=1e-12)
    selected=[keys[0],keys[8],keys[-1]];oldjac=old.jacobian(g,selected,'reference_selected_keys')
    error=float(np.max(abs(oldjac-jac[:,[keys.index(k) for k in selected]])));assert error<1e-10
    # Exercise the same distributed chain-rule path used by training.
    with pt.pool_for(run,1) as pool:
        dz=np.linspace(-.2,.4,60)[None];qgrad,rows=full_gradient(pool,[idx],theta,dz,counts)
    chunkerror=float(np.max(abs(qgrad-dz[0]@jac)));assert chunkerror<1e-10
    report=dict(passed=True,geometry=idx,backend=pt.settings(),fast_vs_reference_readout=float(np.max(abs(z-zold))),
        selected_key_jacobian_error=error,distributed_chain_rule_error=chunkerror,
        optimizer_updates=0)
    pt.atom_json(run/'numerical_preflight.json',report);print(json.dumps(report))

if __name__=='__main__':main()
