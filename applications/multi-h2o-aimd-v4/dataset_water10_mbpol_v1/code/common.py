"""Shared I/O: paths are explicit, in-project, atomic, and never overwrite frozen data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import numpy as np
import yaml

Z = np.tile([8, 1, 1], 10).astype(np.int32)
MOLECULE_ID = np.repeat(np.arange(10, dtype=np.int32), 3)

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(2**20), b''):
            h.update(b)
    return h.hexdigest()

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def coordinate_hash(x):
    a = np.asarray(x, dtype='<f8')
    if a.shape != (30, 3) or not np.isfinite(a).all():
        raise ValueError('Expected finite (30,3) coordinates in angstrom')
    return hashlib.sha256(a.tobytes(order='C')).hexdigest()

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def arguments(description, extra=None):
    p = argparse.ArgumentParser(description=description)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--project-root', type=Path)
    p.add_argument('--output-dir', type=Path)
    if extra:
        extra(p)
    a = p.parse_args()
    cfgpath = a.config.resolve(strict=True)
    c = yaml.safe_load(cfgpath.read_text())
    root = (a.project_root or cfgpath.parent / c['project_root']).resolve(strict=True)
    out = (a.output_dir or root / c['output_dir']).resolve()
    if not out.is_relative_to(root) or out == root:
        p.error('Output must be an independent directory inside --project-root')
    if c['dataset_id'] != 'water10_wb97mv_tzvppd_v1' or sum(c['splits'].values()) != 5000:
        p.error('This v1 implementation requires the fixed dataset identity and size 5000')
    if (out / 'selected/dataset_manifest.json').exists():
        manifest = json.loads((out / 'selected/dataset_manifest.json').read_text())
        if manifest.get('status') == 'FROZEN' and not getattr(a, 'read_only', False):
            p.error('Dataset is frozen; write a new version instead')
    for d in ['config','raw','candidates','manifests','reference_jobs','audit','selected','reports','scratch']:
        (out / d).mkdir(parents=True, exist_ok=True)
    c['_root'], c['_out'], c['_config'] = root, out, cfgpath
    return a, c

def read_json(path):
    return json.loads(Path(path).read_text())

def source_path(c, key):
    return (c['_root'] / c['sampling'][key]).resolve(strict=True)
