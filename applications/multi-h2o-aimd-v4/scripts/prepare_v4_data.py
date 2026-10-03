"""Verify the immutable copy and audit v4 adaptation on pcie5; no training."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import h5py
import numpy as np
from water10_v4.data import (DATASET, features, load_panel, fit_normalizer,
                            encode_features, make_panels)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(2**20), b''):
            h.update(block)
    return h.hexdigest()


def main():
    inventory = json.loads((ROOT/'data_v4/dataset_manifest.json').read_text())
    actual = {str(p.relative_to(DATASET)) for p in DATASET.rglob('*') if p.is_file() or p.is_symlink()}
    assert actual == set(inventory['files']), 'Dataset inventory differs'
    for name, entry in inventory['files'].items():
        p = DATASET/name
        if 'symlink' in entry:
            assert str(p.readlink()) == entry['symlink'], name
        else:
            assert sha(p) == entry['sha256'], name
    package_check = subprocess.check_output(
        [sys.executable, '-B', str(DATASET/'code/verify_package.py')], text=True)
    panels = make_panels()
    save(ROOT/'data_v4/panels.json', panels)
    report = dict(status='passed', host=platform.node(), python=sys.executable,
                  dataset_files_verified=len(actual), source_package_check=json.loads(package_check),
                  training_executed=False, test_labels_accessed=False, panels={}, geometry_splits={})
    # Check geometry compatibility on ALL splits, without opening test energy/force values.
    with h5py.File(DATASET/'selected/water10.h5') as h:
        splits = h['split'].asstr()[:]
        report['split_counts'] = dict(Counter(splits))
        for split in sorted(set(splits)):
            rows = np.flatnonzero(splits == split)
            raw = features(h['positions_angstrom'][rows])
            assert raw['x1'].shape == (len(rows), 10, 3)
            assert raw['x2'].shape == (len(rows), 45, 10)
            assert raw['x3'].shape == (len(rows), 120, 15)
            assert all(np.isfinite(raw[k]).all() for k in ('x1','x2','x3','w2','w3'))
            report['geometry_splits'][split] = dict(samples=len(rows),
                pole_count=int(raw['pole_mask'].sum()),
                active_pairs_min=int(raw['active_pairs'].sum(-1).min()),
                active_pairs_max=int(raw['active_pairs'].sum(-1).max()),
                active_triples_min=int(raw['active_triples'].sum(-1).min()),
                active_triples_max=int(raw['active_triples'].sum(-1).max()))
    for name, split in [('pilot_train_32','train'), ('train_250','train'), ('validation_64','validation')]:
        panel = load_panel(panels[name], split=split)
        assert list(panel['sample_id']) == panels[name]
        report['panels'][name] = dict(count=len(panel['sample_id']), categories=dict(Counter(panel['category'])))
        if split == 'train':
            normalizer = fit_normalizer(panel)
            save(ROOT/f'data_v4/normalizer_{name}.json', normalizer)
            raw = features(panel['positions_angstrom'])
            enc = encode_features(raw, normalizer)
            assert np.array_equal(raw['x1'][...,2], enc['x1'][...,2])
            assert np.array_equal(raw['g'][...,3:], enc['g'][...,3:])
            y = (panel['energy_ev']-normalizer['energy_mean_ev'])/normalizer['energy_scale_ev']
            assert np.allclose(y*normalizer['energy_scale_ev']+normalizer['energy_mean_ev'], panel['energy_ev'])
    # Independent known geometry: r1=r2=1, HOH=pi/2, bisector +x, alpha=0, beta=pi/2.
    toy = np.zeros((10,3,3))
    toy[:,0,0] = np.arange(10)*10.
    toy[:,1] = toy[:,0]+np.array([1.,1.,0.])/np.sqrt(2)
    toy[:,2] = toy[:,0]+np.array([1.,-1.,0.])/np.sqrt(2)
    raw = features(toy.reshape(30,3))
    assert np.allclose(raw['x1'], [1.,1.,np.pi/2])
    assert np.allclose(raw['g'][:,3:], [0.,np.pi/2])
    assert not raw['active_pairs'].any() and not raw['active_triples'].any()
    toy[:,1] = toy[:,0]+np.array([1.,0.,1.])/np.sqrt(2)
    toy[:,2] = toy[:,0]+np.array([-1.,0.,1.])/np.sqrt(2)
    pole = features(toy.reshape(30,3))
    assert pole['pole_mask'].all() and np.allclose(pole['g'][:,3:], 0.)
    # Sharing one center with two neighbours gives w3=1 even when the outer edge is off.
    toy[:,0,0] = np.arange(10)*10.
    toy[:3,0,0] = [0.,2.5,-2.5]
    toy[:,1] = toy[:,0]+np.array([1.,1.,0.])/np.sqrt(2)
    toy[:,2] = toy[:,0]+np.array([1.,-1.,0.])/np.sqrt(2)
    assert np.isclose(features(toy.reshape(30,3))['w3'][0], 1.)
    for action in (lambda: load_panel(split='test_id'),
                   lambda: load_panel(panels['validation_64'],split='train'),
                   lambda: fit_normalizer(load_panel(panels['validation_64'],split='validation')),
                   lambda: features(np.zeros((30,3)))):
        try:
            action()
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid input was accepted')
    report['checks'] = ['296-file SHA256 copy verification', 'upstream frozen manifests',
                        '5000 geometry feature shapes/finiteness', 'requested ID order',
                        'energy normalization roundtrip', 'angles unchanged by normalization',
                        'independent analytic geometry', 'polar convention',
                        'v4 center-connected triple switch', 'test/split/normalizer/degeneracy guards']
    save(ROOT/'reports/dataset_adaptation_report.json', report)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
