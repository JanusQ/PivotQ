"""Single 30-qubit circuit, explicit semantic templates and per-instance angles."""
from copy import deepcopy
from itertools import product
import numpy as np
from qiskit import QuantumCircuit
from .data import PAIRS, TRIPLES
from .encoding_angles import enforce_encoding_floor

COUNTS = {1: 3, 2: 10, 3: 15}

def gate(axis, sites, origin='heuristic', scale=1.):
    return dict(axis=axis, sites=list(sites), origin=origin, scale=scale)

def empty_templates():
    return {stage: {str(b): [[] for _ in range(n)] for b,n in COUNTS.items()}
            for stage in ('encoding', 'trainable')}

def seed_templates():
    t = empty_templates()
    for stage in t:
        for f in range(3):
            t[stage]['1'][f] = [gate('Y' if f != 1 else 'X', [f])]
    return t

def parameter_key(b, f, j):
    return f'b{b}_f{f}_g{j}'

def parameter_keys(t):
    return [parameter_key(b,f,j) for b,n in COUNTS.items() for f in range(n)
            for j in range(len(t['trainable'][str(b)][f]))]

def complete_templates(t, bus_only=False):
    """Explicitly heuristic semantic completion; retain all adaptive operations."""
    t = deepcopy(t)
    for stage in t:
        for b,n in COUNTS.items():
            for f in range(n):
                block = t[stage][str(b)][f]
                if not block:
                    # Feature owner and a rotating local site: no random decoration.
                    owner = f//5 if b>1 else 0
                    q = owner*3 + f%3
                    block.append(gate(('Y','X','Y','X','Y')[f%5], [q], scale=.65))
                # A small, nonuniform number of genuine entangling Pauli rotations.
                if b==1 and f in (0,2):
                    block.append(gate('XZ' if f==0 else 'YZZ', [0,1] if f==0 else [2,0,1], scale=.45))
                if b==2 and f in (0,3,6,9):
                    block.append(gate('XZ' if f%2==0 else 'YZ', [f%3,3+(f+1)%3], scale=.4))
                if b==3 and f in (0,4,8,12):
                    block.append(gate('XZZ' if f%8==0 else 'YZZ', [f%3,3+(f+1)%3,6+(f+2)%3], scale=.3))
    if bus_only:
        # Numerically audited fallback: ten interacting q_(3i), twenty local wires.
        # No molecular-1B entanglers, so all bipartitions have Schmidt rank <=32.
        # This is NOT an equivalent simplification of the adaptive YZZ candidate.
        for stage in t:
            for b,n in COUNTS.items():
                for f in range(n):
                    for g in t[stage][str(b)][f]:
                        if len(g['axis'])<=1: continue
                        old=deepcopy(g)
                        if b==1:
                            g.update(axis='X' if f==0 else 'Z',sites=[f])
                        else:
                            g.update(axis=g['axis'][0]+'Z'*(b-1),sites=[3*i for i in range(b)])
                        g.update(origin='heuristic',previous_gate=old,
                                 change_reason='bound interacting subsystem to ten molecular wires; exact Schmidt rank <=32')
                    block=t[stage][str(b)][f]
                    for j in range(1,len(block)):
                        if block[j]['axis']==block[j-1]['axis'] and block[j]['sites']==block[j-1]['sites']:
                            block[j]['axis']=('X' if block[j]['axis'][0]=='Y' else 'Y')+block[j]['axis'][1:]
                            block[j]['change_reason']+='; use a noncommuting axis rather than duplicate same-axis rotations'
    return t

def active_pool():
    """Frozen explicit 16-edit engineering pool; no gradient pre-screening."""
    specs = [(1,0,'XZ',[0,1]),(1,1,'YZ',[1,2]),(1,2,'XZZ',[2,0,1]),
             (1,0,'XY',[1,2]),(1,2,'Y',[0]),(1,1,'ZX',[0,2]),
             (2,0,'XZ',[0,3]),(2,3,'YZ',[1,4]),(2,6,'XX',[2,5]),
             (2,9,'YZZ',[0,3,4]),(2,2,'Y',[2]),
             (3,0,'XZZ',[0,3,6]),(3,4,'YZZ',[1,4,7]),
             (3,8,'XYZ',[2,5,8]),(3,12,'YXZ',[0,4,8]),(3,14,'Y',[7])]
    return [dict(id=f'c{i:02d}',body=b,feature=f,
                 encoding=gate(a,s,'adaptive',.5),trainable=gate(a,s,'adaptive',.5),
                 operation='append to both corresponding semantic blocks',sharing='template across combinations')
            for i,(b,f,a,s) in enumerate(specs)]

def edit_template(t, edit):
    t = deepcopy(t)
    for stage in t:
        t[stage][str(edit['body'])][edit['feature']].append(deepcopy(edit[stage]))
    return t

def instances(t, feature, theta):
    out=[]
    combinations={1:np.arange(10)[:,None],2:PAIRS,3:TRIPLES}
    for stage in ('encoding','trainable'):
        for b,n in COUNTS.items():
            for ci,mols in enumerate(combinations[b]):
                weight=1. if b==1 else float(feature[f'w{b}'][ci])
                if weight<=0: continue
                wires=[int(3*m+q) for m in mols for q in range(3)]
                for f in range(n):
                    for j,g in enumerate(t[stage][str(b)][f]):
                        key=parameter_key(b,f,j) if stage=='trainable' else None
                        value=theta[key] if key else float(feature[f'x{b}'][ci,f])
                        raw_angle=weight*g['scale']*value
                        minimum=g.get('encoding_min_abs_angle') if stage=='encoding' else None
                        angle=raw_angle if minimum is None else enforce_encoding_floor(raw_angle,minimum)
                        if minimum is not None and g['scale']!=1.:
                            raise ValueError('Floored encoding requires unit per-gate scale')
                        out.append(dict(stage=stage,body=b,feature=f,combination_index=ci,
                                        molecules=[int(m) for m in mols],scope=wires,
                                        axis=g['axis'],local_qubits=g['sites'],
                                        qubits=[wires[q] for q in g['sites']],origin=g['origin'],
                                        parameter=key,coefficient=weight*g['scale'],weight=weight,
                                        angle=angle))
                        if minimum is not None:
                            out[-1].update(encoding_min_abs_angle=minimum,encoding_raw_angle=raw_angle,
                                           encoding_angle_clamped=(angle!=raw_angle))
    return out

def append_rotation(qc, axis, wires, angle):
    """Exact exp(-i angle P/2). axis[k] acts on wires[k], not string endian."""
    if len(axis)==1:
        getattr(qc,'r'+axis.lower())(angle,wires[0]); return
    if axis[0] in 'XY' and set(axis[1:])=={'Z'}:
        for q in wires[1:]: qc.cz(wires[0],q)
        getattr(qc,'r'+axis[0].lower())(angle,wires[0])
        for q in reversed(wires[1:]): qc.cz(wires[0],q)
        return
    for a,q in zip(axis,wires):
        if a=='X': qc.h(q)
        elif a=='Y': qc.sdg(q); qc.h(q)
    for q in wires[:-1]: qc.h(wires[-1]); qc.cz(q,wires[-1]); qc.h(wires[-1])
    qc.rz(angle,wires[-1])
    for q in reversed(wires[:-1]): qc.h(wires[-1]); qc.cz(q,wires[-1]); qc.h(wires[-1])
    for a,q in reversed(list(zip(axis,wires))):
        if a=='X': qc.h(q)
        elif a=='Y': qc.h(q); qc.s(q)

def build_circuit(gates, shift=None, num_qubits=30, readout=True):
    from qiskit.quantum_info import Pauli
    qc=QuantumCircuit(num_qubits)
    for i,g in enumerate(gates):
        a=g['angle']+(shift[1] if shift and shift[0]==i else 0.)
        append_rotation(qc,g['axis'],g['qubits'],a)
    # Remove exact adjacent CZ inverse pairs introduced at group boundaries.
    # Logical Pauli-instance indexing remains unchanged for parameter shifts.
    reduced=[]
    for item in qc.data:
        wires=[qc.find_bit(q).index for q in item.qubits]
        if item.operation.name=='cz' and reduced and reduced[-1][0].name=='cz' and set(wires)==set(reduced[-1][1]):
            reduced.pop()
        else: reduced.append((item.operation,wires))
    qc=QuantumCircuit(num_qubits)
    for op,wires in reduced:qc.append(op,wires)
    if readout:
        for axis in ('X','Z'):
            for q in range(num_qubits): qc.save_expectation_value(Pauli(axis),[q],label=f'{axis}{q}')
    return qc
