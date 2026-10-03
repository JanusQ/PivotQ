"""Read frozen MB-pol data and derive v4 features without changing labels."""
from itertools import combinations
from pathlib import Path
import hashlib
import json

import h5py
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'dataset_water10_mbpol_v1'
PAIRS = np.array(list(combinations(range(10), 2)), dtype=int)
TRIPLES = np.array(list(combinations(range(10), 3)), dtype=int)


def load_panel(sample_ids=None, *, split='train', allow_test=False, include_forces=False, root=DATASET):
    """Read only requested HDF5 rows, preserving the caller's ID order."""
    allowed = {'train', 'validation'}
    if allow_test:
        allowed.update({'test_id', 'test_trajectory', 'test_ood'})
    if split not in allowed:
        raise ValueError('Unknown or sealed split: ' + split)
    with h5py.File(Path(root) / 'selected/water10.h5', 'r') as h:
        ids, splits = h['sample_id'].asstr()[:], h['split'].asstr()[:]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate source sample IDs')
        rows = np.flatnonzero(splits == split)
        if sample_ids is not None:
            requested = list(sample_ids)
            if not requested or len(set(requested)) != len(requested):
                raise ValueError('Expected nonempty unique sample IDs')
            lookup = {sid: i for i, sid in enumerate(ids)}
            rows = np.array([lookup[sid] for sid in requested], dtype=int)
        if not len(rows) or not np.all(splits[rows] == split):
            raise ValueError('Empty panel or sample from another split')
        if not np.array_equal(h['atomic_numbers'][:], np.tile([8, 1, 1], 10)):
            raise ValueError('Expected fixed OHH atom order')
        if not np.array_equal(h['molecule_id'][:], np.repeat(np.arange(10), 3)):
            raise ValueError('Expected molecule IDs 0..9')
        if np.any(h['pbc'][:]):
            raise ValueError('This adapter supports the frozen nonperiodic dataset only')
        if h.attrs['energy_unit'] != 'eV' or h.attrs['position_unit'] != 'angstrom':
            raise ValueError('Unexpected units')
        if h.attrs['label_source'] != 'MB-pol' or bool(h.attrs['is_dft']):
            raise ValueError('Unexpected label provenance')
        order = np.argsort(rows)
        inverse = np.argsort(order)
        def read(key):
            return h[key][rows[order]][inverse]
        positions, energy = read('positions_angstrom'), read('energy_ev')
        if not np.isfinite(positions).all() or not np.isfinite(energy).all():
            raise ValueError('Nonfinite coordinates or labels')
        result = dict(sample_id=ids[rows], split=splits[rows],
                    category=h['category'].asstr()[rows[order]][inverse],
                    positions_angstrom=positions, energy_ev=energy)
        if include_forces:
            if h.attrs.get('force_unit') != 'eV/angstrom':
                raise ValueError('Unexpected force units')
            forces = read('forces_ev_per_angstrom')
            if forces.shape != positions.shape or not np.isfinite(forces).all():
                raise ValueError('Invalid force labels')
            result['forces_ev_per_angstrom'] = forces
        return result


def smooth_switch(distance, r_on, r_off):
    if not 0 <= r_on < r_off:
        raise ValueError('Expected 0 <= r_on < r_off')
    t = np.clip((distance-r_on)/(r_off-r_on), 0., 1.)
    return np.clip(1-10*t**3+15*t**4-6*t**5, 0., 1.)


def features(positions, *, pair_radii=(4.5, 6.5), triple_radii=(3., 4.5)):
    """Return all lexicographic combinations; active masks select weight > 0."""
    r = np.asarray(positions, dtype=np.float64)
    if r.shape[-2:] != (30, 3) or not np.isfinite(r).all():
        raise ValueError('Expected finite [...,30,3] coordinates')
    xyz = r.reshape(*r.shape[:-2], 10, 3, 3)
    oxygen = xyz[..., 0, :]
    bonds = xyz[..., 1:, :] - oxygen[..., None, :]
    lengths = np.linalg.norm(bonds, axis=-1)
    if np.any(lengths < 1e-8):
        raise ValueError('Degenerate OH bond')
    u = bonds / lengths[..., None]
    theta = np.arccos(np.clip(np.sum(u[..., 0, :]*u[..., 1, :], axis=-1), -1., 1.))
    bisector = u.sum(axis=-2)
    norm = np.linalg.norm(bisector, axis=-1)
    if np.any(norm < 1e-8):
        raise ValueError('Undefined HOH bisector')
    bisector /= norm[..., None]
    projection = np.linalg.norm(bisector[..., :2], axis=-1)
    alpha = (np.arctan2(bisector[..., 1], bisector[..., 0])+np.pi) % (2*np.pi)-np.pi
    pole = projection < 1e-12
    alpha = np.where(pole, 0., alpha)
    beta = np.arctan2(projection, bisector[..., 2])
    x1 = np.concatenate([lengths, theta[..., None]], axis=-1)
    g = np.concatenate([oxygen, alpha[..., None], beta[..., None]], axis=-1)
    d = np.linalg.norm(oxygen[..., :, None, :]-oxygen[..., None, :, :], axis=-1)
    i, j = PAIRS.T
    if np.any(d[..., i, j] < 1e-8):
        raise ValueError('Coincident oxygen atoms')
    w2 = smooth_switch(d[..., i, j], *pair_radii)
    i, j, k = TRIPLES.T
    a = smooth_switch(d[..., i, j], *triple_radii)
    b = smooth_switch(d[..., i, k], *triple_radii)
    c = smooth_switch(d[..., j, k], *triple_radii)
    w3 = np.clip(a*b+a*c+b*c-2*a*b*c, 0., 1.)
    return dict(x1=x1, g=g,
                x2=g[..., PAIRS, :].reshape(*g.shape[:-2], 45, 10),
                x3=g[..., TRIPLES, :].reshape(*g.shape[:-2], 120, 15),
                pair_index=PAIRS.copy(), triple_index=TRIPLES.copy(),
                w2=w2, w3=w3, active_pairs=w2 > 0, active_triples=w3 > 0,
                pole_mask=pole, qubit_map=np.arange(30).reshape(10, 3))


def fit_normalizer(panel):
    if not np.all(np.asarray(panel['split']) == 'train'):
        raise ValueError('Fit only on the actual training panel')
    raw = features(panel['positions_angstrom'])
    # Pool H1/H2 bond lengths; pool each Cartesian component across all waters.
    oh = raw['x1'][..., :2].ravel()
    oxygen = raw['g'][..., :3].reshape(-1, 3)
    energy = panel['energy_ev']
    return dict(train_ids=list(panel['sample_id']),
                oh_mean=float(oh.mean()), oh_scale=max(float(oh.std()), 1e-8),
                oxygen_mean=oxygen.mean(0).tolist(),
                oxygen_scale=np.maximum(oxygen.std(0), 1e-8).tolist(),
                energy_mean_ev=float(energy.mean()),
                energy_scale_ev=max(float(energy.std()), 1e-8),
                scale_floor=1e-8, angle_policy='raw_radians',
                coordinate_policy='unchanged_hdf5_global_frame')


def encode_features(raw, normalizer):
    """Normalize lengths/coordinates only; leave all three angle types in radians."""
    result = dict(raw)
    x1, g = raw['x1'].copy(), raw['g'].copy()
    x1[..., :2] = np.pi/2*np.tanh((x1[..., :2]-normalizer['oh_mean'])/normalizer['oh_scale'])
    g[..., :3] = np.pi/2*np.tanh((g[..., :3]-normalizer['oxygen_mean'])/normalizer['oxygen_scale'])
    result.update(x1=x1, g=g,
                  x2=g[..., PAIRS, :].reshape(*g.shape[:-2], 45, 10),
                  x3=g[..., TRIPLES, :].reshape(*g.shape[:-2], 120, 15))
    return result


def stratified_ids(ids, categories, count):
    """Largest-remainder category counts, SHA256 ID ranking; no label access."""
    ids, categories = np.asarray(ids), np.asarray(categories)
    if not 0 < count <= len(ids):
        raise ValueError('Invalid panel size')
    names, counts = np.unique(categories, return_counts=True)
    quotas = counts*count/len(ids)
    sizes = np.floor(quotas).astype(int)
    for i in sorted(range(len(names)), key=lambda i: (-(quotas[i]-sizes[i]), names[i]))[:count-int(sizes.sum())]:
        sizes[i] += 1
    rank = lambda sid: hashlib.sha256(str(sid).encode()).hexdigest()
    selected = []
    for name, size in zip(names, sizes):
        selected.extend(sorted(ids[categories == name], key=rank)[:size])
    return sorted(selected, key=rank)


def make_panels(root=DATASET):
    nested = json.loads((Path(root)/'selected/nested_train_ids.json').read_text())
    with h5py.File(Path(root)/'selected/water10.h5') as h:
        ids, splits, category = [h[k].asstr()[:] for k in ('sample_id', 'split', 'category')]
    lookup = {sid: i for i, sid in enumerate(ids)}
    train = nested['250']
    rows = [lookup[sid] for sid in train]
    if not np.all(splits[rows] == 'train'):
        raise ValueError('Nested panel crosses frozen splits')
    validation = splits == 'validation'
    return dict(train_250=train,
                pilot_train_32=stratified_ids(train, category[rows], 32),
                validation_64=stratified_ids(ids[validation], category[validation], 64),
                selection='largest remainder categories; SHA256(sample_id); no labels',
                test_labels_accessed=False)
