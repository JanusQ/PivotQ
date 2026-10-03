"""Independent small-circuit acceptance; no 30-qubit training allocation."""
from pathlib import Path
import numpy as np
import pytest
import torch
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector,Pauli
from water10_v4.circuit import append_rotation
from water10_v4.dense_force.adjoint import DenseAdjoint,build_library
from water10_v4.dense_force.autograd import readouts


@pytest.fixture(scope='module')
def engine(tmp_path_factory):
    gates=[dict(axis=a,qubits=q) for a,q in [('Y',[0]),('X',[2]),('YZ',[0,2]),('XYZ',[2,0,1]),('Z',[1]),('YY',[1,2])]]
    return DenseAdjoint(gates,nqubits=3,threads=1,library=build_library(tmp_path_factory.mktemp('lib'))),gates


def test_state_and_readouts_against_qiskit(engine):
    e,gates=engine;a=np.array([.2,-.4,.7,.35,-.18,.51]);qc=QuantumCircuit(3)
    for g,angle in zip(gates,a):append_rotation(qc,g['axis'],g['qubits'],angle)
    ref=Statevector.from_instruction(qc);actual,_=e.forward_state(a)
    np.testing.assert_allclose(actual,ref.data,atol=1e-13,rtol=0)
    z=[]
    for axis in ('X','Z'):
        for q in range(3):
            label=['I']*3;label[2-q]=axis;z.append(ref.expectation_value(Pauli(''.join(label))).real)
    np.testing.assert_allclose(e.readouts(actual),z,atol=1e-13,rtol=0)


def test_adjoint_matches_individual_parameter_shift(engine):
    e,_=engine;a=np.linspace(-.3,.7,6);v=np.linspace(-.8,.5,6)
    expected=[]
    for j in range(6):
        shift=np.zeros(6);shift[j]=np.pi/2
        expected.append(v@(.5*(e.forward(a+shift)-e.forward(a-shift))))
    np.testing.assert_allclose(e.vjp(a,v),expected,atol=2e-12,rtol=0)


def test_hessian_vector_and_directional_readout(engine):
    e,_=engine;a=np.linspace(-.3,.7,6);v=np.linspace(-.8,.5,6);d=np.linspace(.2,-.7,6);h=1e-5
    hvp,zd=e.hvp(a,v,d)
    np.testing.assert_allclose(hvp,(e.vjp(a+h*d,v)-e.vjp(a-h*d,v))/(2*h),atol=1e-9,rtol=0)
    np.testing.assert_allclose(zd,(e.forward(a+h*d)-e.forward(a-h*d))/(2*h),atol=1e-9,rtol=0)


def test_force_loss_gradient_includes_mixed_derivatives(engine):
    e,_=engine
    def loss(x,theta,w):
        # Coordinate-dependent trainable gate scale tests the angle mixed term too.
        a=torch.sin(x)*theta
        z=readouts(a,e);energy=torch.tanh(z@w)
        force=-torch.autograd.grad(energy,x,create_graph=True)[0]
        return (energy-.3)**2+.4*((force-.2)**2).mean()
    x=torch.linspace(.2,.7,6,dtype=torch.float64,requires_grad=True)
    t=torch.linspace(-.3,.8,6,dtype=torch.float64,requires_grad=True)
    w=torch.linspace(-.4,.6,6,dtype=torch.float64,requires_grad=True)
    grads=torch.autograd.grad(loss(x,t,w),(t,w))
    for which,var in enumerate((t,w)):
        for j in range(6):
            shift=torch.zeros(6,dtype=torch.float64);shift[j]=1e-5
            plus=loss(x,t+shift,w) if which==0 else loss(x,t,w+shift)
            minus=loss(x,t-shift,w) if which==0 else loss(x,t,w-shift)
            assert abs(float(grads[which][j]) - float((plus-minus)/(2e-5)))<2e-8
