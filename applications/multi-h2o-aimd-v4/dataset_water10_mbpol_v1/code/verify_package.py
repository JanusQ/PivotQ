"""Verify immutable data, relocated historical sources, and self-contained package files."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(2**20),b''):h.update(b)
 return h.hexdigest()
def main():
 frozen=json.loads((ROOT/'selected/dataset_manifest.json').read_text())
 for name,value in frozen['files'].items():assert sha(ROOT/name)==value,name
 reloc=json.loads((ROOT/'provenance/source_relocations.json').read_text())['paths']
 lock=json.loads((ROOT/'config/reference.lock.json').read_text())
 for name,value in lock['source_files'].items():assert sha(ROOT/reloc[name])==value,name
 manifest=json.loads((ROOT/'provenance/package_manifest.json').read_text())
 for name,value in manifest['files'].items():assert sha(ROOT/name)==value,name
 import h5py
 with h5py.File(ROOT/'selected/water10.h5') as h:
  assert h['positions_angstrom'].shape==(5000,30,3)
 print(json.dumps({'passed':True,'samples':5000,'frozen_files':len(frozen['files']),'package_files':len(manifest['files']),'historical_sources':len(reloc)}))
if __name__=='__main__':main()
