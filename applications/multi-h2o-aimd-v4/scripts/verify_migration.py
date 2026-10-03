"""Verify byte-preserved model/data resources against the migration source."""
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / 'provenance/migration_manifest.json').read_text())
    checked = {}
    for name, expected in manifest['files'].items():
        if not name.startswith(('models/', 'dataset_water10_mbpol_v1/', 'data_v4/')):
            continue
        digest = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if digest != expected:
            raise ValueError(f'Migrated resource differs from source: {name}')
        checked[name] = digest
    for name, expected in manifest.get('symlinks', {}).items():
        path = root / name
        if not path.is_symlink() or str(path.readlink()) != expected or not path.exists():
            raise ValueError(f'Migrated symlink differs from source: {name}')
    with h5py.File(root / 'dataset_water10_mbpol_v1/selected/water10.h5', 'r') as data:
        if data['positions_angstrom'].shape != (5000, 30, 3) \
                or data['forces_ev_per_angstrom'].shape != (5000, 30, 3) \
                or data['energy_ev'].shape != (5000,):
            raise ValueError('Unexpected frozen dataset shapes')
        if not np.array_equal(data['atomic_numbers'][:], [8, 1, 1] * 10):
            raise ValueError('Unexpected frozen atom order')
        labels, counts = np.unique(data['split'].asstr()[:], return_counts=True)
        splits = dict(zip(labels.tolist(), counts.tolist()))
        if splits != {'train': 3500, 'validation': 500, 'test_id': 500,
                      'test_trajectory': 250, 'test_ood': 250}:
            raise ValueError('Unexpected frozen dataset split')
    print(json.dumps({'passed': True, 'source_commit': manifest['source_commit'],
                      'immutable_files': len(checked),
                      'symlinks': len(manifest.get('symlinks', {})),
                      'samples': 5000, 'splits': splits}, indent=2))


if __name__ == '__main__':
    main()
