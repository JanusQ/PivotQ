import unittest
import numpy as np
from water10_v4 import mlp_full
from water10_v4.benchmark002 import corrected_templates, audit_angles
from water10_v4.revision import revised_templates, theta_for, audit_templates
from water10_v4.circuit import instances


class Training002Contract(unittest.TestCase):
    def test_floor_is_encoding_only_and_inactive_modules_stay_absent(self):
        old=revised_templates();t=corrected_templates(old);theta=theta_for(t)
        f=dict(x1=np.zeros((10,3)),x2=np.full((45,10),-.108),
               x3=np.full((120,15),1.394),w2=np.zeros(45),w3=np.zeros(120))
        f['w2'][0]=.0006945094718296879;f['w3'][0]=.0006945094718296879
        gates=instances(t,f,theta);audit_angles(gates,f)
        self.assertTrue(all(abs(g['angle'])>=.1 for g in gates if g['stage']=='encoding'))
        self.assertTrue(all(g['combination_index']==0 for g in gates if g['body']>1))
        self.assertEqual([g for g in gates if g['stage']=='trainable'],
                         [g for g in instances(old,f,theta) if g['stage']=='trainable'])
        self.assertEqual({g['angle'] for g in gates if g['stage']=='encoding' and g['body']==2},{-.1})
        self.assertEqual({g['angle'] for g in gates if g['stage']=='encoding' and g['body']==3},{.1})

    def test_uniform_encoding_without_structure_changes(self):
        old = revised_templates()
        t = corrected_templates(old)
        self.assertTrue(audit_templates(t)['passed'])
        self.assertEqual(t['trainable'], old['trainable'])
        f = dict(x1=np.full((10,3), .31), x2=np.full((45,10), .42),
                 x3=np.full((120,15), .53), w2=np.full(45,.7), w3=np.full(120,.4))
        audit = audit_angles(instances(t,f,theta_for(t)),f)
        self.assertEqual(len(audit), 30+45*10+120*15)
        for row in audit:
            self.assertAlmostEqual(row['angle'], {1:.31,2:.42*.7,3:.53*.4}[row['body']])

    def test_mlp_parameter_limits(self):
        self.assertEqual([mlp_full.parameter_count(w) for w in mlp_full.ARCHITECTURES],
                         [993,2497,6017,10177,14177])
        with self.assertRaises(ValueError):
            mlp_full.initialize((60,512,1))

    def test_mlp_full_reverse_gradient(self):
        net=mlp_full.initialize((3,4,2,1))
        z=np.array([[.2,-.7,.5],[-.1,.6,.8]])
        y=np.array([.3,-.4])
        _,grad,dz=mlp_full.backward(net,z,y)
        loss=lambda: np.mean((mlp_full.predict(net,z)-y)**2)
        eps=1e-6
        for key,arr in net['p'].items():
            for ix in np.ndindex(arr.shape):
                old=arr[ix];arr[ix]=old+eps;plus=loss()
                arr[ix]=old-eps;minus=loss();arr[ix]=old
                self.assertAlmostEqual(grad[key][ix],(plus-minus)/(2*eps),places=8)
        for ix in np.ndindex(z.shape):
            old=z[ix];z[ix]=old+eps;plus=loss()
            z[ix]=old-eps;minus=loss();z[ix]=old
            self.assertAlmostEqual(dz[ix],(plus-minus)/(2*eps),places=8)


if __name__=='__main__': unittest.main()
