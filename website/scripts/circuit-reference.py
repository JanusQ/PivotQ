"""Generate small reference fixtures by executing the supplied native F2 compiler.

The shim implements only Qiskit's gate API used by the original source, with
dense NumPy matrices in Qiskit little-endian order. It does not reimplement the
logical Pauli simulator under test. No scientific AIMD calculation is run.
"""
import copy
import importlib.util
import json
import sys
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


class QuantumCircuit:
    def __init__(self, n, name=None):
        assert n == 3
        self.state = np.eye(8, dtype=complex)[:, 0]
        self.metadata = {}

    def apply(self, matrix, q):
        factors = [matrix if i == q else np.eye(2) for i in (2, 1, 0)]
        self.state = np.kron(np.kron(factors[0], factors[1]), factors[2]) @ self.state

    def ry(self, theta, q):
        c, s = np.cos(theta / 2), np.sin(theta / 2)
        self.apply(np.array([[c, -s], [s, c]]), q)

    def rz(self, theta, q):
        self.apply(np.diag([np.exp(-1j * theta / 2), np.exp(1j * theta / 2)]), q)

    def cz(self, a, b):
        self.state = np.diag([-1 if i & (1 << a) and i & (1 << b) else 1 for i in range(8)]) @ self.state

    def copy(self, name=None):
        return copy.deepcopy(self)


sys.modules['qiskit'] = types.SimpleNamespace(QuantumCircuit=QuantumCircuit)
loader = importlib.util.spec_from_file_location('provided_f2', ROOT / 'public/aimd/qiskit_f2.py')
source = importlib.util.module_from_spec(loader)
loader.loader.exec_module(source)
cases = [
    ([np.pi / 4, np.pi / 8, np.pi / 4], [.4, -.6, .8, .3, -.5, .7], [.45, -.35, .55, .25, -.2]),
    ([0, 0, 0], [0] * 6, [0] * 5),
    ([-1.2, .37, 2.6], [.15, -2.3, 1.1, -.84, 2.04, -.22], [-.51, 1.4, -2.9, .7, 1.2]),
]
fixtures = []
reorder = [int(f'{i:03b}'[::-1], 2) for i in range(8)]
for angles, seed, adapt in cases:
    spec = dict(num_qubits=3, seed='native', connectivity=[[0, 1], [1, 2]], entangler_gate='cz',
                data_reuploading=False, selected_operators=list(source.F2_OPERATOR_SEQUENCE),
                seed_parameters=seed, adapt_parameters=adapt)
    z, x = source.build_bound_f2_circuit_pair(angles, spec)
    state = z.state[reorder]
    fixtures.append(dict(encoding=angles, seed=seed, adapt=adapt,
                         re=state.real.tolist(), im=state.imag.tolist(),
                         z=(abs(z.state[reorder]) ** 2).tolist(), x=(abs(x.state[reorder]) ** 2).tolist()))
target = ROOT / 'scripts/fixtures/f2-native-reference.json'
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({'source': 'public/aimd/qiskit_f2.py, unchanged native compiler via NumPy matrix shim', 'order': 'q0 q1 q2', 'cases': fixtures}, indent=2) + '\n', encoding='utf-8')
print(f'Generated {len(fixtures)} native-compiler reference cases: {target}')
