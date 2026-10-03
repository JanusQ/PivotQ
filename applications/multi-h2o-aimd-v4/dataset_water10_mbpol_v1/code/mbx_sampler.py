"""Read-only reuse of the existing full MBX System API, original h2o monomers."""
import ctypes
import json
import numpy as np
from ase.calculators.calculator import Calculator, all_changes
from ase import units
from common import source_path

class MBX(Calculator):
    implemented_properties=['energy','forces']
    def __init__(self,c,settings=None):
        super().__init__()
        self.lib=ctypes.CDLL(str(source_path(c,'adapter_library')))
        ptr=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
        self.lib.evaluate.argtypes=[ctypes.c_int,ptr,ptr,ptr,ctypes.c_int]
        self.lib.evaluate.restype=ctypes.c_int
        self.lib.configure.argtypes=[ctypes.c_char_p]
        self.lib.configure.restype=None
        self.lib.last_error.restype=ctypes.c_char_p
        self.settings=settings or {'MBX': {'box': [],'realspace_cutoff':100.,'twobody_cutoff':100.,'threebody_cutoff':7.,
            'dipole_tolerance':1e-14,'dipole_max_it':500,'dipole_method':'cg','alpha_ewald_elec':0.,'alpha_ewald_disp':0.,
            'ignore_1b_poly':[],'ignore_2b_poly':[],'ignore_3b_poly':[]}}
        self.lib.configure(json.dumps(self.settings).encode())
    def evaluate(self,x):
        x=np.ascontiguousarray(x,dtype=np.float64).reshape(-1,3)
        out=np.zeros(3); grad=np.zeros(x.size)
        rc=self.lib.evaluate(len(x)//3,x,out,grad,1)
        if rc: raise RuntimeError(self.lib.last_error().decode())
        factor=units.kcal/units.mol
        e=float(out[0]*factor); f=-grad.reshape(x.shape)*factor
        if not np.isfinite(e) or not np.isfinite(f).all(): raise ValueError('nonfinite MBX output')
        return e,f
    def calculate(self,atoms=None,properties=('energy','forces'),system_changes=all_changes):
        super().calculate(atoms,properties,system_changes)
        if np.any(atoms.pbc): raise ValueError('Only isolated nonperiodic clusters are permitted')
        if list(atoms.numbers)!=[8,1,1]*(len(atoms)//3): raise ValueError('MBX requires fixed O,H,H order')
        e,f=self.evaluate(atoms.positions)
        self.results={'energy':e,'forces':f}
