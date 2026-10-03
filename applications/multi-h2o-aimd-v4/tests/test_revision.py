import unittest
from copy import deepcopy
import numpy as np
from qiskit.quantum_info import Operator
from water10_v4.revision import *

class RevisionContract(unittest.TestCase):
    def test_all_templates_differ_and_mutation_is_rejected(self):
        t=revised_templates();self.assertTrue(audit_templates(t)['passed'])
        bad=deepcopy(t);bad['trainable']['3'][8]=deepcopy(bad['encoding']['3'][8])
        with self.assertRaises(AssertionError):audit_templates(bad)
        bad=deepcopy(t);bad['encoding']['2'][1]=deepcopy(bad['encoding']['2'][0])
        with self.assertRaises(AssertionError):audit_templates(bad)

    def test_zero_weight_whole_modules(self):
        t=revised_templates()
        for stage in t:
            for b in (2,3):
                qc=QuantumCircuit(3*b)
                for block in t[stage][str(b)]:
                    for g in block:append_rotation(qc,g['axis'],g['sites'],0.)
                np.testing.assert_allclose(Operator(qc).data,np.eye(2**(3*b)),atol=1e-13)

    def test_compilation_never_cancels_across_blocks(self):
        base=dict(stage='encoding',body=2,molecules=[0,1],origin='heuristic',parameter=None)
        gg=[dict(base,feature=0,axis='YZ',qubits=[0,3],angle=.2),
            dict(base,feature=1,axis='XZ',qubits=[0,3],angle=.3)]
        p=primitive_manifest(gg);self.assertEqual(len(p),6)
        gg[1]['feature']=0;p=primitive_manifest(gg);self.assertEqual(len(p),4)
        raw=QuantumCircuit(6)
        for g in gg:append_rotation(raw,g['axis'],g['qubits'],g['angle'])
        np.testing.assert_allclose(Operator(build_block_circuit(gg,num_qubits=6,readout=False)).data,Operator(raw).data,atol=1e-14)

    def test_interaction_records_and_continuity(self):
        from water10_v4.data import ROOT,load_panel
        ids=json.loads((ROOT/'data_v4/panels.json').read_text())['pilot_train_32']
        panel=load_panel(ids[:2]);radii=dict(pair_radii=[2.57,2.93],triple_radii=[2.53,2.84])
        records=interaction_records(panel,radii);raw=features(panel['positions_angstrom'],**radii)
        t=revised_templates();theta=theta_for(t)
        for i,rec in enumerate(records):
            self.assertEqual(len(rec['candidate_pairs']),45);self.assertEqual(len(rec['candidate_triples']),120)
            ff={k:raw[k][i] for k in ('x1','x2','x3','w2','w3')};g=instances(t,ff,theta)
            audit_instances(g,t)
            for b,name in ((2,'pairs'),(3,'triples')):
                self.assertEqual(sorted({tuple(x['molecules']) for x in g if x['body']==b}),
                     [tuple(x['molecule_ids']) for x in rec['active_'+name]])
            with self.assertRaises(AssertionError):audit_instances(g+[g[0]],t)

if __name__=='__main__':unittest.main()
