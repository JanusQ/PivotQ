"""Exact connected-component operator/state verification on pcie5.

The union of both circuits' interaction graphs factors the 30-wire unitary into
independent components (largest is six wires for this frozen input). This is an
exact factorization, not qubit removal, an MPS approximation, or circuit cutting.
"""
from pathlib import Path
import hashlib,json,platform,resource,time
import numpy as np
import qiskit
from qiskit import QuantumCircuit,qpy
from qiskit.quantum_info import Operator,Statevector

root=Path(__file__).resolve().parent
stem='water10_stateprep_symbolic_rx_rz_cz_opt3'
with (root/f'{stem}.reference.qpy').open('rb') as f:original=qpy.load(f)[0]
with (root/f'{stem}.bound.qpy').open('rb') as f:compiled=qpy.load(f)[0]
assert compiled.num_qubits==30 and compiled.num_clbits==0 and not compiled.parameters
assert set(compiled.count_ops())=={'rx','rz','cz'}
components=[{i} for i in range(30)]
for circuit in (original,compiled):
    for inst in circuit.data:
        sites={circuit.find_bit(q).index for q in inst.qubits}
        touched=[c for c in components if c & sites]
        union=set().union(*touched)
        components=[c for c in components if not c & sites]+[union]
components=sorted([sorted(c) for c in components],key=lambda c:c[0])
assert max(map(len,components))<=10,'Refuse unexpectedly large dense operator allocation'

def extract(circuit,sites):
    mapping={q:i for i,q in enumerate(sites)}
    reduced=QuantumCircuit(len(sites))
    for inst in circuit.data:
        qs=[circuit.find_bit(q).index for q in inst.qubits]
        if any(q in mapping for q in qs):
            assert all(q in mapping for q in qs)
            reduced.append(inst.operation,[mapping[q] for q in qs])
    return reduced

start=time.perf_counter()
records=[]
phase_product=np.exp(1j*(float(original.global_phase)-float(compiled.global_phase)))
for sites in components:
    a,b=extract(original,sites),extract(compiled,sites)
    ua,ub=Operator(a).data,Operator(b).data
    phase=np.vdot(ub,ua)/ua.shape[0]
    unit_phase=phase/abs(phase)
    error=float(np.max(np.abs(ua-unit_phase*ub)))
    va,vb=Statevector.from_instruction(a).data,Statevector.from_instruction(b).data
    fidelity=float(abs(np.vdot(vb,va))**2)
    phase_product*=unit_phase
    records.append(dict(qubits=sites,operator_max_abs_error_up_to_phase=error,
                        state_fidelity=fidelity,relative_phase_rad=float(np.angle(unit_phase))))
max_error=max(r['operator_max_abs_error_up_to_phase'] for r in records)
fidelity=float(np.prod([r['state_fidelity'] for r in records]))
phase_error=float(abs(phase_product-1))
report=dict(passed=max_error<1e-10 and abs(fidelity-1)<1e-10 and phase_error<1e-10,
    verification='exact dense operators and statevectors on all components of the union interaction graph',
    factorization_is_exact=True,num_qubits=30,largest_component_qubits=max(map(len,components)),
    max_component_operator_error=max_error,full_prepared_state_fidelity=fidelity,
    global_phase_consistency_error=phase_error,acceptance_absolute_error=1e-10,components=records,
    original_sha256=hashlib.sha256((root/f'{stem}.reference.qpy').read_bytes()).hexdigest(),
    compiled_sha256=hashlib.sha256((root/f'{stem}.bound.qpy').read_bytes()).hexdigest(),
    qiskit_version=qiskit.__version__,python=platform.python_version(),
    backend='qiskit.quantum_info.Operator/Statevector, complex128, CPU',threads=1,
    seconds=time.perf_counter()-start,max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
(root/f'{stem}.verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='components'},indent=2))
assert report['passed'],report
