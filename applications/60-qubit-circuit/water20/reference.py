"""External MBX shared library; full interacting cluster energies and forces.

No fitted water10 weights or data are read. Each process owns its MBX state.
"""
import ctypes
import json
from pathlib import Path

import numpy as np
from ase.calculators.calculator import Calculator, all_changes
from ase import units


class MBX(Calculator):
    implemented_properties = ["energy", "forces"]

    def __init__(self, library, settings):
        super().__init__()
        self.library = Path(library).resolve()
        self.lib = ctypes.CDLL(str(self.library))
        array = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
        self.lib.evaluate.argtypes = [ctypes.c_int, array, array, array, ctypes.c_int]
        self.lib.evaluate.restype = ctypes.c_int
        self.lib.configure.argtypes = [ctypes.c_char_p]
        self.lib.configure.restype = None
        self.lib.last_error.restype = ctypes.c_char_p
        self.lib.configure(json.dumps(settings).encode())

    def evaluate(self, positions):
        x = np.ascontiguousarray(positions, dtype=np.float64)
        if x.shape != (60, 3) or not np.isfinite(x).all():
            raise ValueError("MBX water20 requires finite (60,3) Angstrom coordinates")
        out, gradient = np.zeros(3), np.zeros(x.size)
        rc = self.lib.evaluate(20, x, out, gradient, 1)
        if rc:
            raise RuntimeError(self.lib.last_error().decode())
        factor = units.kcal / units.mol
        energy, forces = float(out[0] * factor), -gradient.reshape(x.shape) * factor
        if not np.isfinite(energy) or not np.isfinite(forces).all():
            raise ValueError("Nonfinite MBX label")
        return energy, forces

    def calculate(self, atoms=None, properties=("energy", "forces"), system_changes=all_changes):
        super().calculate(atoms, properties, system_changes)
        if np.any(atoms.pbc) or list(atoms.numbers) != [8, 1, 1] * 20:
            raise ValueError("Isolated OHH-ordered water20 cluster required")
        energy, forces = self.evaluate(atoms.positions)
        self.results = {"energy": energy, "forces": forces}
