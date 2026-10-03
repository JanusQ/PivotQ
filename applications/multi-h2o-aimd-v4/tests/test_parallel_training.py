import copy,tempfile,unittest
from pathlib import Path
import numpy as np
import pytest
from water10_v4.parallel_training import FastSimulator,save_state,load_state,update_joint,half_sample
from water10_v4.benchmark002 import corrected_templates,audit_angles
from water10_v4.revision import revised_templates,theta_for,build_block_circuit
from water10_v4.circuit import instances,parameter_keys
from water10_v4 import mlp_full

class ParallelTrainingContract(unittest.TestCase):
    def test_full_dataset_evaluation_uses_all_rows_and_correct_boundary(self):
        from unittest.mock import patch
        from water10_v4.parallel_training import evaluate_all
        net=mlp_full.initialize((60,4,1))
        for p in net['p'].values():p[:]=0
        state=dict(plan=dict(train=3500,validation=500,normalizer=dict(energy_scale_ev=1)),
                   theta={'q':.1},network=net,epoch=1,global_batch=55)
        seen=[]
        def forward(pool,indices,*args):
            seen.extend(indices);return np.zeros((len(indices),60)),None,[]
        with tempfile.TemporaryDirectory() as d:
            np.savez(Path(d)/'dataset.npz',y=np.r_[np.zeros(3500),np.ones(500)])
            with patch('water10_v4.parallel_training.collect',side_effect=forward):
                row=evaluate_all(None,state,Path(d))
        self.assertEqual(seen,list(range(4000)))
        self.assertEqual(row['train']['mse'],0)
        self.assertEqual(row['validation']['mse'],1)

    def sample(self):
        t=corrected_templates(revised_templates());theta=theta_for(t)
        f=dict(x1=np.full((10,3),.04),x2=np.full((45,10),-.03),x3=np.full((120,15),.02),
               w2=np.zeros(45),w3=np.zeros(120))
        f['w2'][0]=.5;f['w3'][0]=.3
        return t,theta,f

    def test_cached_circuit_exact_structure_and_shift(self):
        t,theta,f=self.sample();g=instances(t,f,theta);audit_angles(g,f)
        fast=FastSimulator();qc,positions=fast.compile(g)
        self.assertEqual(qc,build_block_circuit(g))
        for group in (0,61,len(g)-1):
            for sign in (-1,1):
                q=qc.copy();pos=positions[group];ins=q.data[pos];op=ins.operation.copy();op.params=[g[group]['angle']+sign*np.pi/2]
                q.data[pos]=ins.replace(operation=op)
                self.assertEqual(q,build_block_circuit(g,(group,sign*np.pi/2)))

    @pytest.mark.heavy
    def test_all_key_jacobian_finite_difference(self):
        t,theta,f=self.sample();keys=parameter_keys(t);fast=FastSimulator();g=instances(t,f,theta)
        z,jac=fast.compute(g,keys,True)
        for key in (keys[0],keys[8],keys[-1]):
            plus=theta.copy();minus=theta.copy();plus[key]+=1e-5;minus[key]-=1e-5
            zp,_=fast.compute(instances(t,f,plus),keys,False);zm,_=fast.compute(instances(t,f,minus),keys,False)
            np.testing.assert_allclose(jac[:,keys.index(key)],(zp-zm)/2e-5,atol=1e-8,rtol=1e-6)

    def test_resume_preserves_adam_rng_and_joint_update(self):
        rng=np.random.default_rng(2);keys=['a','b','c']
        state=dict(plan=dict(keys=keys,mlp_lr=.001,quantum_lr=.003),theta=dict.fromkeys(keys,.08),
          quantum_adam=dict(step=0,m=np.zeros(3),v=np.zeros(3)),network=mlp_full.initialize((4,5,1)),global_batch=0,
          rng_state=rng.bit_generator.state,epoch=1,next_batch=3,order=np.arange(8))
        z=rng.normal(size=(2,4));jac=rng.normal(size=(2,4,3));y=np.array([.2,.7])
        update_joint(state,z,jac,y)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'checkpoint.pkl';save_state(path,state);restored=load_state(path)
            self.assertEqual(restored['rng_state'],state['rng_state']);self.assertEqual(restored['next_batch'],3)
            a=update_joint(state,z,jac,y);b=update_joint(restored,z,jac,y)
            self.assertEqual(a,b);self.assertEqual(state['theta'],restored['theta'])
            for family in ('p','m','v'):
                for key in state['network'][family]:np.testing.assert_array_equal(state['network'][family][key],restored['network'][family][key])
            self.assertEqual(restored['quantum_adam']['step'],2)

    def test_half_selection_stratified_and_reproducible(self):
        panel=dict(category=np.array(['thermal']*2451+['distortion']*699+['boundary']*350))
        a,counts=half_sample(panel);b,_=half_sample(panel)
        np.testing.assert_array_equal(a,b);self.assertEqual(len(a),1750);self.assertEqual(len(set(a)),1750)
        self.assertEqual(sum(counts.values()),1750)

    @pytest.mark.heavy
    def test_chunked_chain_rule_matches_full_jacobian(self):
        from water10_v4 import parallel_training as pt
        from water10_v4.parallel_chunks import shift_task
        t,theta,f=self.sample();keys=parameter_keys(t);g=instances(t,f,theta)
        sim=FastSimulator();_,jac=sim.compute(g,keys,True);dz=np.linspace(-.3,.4,60)
        pt._WORK.clear();pt._WORK.update(meta=dict(templates=t,keys=keys),
            arrays={k:v[None] for k,v in f.items()},sim=FastSimulator())
        n=sum(x['parameter'] is not None for x in g)
        rows=[shift_task((0,theta,dz,start,min(start+24,n))) for start in range(0,n,24)]
        np.testing.assert_allclose(sum((r['gradient'] for r in rows)),dz@jac,atol=1e-12,rtol=1e-12)
        self.assertEqual(sum(r['calls'] for r in rows),2*n)

if __name__=='__main__':unittest.main()
