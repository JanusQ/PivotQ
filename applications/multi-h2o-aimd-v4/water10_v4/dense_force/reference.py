"""Read-only MBX evaluation with exactly the frozen dataset's settings and units."""
import os
import ctypes as ct
import json
from pathlib import Path
import numpy as np
from ..data import DATASET


class Reference:
    def __init__(self,root=DATASET):
        root=Path(root);lock=json.loads((root/'config/reference.lock.json').read_text())
        libs=root/'vendor/mbx/pcie5/lib'
        fftw=os.environ.get('WATER10_FFTW_LIBRARY')
        self.fftw=ct.CDLL(fftw,mode=ct.RTLD_GLOBAL) if fftw else None
        self.base=ct.CDLL(str(libs/'libmbx.so.0.0.0'),mode=ct.RTLD_GLOBAL)
        self.lib=ct.CDLL(str(libs/'libqaqua_mbx.so'))
        pointer=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
        self.lib.evaluate.argtypes=[ct.c_int,pointer,pointer,pointer,ct.c_int];self.lib.evaluate.restype=ct.c_int
        self.lib.configure.argtypes=[ct.c_char_p];self.lib.configure.restype=None
        self.lib.last_error.restype=ct.c_char_p
        self.lib.configure(json.dumps(lock['settings']).encode());self.factor=lock['units']['kcalmol_to_ev']

    def evaluate(self,positions):
        x=np.ascontiguousarray(positions,dtype=np.float64)
        if x.shape!=(30,3) or not np.isfinite(x).all():raise ValueError('Expected finite ten-water geometry')
        energy=np.zeros(3);gradient=np.zeros(90)
        if self.lib.evaluate(10,x,energy,gradient,1):raise RuntimeError(self.lib.last_error().decode())
        e=float(energy[0]*self.factor);f=-gradient.reshape(30,3)*self.factor
        if not np.isfinite(e) or not np.isfinite(f).all():raise ValueError('Invalid reference labels')
        return e,f
