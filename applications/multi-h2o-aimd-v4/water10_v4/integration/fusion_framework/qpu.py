"""30-qubit application contract. The repository's 3q QOS service is NOT compatible."""
import inspect
import math
from uuid import uuid4

import numpy as np

from ...revision import build_block_circuit
from .model import readouts


def bound_circuit_pair(gates, shift=None):
    """Use the exact trained compiler; the provider only adds final Z measurement."""
    z = build_block_circuit(gates, shift=shift, readout=False)
    x = z.copy()
    for q in range(30):
        x.h(q)
    return [('X', x), ('Z', z)]


def decode_results(results, expected, shots):
    """Sparse joint distributions in q0..q29 order; missing strings mean zero.

    Never enumerate the 2**30 state space. Raw Qiskit counts must be reversed
    by the service before crossing this contract.
    """
    if len(results) != len(expected):
        raise ValueError('QPU result count mismatch')
    values = []
    for raw, (circuit_id, basis) in zip(results, expected):
        if raw.get('circuit_id') != circuit_id or raw.get('measurement_basis') != basis:
            raise ValueError('QPU circuit ID/order/basis mismatch')
        if raw.get('status', 'succeeded') != 'succeeded' or raw.get('error'):
            raise RuntimeError(f'QPU circuit failed: {raw.get("error")}')
        if raw.get('measurement_qubits') != list(range(30)):
            raise ValueError('QPU bit order must be q0..q29 left-to-right')
        if isinstance(raw.get('shots'), bool) or raw.get('shots') != shots:
            raise ValueError('QPU shots mismatch')
        probabilities = raw.get('probabilities')
        if not isinstance(probabilities, dict) or not probabilities:
            raise ValueError('Expected nonempty sparse joint probabilities')
        total = 0.
        marginal = np.zeros(30)
        for bits, value in probabilities.items():
            if not isinstance(bits, str) or len(bits) != 30 or set(bits) - {'0', '1'}:
                raise ValueError('Expected 30-bit keys')
            p = float(value)
            if not math.isfinite(p) or not 0 <= p <= 1:
                raise ValueError('Invalid probability')
            total += p
            marginal += p * np.array([1 if b == '0' else -1 for b in bits])
        if not math.isclose(total, 1., abs_tol=1e-6, rel_tol=1e-6):
            raise ValueError('QPU probabilities do not sum to one')
        values.append(marginal)
    return readouts(np.asarray(values).reshape(-1, 60))


class QPUFeatures:
    def __init__(self, service, *, shots, physical_qubits=None, request_factory=None):
        if isinstance(shots, bool) or not isinstance(shots, int) or shots <= 0:
            raise ValueError('shots must be a positive integer')
        # Explicit capability handshake prevents accidental submission to legacy 3q QOS.
        description = service.describe()
        if (description.get('num_qubits') != 30 or
                description.get('result_bit_order') != 'q0..q29' or
                description.get('measurement_bases') != ['X', 'Z']):
            raise ValueError('QPU service must declare 30 qubits, q0..q29 and X/Z bases')
        if physical_qubits is not None:
            if (len(physical_qubits) != 30 or len(set(physical_qubits)) != 30 or
                    any(not isinstance(q, str) or not q for q in physical_qubits)):
                raise ValueError('Expected 30 unique physical qubit names')
        self.service, self.shots = service, shots
        self.physical_qubits, self.request_factory = physical_qubits, request_factory
        self.step = 0

    def evaluate_batch(self, gates_batch, shifts=None):
        if not gates_batch:
            raise ValueError('Empty circuit batch')
        if self.step > 999999:
            raise RuntimeError('QPU step counter exhausted')
        shifts = [None] * len(gates_batch) if shifts is None else shifts
        if len(shifts) != len(gates_batch):
            raise ValueError('Shift batch length mismatch')
        factory = self.request_factory
        if factory is None:
            from pivotq._internal.qpu_integration import QuantumCircuitRequest
            factory = QuantumCircuitRequest
        requests, expected = [], []
        prefix = uuid4().hex
        for i, (gates, shift) in enumerate(zip(gates_batch, shifts)):
            for basis, circuit in bound_circuit_pair(gates, shift):
                identity = f'{prefix}.{i}.{basis}'
                requests.append(factory(circuit_id=identity, circuit=circuit, measurement_basis=basis))
                expected.append((identity, basis))
        kwargs = dict(step=self.step, circuits=requests, shots=self.shots)
        self.step += 1
        parameters = inspect.signature(self.service.run_quantum_circuits).parameters
        if 'physical_qubits' in parameters:
            if self.physical_qubits is None:
                raise ValueError('This service requires physical_qubits')
            kwargs['physical_qubits'] = self.physical_qubits
        if 'measurement_qubits' in parameters:
            kwargs['measurement_qubits'] = list(range(30))
        return decode_results(list(self.service.run_quantum_circuits(**kwargs)), expected, self.shots)

    def evaluate(self, gates, context='forward', shift=None):
        return self.evaluate_batch([gates], [shift])[0]

    def jacobian(self, gates, keys, context='parameter_shift'):
        """Preserve per-gate shifts and chain factors for shared parameters."""
        jac = np.zeros((60, len(keys)))
        indices = {key: i for i, key in enumerate(keys)}
        for i, gate in enumerate(gates):
            key = gate['parameter']
            if key in indices and gate['coefficient'] != 0:
                plus, minus = self.evaluate_batch([gates, gates], [(i, np.pi/2), (i, -np.pi/2)])
                jac[:, indices[key]] += .5 * gate['coefficient'] * (plus - minus)
        return jac
