"""Explicit device profile and routing, without guessing 60 physical labels."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from qiskit import qasm3

from .circuit import build, native


class HardwareNotReady(RuntimeError):
    pass


@dataclass(frozen=True)
class HardwareProfile:
    mapping_version: str
    physical_labels: tuple[str, ...]  # QASM q[slot] -> device result_qNN label
    coupling_edges: tuple[tuple[int, int], ...]
    initial_layout: tuple[int, ...]  # logical -> QASM physical slot
    max_depth: int
    max_gates: int
    shot_index_base: int = 0
    terminal_measurement: str = "server_z"

    @classmethod
    def load(cls, path):
        document = json.loads(Path(path).read_text())
        if document.get("schema_version") != 1 or document.get("n_qubits") != 60:
            raise HardwareNotReady("A versioned 60-qubit hardware profile is required")
        labels, edges = document.get("physical_labels"), document.get("coupling_edges")
        layout = document.get("initial_layout")
        if not isinstance(labels, list) or len(labels) != 60 or len(set(labels)) != 60 or any(not isinstance(q, str) or not re.fullmatch(r"q\d+", q) for q in labels):
            raise HardwareNotReady("Missing 60 distinct confirmed physical readout labels")
        if not isinstance(layout, list) or any(type(q) is not int for q in layout) or sorted(layout) != list(range(60)):
            raise HardwareNotReady("Explicit initial logical-to-slot permutation required")
        if not isinstance(edges, list) or not edges:
            raise HardwareNotReady("Actual hardware coupling edges are required")
        graph = {q: set() for q in range(60)}
        for edge in edges:
            if not isinstance(edge, list) or len(edge) != 2 or any(type(q) is not int or q not in graph for q in edge) or edge[0] == edge[1]:
                raise HardwareNotReady("Coupling edges must use slots 0..59")
            a, b = edge
            graph[a].add(b)
            graph[b].add(a)
        seen, pending = set(), [0]
        while pending:
            q = pending.pop()
            if q not in seen:
                seen.add(q)
                pending.extend(graph[q]-seen)
        if len(seen) != 60:
            raise HardwareNotReady("A connected 60-slot subgraph is required")
        if document.get("terminal_measurement") != "server_z" or document.get("native_gates") != ["rx", "rz", "cz"]:
            raise HardwareNotReady("This adapter implements the reference RX/RZ/CZ and server-terminal-Z protocol")
        if document.get("result_format") != "shot_table" or document.get("shot_index_base") not in (0, 1):
            raise HardwareNotReady("Explicit shot-table protocol required")
        if any(type(document.get(k)) is not int or document[k] <= 0 for k in ("max_depth", "max_gates")):
            raise HardwareNotReady("Confirmed hardware depth/gate budgets required")
        version = document.get("mapping_version")
        if not isinstance(version, str) or not version.strip():
            raise HardwareNotReady("Mapping version required")
        if document.get("capability_status") != "confirmed_60_qubit_global_circuit":
            raise HardwareNotReady("Profile must confirm a global 60-qubit circuit, not independent 3-qubit lanes")
        return cls(version, tuple(labels), tuple(map(tuple, edges)), tuple(layout),
                   document["max_depth"], document["max_gates"], document["shot_index_base"])


@dataclass(frozen=True)
class CircuitRequest:
    circuit_id: str
    basis: str
    filename: str
    qasm: str
    logical_readout_labels: tuple[str, ...]
    mapping_version: str
    depth: int
    n_gates: int
    schema_version: int = 1


def prepare(gates, profile, request_id):
    requests = []
    for basis in ("X", "Z"):
        circuit = native(build(gates, basis=basis), coupling=profile.coupling_edges,
                         initial_layout=list(profile.initial_layout))
        if circuit.num_qubits != 60 or circuit.num_clbits or circuit.parameters:
            raise HardwareNotReady("Bound 60-qubit unitary circuit required")
        edges = {tuple(sorted(edge)) for edge in profile.coupling_edges}
        for item in circuit.data:
            name = item.operation.name
            if name not in ("rx", "rz", "cz"):
                raise HardwareNotReady("Non-native operation after compilation")
            if name == "cz":
                edge = tuple(sorted(circuit.find_bit(q).index for q in item.qubits))
                if edge not in edges:
                    raise HardwareNotReady("Compiler emitted a CZ outside physical topology")
        depth, n_gates = circuit.depth(), len(circuit.data)
        if depth > profile.max_depth or n_gates > profile.max_gates:
            raise HardwareNotReady(f"Hardware budget exceeded: depth={depth}, gates={n_gates}")
        slots = circuit.layout.final_index_layout() if circuit.layout is not None else list(profile.initial_layout)
        if sorted(slots) != list(range(60)):
            raise HardwareNotReady("Invalid final routing permutation")
        logical_labels = tuple(profile.physical_labels[q] for q in slots)
        # Strip Qiskit's physical-layout metadata before QASM serialization so
        # q[slot] refers to the profile's confirmed register-slot mapping.
        from qiskit import QuantumCircuit
        plain = QuantumCircuit(60)
        plain.global_phase = circuit.global_phase
        for item in circuit.data:
            plain.append(item.operation, [circuit.find_bit(q).index for q in item.qubits])
        text = qasm3.dumps(plain)
        # Global phase has no effect on final computational-basis probabilities.
        text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("gphase("))+"\n"
        cid = f"{request_id}.{basis}"
        filename = "circuit-"+hashlib.sha256(cid.encode()).hexdigest()[:24]+".qasm"
        requests.append(CircuitRequest(cid, basis, filename, text, logical_labels,
                                       profile.mapping_version, depth, n_gates))
    return tuple(requests)
