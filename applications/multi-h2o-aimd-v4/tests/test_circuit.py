"""Scientific contract tests: exact small-system references, never training FD."""
import json, unittest
import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator, Pauli, Statevector
from water10_v4.circuit import *
from water10_v4.data import ROOT, load_panel, features, fit_normalizer, encode_features
from water10_v4.experiment import network, backward, predict

class CircuitContract(unittest.TestCase):
    def test_pauli_endian_and_rotation_angle(self):
        for axis in ['X','Y','Z','XX','XY','XZ','YX','YY','YZ','ZX','ZY','ZZ','XYZ','XZZ','YZZ','YXZ']:
            n=len(axis);qc=QuantumCircuit(n);angle=.371
            append_rotation(qc,axis,list(range(n)),angle)
            p=Pauli(axis[::-1]).to_matrix()
            expected=np.cos(angle/2)*np.eye(2**n)-1j*np.sin(angle/2)*p
            np.testing.assert_allclose(Operator(qc).data,expected,atol=2e-14)

    def test_whole_modules_close_to_identity(self):
        t=complete_templates(seed_templates())
        for stage in t:
            for b in (2,3):
                qc=QuantumCircuit(3*b)
                for block in t[stage][str(b)]:
                    for g in block:append_rotation(qc,g['axis'],g['sites'],0.)
                np.testing.assert_allclose(Operator(qc).data,np.eye(2**(3*b)),atol=3e-14)

    def test_shared_parameter_shift_chain(self):
        weights=[.3,-.72,.8];theta=.274
        def read(theta,shift=None):
            qc=QuantumCircuit(3);qc.h(0);qc.ry(.4,1);qc.rx(.5,2)
            for i,(axis,sites) in enumerate([('XZ',[0,1]),('Y',[2]),('YZZ',[1,0,2])]):
                append_rotation(qc,axis,sites,weights[i]*theta+(shift[1] if shift and shift[0]==i else 0))
            sv=Statevector(qc)
            return np.array([sv.expectation_value(Pauli(a)).real for a in ('IIX','IZI','ZII')])
        jac=sum(w*.5*(read(theta,(i,np.pi/2))-read(theta,(i,-np.pi/2))) for i,w in enumerate(weights))
        fd=(read(theta+1e-6)-read(theta-1e-6))/2e-6
        np.testing.assert_allclose(jac,fd,atol=3e-10)
        # Nonlinear head: differentiate readout, then head; no loss-shift shortcut.
        z=read(theta); chain=2*(np.tanh(z).sum()-.2)*(1-np.tanh(z)**2)@jac
        loss=lambda th:(np.tanh(read(th)).sum()-.2)**2
        self.assertLess(abs(chain-(loss(theta+1e-5)-loss(theta-1e-5))/2e-5),1e-9)

    def test_semantics_mapping_and_shared_dictionary(self):
        ids=json.loads((ROOT/'data_v4/panels.json').read_text())['pilot_train_32']
        p=load_panel(ids);normalizer=fit_normalizer(p);ff=encode_features(features(p['positions_angstrom']),normalizer)
        t=complete_templates(seed_templates());keys=parameter_keys(t);theta={k:.1 for k in keys}
        self.assertEqual([len(t['encoding'][str(b)]) for b in (1,2,3)],[3,10,15])
        for i in (0,7,18):
            f={k:ff[k][i] for k in ('x1','x2','x3','w2','w3')};gates=instances(t,f,theta)
            for g in gates:
                self.assertEqual(g['qubits'],[g['scope'][q] for q in g['local_qubits']])
                self.assertTrue(set(g['qubits'])<=set(g['scope']))
                self.assertTrue(np.isfinite(g['angle']))
                self.assertEqual(g['parameter'] is None,g['stage']=='encoding')
            semantic=lambda s:{(g['body'],g['combination_index'],g['feature']) for g in gates if g['stage']==s}
            self.assertEqual(semantic('encoding'),semantic('trainable'))
            self.assertEqual(keys,parameter_keys(t))
        y=(p['energy_ev']-normalizer['energy_mean_ev'])/normalizer['energy_scale_ev']
        np.testing.assert_allclose(y*normalizer['energy_scale_ev']+normalizer['energy_mean_ev'],p['energy_ev'])

    def test_mlp_analytic_gradient(self):
        net=network();z=np.random.default_rng(2).normal(size=(2,60));y=np.array([.1,.9])
        _,gr,dz=backward(net,z,y);h=1e-6
        zz=z.copy();zz[0,7]+=h;plus=np.mean((predict(net,zz)-y)**2)
        zz[0,7]-=2*h;minus=np.mean((predict(net,zz)-y)**2)
        self.assertAlmostEqual(dz[0,7],(plus-minus)/2/h,places=8)
        net['p']['W'][5,3]+=h;plus=np.mean((predict(net,z)-y)**2)
        net['p']['W'][5,3]-=2*h;minus=np.mean((predict(net,z)-y)**2)
        self.assertAlmostEqual(gr['W'][5,3],(plus-minus)/2/h,places=8)

    def test_interaction_rank_bound_and_cz_simplification(self):
        t=complete_templates(edit_template(seed_templates(),active_pool()[9]),bus_only=True)
        for stage in t:
            for b in (1,2,3):
                for block in t[stage][str(b)]:
                    for g in block:
                        if len(g['axis'])>1:self.assertTrue(b>1 and all(q%3==0 for q in g['sites']))
                    for a,c in zip(block,block[1:]):
                        self.assertFalse(a['axis']==c['axis'] and a['sites']==c['sites'])
        gates=[dict(axis='YZ',qubits=[0,3],angle=.2),dict(axis='XZ',qubits=[0,3],angle=.3)]
        raw=QuantumCircuit(6)
        for g in gates:append_rotation(raw,g['axis'],g['qubits'],g['angle'])
        compiled=build_circuit(gates,num_qubits=6,readout=False)
        self.assertEqual(len(raw.data)-len(compiled.data),2)
        np.testing.assert_allclose(Operator(raw).data,Operator(compiled).data,atol=1e-14)

if __name__=='__main__':unittest.main()
