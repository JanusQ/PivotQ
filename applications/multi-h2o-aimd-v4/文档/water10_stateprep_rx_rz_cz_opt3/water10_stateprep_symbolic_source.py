"""Keep the 48 shared trainable parameters symbolic before opt=3 compilation."""
from pathlib import Path
import csv,json,re,subprocess,hashlib
import xml.etree.ElementTree as ET
import qiskit
from qiskit import QuantumCircuit,qpy,transpile
from qiskit.circuit import Parameter
import resvg_py
from PIL import Image
import water10_stateprep_source as drawing

OUT=Path(__file__).resolve().parent
SOURCE=drawing.SOURCE
STEM='water10_stateprep_symbolic_rx_rz_cz_opt3'
model=json.loads((SOURCE.parent/'best_model.json').read_text())
semantic=json.loads((SOURCE/'display_manifest.json').read_text())
primitives=json.loads((SOURCE/'qiskit_primitive_manifest.json').read_text())['gates']
keys=[f'b{b}_f{f}_g{j}' for b,n in ((1,3),(2,10),(3,15)) for f in range(n)
      for j in range(len(model['templates']['trainable'][str(b)][f]))]
assert len(keys)==48 and set(keys)==set(model['theta'])
parameters={key:Parameter(f'theta{i+1}') for i,key in enumerate(keys)}
original=QuantumCircuit(30)
seen_groups=set()
for p in primitives:
    args=p['params'].copy()
    if args and p['parameter'] is not None:
        g=semantic['gates'][p['group']]
        assert g['stage']=='trainable' and len(args)==1 and p['group'] not in seen_groups
        assert abs(args[0]-g['angle'])<1e-12
        assert abs(args[0]-g['coefficient']*model['theta'][g['parameter']])<1e-12
        args=[g['coefficient']*parameters[g['parameter']]]
        seen_groups.add(p['group'])
    getattr(original,p['name'])(*args,*p['qubits'])
assert len(seen_groups)==sum(g['parameter'] is not None for g in semantic['gates'])
bindings={parameters[k]:float(model['theta'][k]) for k in keys}
with (SOURCE/'selected_circuit.qpy').open('rb') as f:reference=qpy.load(f)[0]
bound_original=original.assign_parameters(bindings)
assert bound_original==reference
compiled=transpile(original,basis_gates=['rx','rz','cz'],optimization_level=3,
                   approximation_degree=1.0,seed_transpiler=916)
assert set(compiled.count_ops())<= {'rx','rz','cz'}
assert set(compiled.parameters)==set(parameters.values())
bound=compiled.assign_parameters(bindings)
for suffix,circuit in [('logical.qpy',original),('qpy',compiled),('bound.qpy',bound),('reference.qpy',reference)]:
    with (OUT/f'{STEM}.{suffix}').open('wb') as f:qpy.dump(circuit,f)
    with (OUT/f'{STEM}.{suffix}').open('rb') as f:assert qpy.load(f)[0]==circuit
mapping=[dict(symbol=f'theta{i+1}',display=f'θ{i+1}',parameter_key=k,
              checkpoint_value=float(model['theta'][k]),body=int(k[1]),
              occurrence_count=sum(g['parameter']==k for g in semantic['gates'])) for i,k in enumerate(keys)]
(OUT/f'{STEM}.parameters.json').write_text(json.dumps(mapping,indent=2,ensure_ascii=False)+'\n')

def display(value):
    if not getattr(value,'parameters',set()):return f'{float(value):+.6f}'
    # Only display coefficients are rounded; QPY and CSV keep the exact expression.
    text=str(value).replace('theta','θ')
    text=re.sub(r'(?<![\w.])(?:\d+\.\d+)(?:[eE][+-]?\d+)?',lambda m:format(float(m[0]),'.5g'),text)
    return text.replace('*','·').replace(' ','')

ops=[]
for i,inst in enumerate(compiled.data):
    ops.append(dict(index=i,name=inst.operation.name,qubits=[compiled.find_bit(q).index for q in inst.qubits],
                    angles_rad=[display(v) for v in inst.operation.params],
                    exact_expression=[str(v) for v in inst.operation.params],
                    trainable=any(getattr(v,'parameters',set()) for v in inst.operation.params)))
ops,columns=drawing.schedule(ops)
for q in range(30):
    cs=[op['column'] for op in ops if q in op['qubits']];assert cs==sorted(set(cs))
max_label=max(len(op['name'])+2+len(op['angles_rad'][0]) for op in ops if op['angles_rad'])
pitch=max(144,max_label*7+28)
meta=dict(sample_id=semantic['sample_id'],qiskit_version=qiskit.__version__,parameters=48,
    compiled=dict(count_ops=dict(compiled.count_ops()),depth=compiled.depth(),
                  global_phase_rad=float(compiled.global_phase)),
    column_pitch=pitch,angle_note='Trainable angles: θ1–θ48 (shared symbols retain their coefficients). Encoding angles: fixed numbers. QPY/CSV retain full expressions.',
    training_parameters_symbolic=True,original_bind_matches_frozen_qpy=True,
    bound_checkpoint_qpy=f'{STEM}.bound.qpy',basis_gates=['rx','rz','cz'],optimization_level=3,
    approximation_degree=1.0,seed_transpiler=916,display_columns=columns,fold=False)
drawing.STEM=STEM
diagram,width,height=drawing.diagram(ops,columns,meta)
# The parameterized view is not a frozen-parameter instance.
tree=ET.parse(diagram)
for cell in tree.getroot().iter('mxCell'):
    if cell.get('id')=='details':cell.set('value',cell.get('value').replace('Frozen best epoch 6','48 shared trainable parameters'))
tree.write(diagram,encoding='utf-8',xml_declaration=True)
with (OUT/f'{STEM}.gates.csv').open('w',newline='') as f:
    w=csv.writer(f);w.writerow(['index','display_column','gate','qubits','exact_parameter_expression','trainable'])
    for op in ops:w.writerow([op['index'],op['column'],op['name'],' '.join(map(str,op['qubits'])), ';'.join(op['exact_expression']),op['trainable']])
svg=OUT/f'{STEM}.svg'
subprocess.run([drawing.DRAWIO,'--export','--format','svg','--theme','light','--border','0','--output',str(svg),str(diagram)],check=True)
drawing.vector_text(svg,diagram)
(OUT/f'{STEM}.png').write_bytes(resvg_py.svg_to_bytes(svg_path=str(svg)))
with Image.open(OUT/f'{STEM}.png') as im:
    meta['png_size']=list(im.size);im.thumbnail((3600,300));im.save(OUT/f'{STEM}.preview.png')
meta['rotation_labels_with_symbols']=sum(op['trainable'] for op in ops)
meta['max_display_label_characters']=max_label
(OUT/f'{STEM}.metadata.json').write_text(json.dumps(meta,indent=2,ensure_ascii=False)+'\n')
print(json.dumps(meta,indent=2,ensure_ascii=False))
