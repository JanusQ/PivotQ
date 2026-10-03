"""Re-export the final frozen circuit using its saved geometry; no training run needed."""
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from qiskit import qpy
from water10_v4.integration.fusion_framework.model import FrozenModel
from water10_v4.revision import primitive_manifest,build_block_circuit

root=Path(__file__).resolve().parents[1]
path=root/'models/final/best_model.json'
model=FrozenModel(path,hashlib.sha256(path.read_bytes()).hexdigest())
geometry=json.loads((root/'configs/fusion_geometry.json').read_text())
gates=model.gates(geometry['molecular_geometries_A'])[0]
out=root/'models/final/circuit_source'
out.mkdir(parents=True,exist_ok=True)
qc=build_block_circuit(gates,readout=False)
with (out/'selected_circuit.qpy').open('wb') as stream:qpy.dump(qc,stream)
sid=geometry['sample_ids'][0]
(out/'display_manifest.json').write_text(json.dumps(dict(sample_id=sid,gates=gates),indent=2)+'\n')
(out/'qiskit_primitive_manifest.json').write_text(json.dumps(dict(sample_id=sid,
 checkpoint_label='Full-data joint training | best epoch 6',gates=primitive_manifest(gates),
 primitive_gates=len(qc.data),depth=qc.depth()),indent=2)+'\n')
print(out)
