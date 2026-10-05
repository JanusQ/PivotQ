"""Exact tensor factors determined from actual gate connectivity, complex128.

This never allocates a 2**60 vector, truncates Schmidt values, or crops qubits.
It is CPU validation, not hardware validation. New entanglers automatically
merge factors; excessively large factors fail explicitly instead of fallback.
"""
import numpy as np


def native_gates(circuit):
    """RX/RZ/CZ circuit -> exact Pauli rotations, ignoring global phase only."""
    gates = []
    for item in circuit.data:
        q = [circuit.find_bit(bit).index for bit in item.qubits]
        if item.operation.name == "cz":
            gates.extend([dict(axis="Z", qubits=[q[0]], angle=-np.pi/2),
                          dict(axis="Z", qubits=[q[1]], angle=-np.pi/2),
                          dict(axis="ZZ", qubits=q, angle=np.pi/2)])
        elif item.operation.name in ("rx", "rz"):
            gates.append(dict(axis=item.operation.name[1].upper(), qubits=q, angle=float(item.operation.params[0])))
        else:
            raise ValueError("Unexpected operation after native compilation")
    return gates


def components(gates, n_qubits):
    parents = list(range(n_qubits))
    def find(q):
        while parents[q] != q:
            parents[q] = parents[parents[q]]
            q = parents[q]
        return q
    for g in gates:
        for q in g["qubits"][1:]:
            parents[find(q)] = find(g["qubits"][0])
    grouped = {}
    for q in range(n_qubits):
        grouped.setdefault(find(q), []).append(q)
    return list(grouped.values())


class Factor:
    def __init__(self, qubits, gates, max_qubits):
        if len(qubits) > max_qubits:
            raise MemoryError(f"Exact factor contains {len(qubits)} qubits; limit={max_qubits}")
        self.qubits = qubits
        local = {q: i for i, q in enumerate(qubits)}
        self.gates = [(index, g["axis"], [local[q] for q in g["qubits"]], g["angle"])
                      for index, g in gates]
        self.index = np.arange(2**len(qubits), dtype=np.uint32)
        self.bits = [((self.index >> q) & 1).astype(np.int8) for q in range(len(qubits))]
        self.flips = {q: self.index ^ (1 << q) for q in range(len(qubits))}
        self.state = np.zeros(len(self.index), dtype=np.complex128)
        self.state[0] = 1

    def pauli(self, state, axis, qubits):
        # Templates contain at most one X/Y and otherwise Z, with axis order
        # attached to the listed wires. Output phases use the *input* bits.
        phase = np.ones(len(state), dtype=np.complex128)
        flip = None
        for a, q in zip(axis, qubits):
            if a == "Z":
                phase *= 1-2*self.bits[q]
            elif a in "XY":
                if flip is not None:
                    raise ValueError("Template contains multiple flipping axes")
                flip = q
                if a == "Y":
                    phase *= 1j*(1-2*self.bits[q])
            else:
                raise ValueError("Unknown Pauli axis")
        if flip is None:
            return phase*state
        return (phase*state)[self.flips[flip]]

    def rotate(self, state, axis, qubits, angle):
        return np.cos(angle/2)*state - 1j*np.sin(angle/2)*self.pauli(state, axis, qubits)

    def forward(self):
        for _, axis, qubits, angle in self.gates:
            self.state = self.rotate(self.state, axis, qubits, angle)
        norm = np.vdot(self.state, self.state).real
        if abs(norm-1) > 1e-8:
            raise ArithmeticError("Exact factor lost state normalization")
        return [[float(np.vdot(self.state, self.pauli(self.state, axis, [q])).real)
                 for q in range(len(self.qubits))] for axis in ("X", "Z")]

    def adjoint(self, feature_gradient, n_qubits):
        dual = np.zeros_like(self.state)
        for local, logical in enumerate(self.qubits):
            for offset, axis in ((0, "X"), (n_qubits, "Z")):
                dual += feature_gradient[offset+logical]*self.pauli(self.state, axis, [local])
        state = self.state.copy()
        derivatives = []
        for index, axis, qubits, angle in reversed(self.gates):
            # dU/dangle=-i P U/2; unitary inverse reconstructs prior state.
            derivative = float(np.vdot(dual, self.pauli(state, axis, qubits)).imag)
            derivatives.append((index, derivative))
            state = self.rotate(state, axis, qubits, -angle)
            dual = self.rotate(dual, axis, qubits, -angle)
        return derivatives


class ExactSimulator:
    def __init__(self, max_factor_qubits=20):
        self.max_factor_qubits = max_factor_qubits
        self.factors = []

    def evaluate(self, gates, n_qubits=60):
        groups = components(gates, n_qubits)
        owners = {q: i for i, group in enumerate(groups) for q in group}
        grouped_gates = [[] for _ in groups]
        for index, gate in enumerate(gates):
            grouped_gates[owners[gate["qubits"][0]]].append((index, gate))
        self.factors = [Factor(q, g, self.max_factor_qubits) for q, g in zip(groups, grouped_gates)]
        features = np.empty(2*n_qubits)
        for factor in self.factors:
            values = factor.forward()
            features[factor.qubits] = values[0]
            features[np.array(factor.qubits)+n_qubits] = values[1]
        self.last_metadata = dict(backend="cpu_exact_tensor_factors", dtype="complex128", real_qpu=False,
                                  n_qubits=n_qubits, all_qubits_retained=True, truncated=False,
                                  factor_qubits=groups, max_factor_qubits=max(map(len, groups)))
        return features

    def angle_gradient(self, features_gradient, n_gates, n_qubits=60):
        derivative = np.zeros(n_gates)
        for factor in self.factors:
            for index, value in factor.adjoint(features_gradient, n_qubits):
                derivative[index] = value
        return derivative
