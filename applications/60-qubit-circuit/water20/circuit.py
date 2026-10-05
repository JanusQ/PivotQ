"""Single global circuit; exact Pauli rotations; terminal X/Z settings."""
import numpy as np
from qiskit import QuantumCircuit, transpile


def append_rotation(circuit, axis, qubits, angle):
    if len(axis) == 1:
        getattr(circuit, "r"+axis.lower())(angle, qubits[0])
    elif axis[0] in "XY" and set(axis[1:]) == {"Z"}:
        for q in qubits[1:]:
            circuit.cz(qubits[0], q)
        getattr(circuit, "r"+axis[0].lower())(angle, qubits[0])
        for q in reversed(qubits[1:]):
            circuit.cz(qubits[0], q)
    else:
        raise ValueError("Unsupported template axis")


def build(gates, n_qubits=60, basis=None, shift=None):
    if basis not in (None, "X", "Z"):
        raise ValueError("Only terminal X/Z readout is supported")
    circuit = QuantumCircuit(n_qubits)
    for index, gate in enumerate(gates):
        angle = gate["angle"] + (shift[1] if shift is not None and shift[0] == index else 0.)
        append_rotation(circuit, gate["axis"], gate["qubits"], angle)
    if basis == "X":
        for q in range(n_qubits):
            circuit.h(q)
    return circuit


def native(circuit, *, coupling=None, initial_layout=None, seed=20261004):
    """Exact level-1 native compilation; optional actual hardware routing.

    Level 2/3 dropped near-identity rotations in the measured smooth-cutoff
    circuit despite approximation_degree=1. Level 1 passed full 60-wire checks.
    """
    options = dict(basis_gates=["rx", "rz", "cz"], optimization_level=1, approximation_degree=1.0, seed_transpiler=seed)
    if coupling is not None:
        directed = [edge for a, b in coupling for edge in ([a, b], [b, a])]
        options.update(coupling_map=directed, initial_layout=initial_layout or list(range(circuit.num_qubits)))
    return transpile(circuit, **options)


def validate_templates(config):
    templates = config["templates"]
    checks, keys = [], []
    for body, count in ((1, 3), (2, 10), (3, 15)):
        signatures = {}
        for stage in ("encoding", "trainable"):
            blocks = templates[stage][str(body)]
            if len(blocks) != count:
                raise ValueError("Wrong semantic block count")
            signatures[stage] = []
            for f, block in enumerate(blocks):
                signature = tuple((g["axis"], tuple(g["sites"])) for g in block)
                if not block or any(len(g["axis"]) != len(g["sites"]) or len(set(g["sites"])) != len(g["sites"]) or
                                    any(q < 0 or q >= 3*body for q in g["sites"]) for g in block):
                    raise ValueError("Invalid template scope")
                signatures[stage].append(signature)
                if stage == "trainable":
                    keys.extend(f"b{body}_f{f}_g{j}" for j in range(len(block)))
            if len(set(signatures[stage])) != count:
                raise ValueError("Duplicate feature-block signatures")
        for f in range(count):
            if signatures["encoding"][f] == signatures["trainable"][f]:
                raise ValueError("Encoding/trainable structures must differ")
            checks.append(dict(body=body, feature=f, structurally_different=True))
        if body > 1:
            for stage in signatures:
                entanglers = [g for block in templates[stage][str(body)] for g in block if len(g["sites"]) > 1]
                if not entanglers or any(len({q//3 for q in g["sites"]}) != body for g in entanglers):
                    raise ValueError("Multi-body gates must span every owner molecule")
    if len(keys) != 48:
        raise ValueError("Expected 48 shared quantum parameters")
    return keys, checks
