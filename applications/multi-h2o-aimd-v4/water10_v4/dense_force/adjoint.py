"""Full-amplitude Pauli circuit, adjoint VJP and exact tangent-over-adjoint HVP.

The force loss requires second derivatives. No finite differences, shift circuit
enumeration, MPS or subsystem simulation is used here. The independent tests
must pass before this engine is used for training.
"""
import os
import ctypes as ct
import hashlib
from pathlib import Path
import subprocess
import numpy as np

PTR=np.ctypeslib.ndpointer(dtype=np.complex128,ndim=1,flags='C_CONTIGUOUS')
U=ct.c_uint64


def build_library(directory):
    source=Path(__file__).with_name('kernels.cpp')
    flags=['-O3','-march=native','-std=c++17','-fopenmp','-shared','-fPIC']
    digest=hashlib.sha256(source.read_bytes()+str(flags).encode()).hexdigest()[:16]
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/f'dense-{digest}.so'
    if not path.exists():
        temporary=path.with_suffix('.tmp.so')
        subprocess.run(['g++',*flags,str(source),'-o',str(temporary)],check=True)
        temporary.replace(path)
    return path


class DenseAdjoint:
    def __init__(self,gates,nqubits=30,threads=8,library=None):
        if not 1<=nqubits<=30:raise ValueError('Expected 1..30 qubits; production uses all 30')
        if threads<1:raise ValueError('threads must be positive')
        self.nqubits=nqubits;self.n=1<<nqubits;self.ops=[]
        for gate in gates:
            axis=gate['axis'];qubits=gate['qubits']
            if len(axis)!=len(qubits) or len(set(qubits))!=len(qubits):raise ValueError('Invalid Pauli gate')
            if any(q<0 or q>=nqubits for q in qubits) or any(a not in 'XYZ' for a in axis):raise ValueError('Invalid sites/axes')
            x=sum(1<<q for a,q in zip(axis,qubits) if a in 'XY')
            z=sum(1<<q for a,q in zip(axis,qubits) if a in 'ZY')
            self.ops.append((x,z,axis.count('Y')))
        self.observables=[(1<<q,0,0) for q in range(nqubits)]+[(0,1<<q,0) for q in range(nqubits)]
        if library is None:raise ValueError('Build/validate the compiled library before constructing an engine')
        self.lib=ct.CDLL(str(library))
        self.lib.dense_threads.argtypes=[ct.c_int];self.lib.dense_threads.restype=None
        self.lib.dense_rotate.argtypes=[PTR,U,U,U,ct.c_int,ct.c_double];self.lib.dense_rotate.restype=None
        self.lib.dense_pauli_add.argtypes=[PTR,PTR,U,U,U,ct.c_int,ct.c_double,ct.c_double];self.lib.dense_pauli_add.restype=None
        self.lib.dense_gradient.argtypes=[PTR,PTR,U,U,U,ct.c_int];self.lib.dense_gradient.restype=ct.c_double
        self.lib.dense_bilinear.argtypes=[PTR,PTR,U,U,U,ct.c_int];self.lib.dense_bilinear.restype=ct.c_double
        self.lib.dense_threads(threads)

    def angles(self,value):
        value=np.asarray(value,dtype=np.float64)
        if value.shape!=(len(self.ops),) or not np.isfinite(value).all():raise ValueError('Invalid angles')
        return value

    def zero(self):return np.zeros(self.n,dtype=np.complex128)
    def check_stop(self):
        flag=os.environ.get('WATER10_STOP_FILE')
        if flag and Path(flag).exists():raise InterruptedError('Stop requested; previous completed checkpoint is retained')

    def rotate(self,state,op,angle):
        self.check_stop();self.lib.dense_rotate(state,self.n,*op,float(angle))
    def add(self,dst,src,op,scale):
        self.lib.dense_pauli_add(dst,src,self.n,*op,float(np.real(scale)),float(np.imag(scale)))
    def contraction(self,left,right,op):return self.lib.dense_gradient(left,right,self.n,*op)
    def bilinear(self,left,right,op):return self.lib.dense_bilinear(left,right,self.n,*op)

    def forward_state(self,angles,direction=None):
        self.check_stop()
        angles=self.angles(angles);psi=self.zero();psi[0]=1
        tangent=self.zero() if direction is not None else None
        if direction is not None:direction=self.angles(direction)
        for j,(angle,op) in enumerate(zip(angles,self.ops)):
            self.rotate(psi,op,angle)
            if tangent is not None:
                self.rotate(tangent,op,angle)
                if direction[j]:self.add(tangent,psi,op,-.5j*direction[j])
        return psi,tangent

    def readouts(self,psi):return np.array([.5*self.bilinear(psi,psi,op) for op in self.observables])
    def forward(self,angles):
        psi,_=self.forward_state(angles)
        return self.readouts(psi)

    def observable_state(self,psi,weights):
        weights=np.asarray(weights,dtype=float)
        if weights.shape!=(2*self.nqubits,) or not np.isfinite(weights).all():raise ValueError('Invalid observable weights')
        result=self.zero()
        for w,op in zip(weights,self.observables):
            if w:self.add(result,psi,op,w)
        return result

    def vjp(self,angles,weights):
        angles=self.angles(angles);psi,_=self.forward_state(angles)
        lam=self.observable_state(psi,weights);grad=np.empty(len(angles))
        for j in range(len(angles)-1,-1,-1):
            op=self.ops[j];grad[j]=self.contraction(lam,psi,op)
            self.rotate(psi,op,-angles[j]);self.rotate(lam,op,-angles[j])
        return grad

    def hvp(self,angles,weights,direction):
        """Return Hessian(weighted readouts) @ direction and J_readouts @ direction."""
        angles=self.angles(angles);direction=self.angles(direction)
        psi,tangent=self.forward_state(angles,direction)
        z_dot=np.array([self.bilinear(psi,tangent,op) for op in self.observables])
        lam=self.observable_state(psi,weights);lam_dot=self.observable_state(tangent,weights)
        result=np.empty(len(angles))
        for j in range(len(angles)-1,-1,-1):
            op=self.ops[j]
            result[j]=self.contraction(lam_dot,psi,op)+self.contraction(lam,tangent,op)
            # Differentiate U(-a); source arrays are still at gate output.
            if direction[j]:
                self.add(tangent,psi,op,.5j*direction[j])
                self.add(lam_dot,lam,op,.5j*direction[j])
            for state in (psi,tangent,lam,lam_dot):self.rotate(state,op,-angles[j])
        return result,z_dot
