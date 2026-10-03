"""Frozen joint-training JSON model; no dataset reads or statistics refitting."""
import hashlib
import json
from pathlib import Path

import numpy as np

from ...circuit import instances, parameter_keys
from ...data import encode_features, features
from ... import mlp_full

FEATURE_NAMES = tuple(f'{axis}{q}' for axis in ('X', 'Z') for q in range(30))
ATOMIC_NUMBERS = [8, 1, 1] * 10


def geometries(value):
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 3 or array.shape[1:] != (30, 3) or not len(array):
        raise ValueError('Expected nonempty molecular_geometries_A with shape (B,30,3), OHH repeated ten times')
    if not np.isfinite(array).all():
        raise ValueError('Nonfinite geometry')
    return array


def readouts(value):
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 60 or not len(array):
        raise ValueError('Expected nonempty (B,60) readout, X0..X29 then Z0..Z29')
    if not np.isfinite(array).all() or np.any(np.abs(array) > 1 + 1e-6):
        raise ValueError('Invalid Pauli expectation')
    return array


class FrozenModel:
    def __init__(self, path, expected_sha256):
        raw = Path(path).read_bytes()
        self.sha256 = hashlib.sha256(raw).hexdigest()
        if self.sha256 != expected_sha256:
            raise ValueError('Model SHA256 mismatch')
        self.state = json.loads(raw)
        for key in ('templates', 'theta', 'normalizer', 'radii', 'network'):
            if key not in self.state:
                raise ValueError(f'Joint-training JSON model missing {key}; use best_model.json')
        if set(parameter_keys(self.state['templates'])) != set(self.state['theta']):
            raise ValueError('Quantum parameter keys do not match the frozen template')
        self.net = self.state['network']
        if self.net['widths'] != [60, 64, 32, 1]:
            raise ValueError('Expected the trained 60-64-32-1 tanh network')
        self.net['p'] = {k: np.asarray(v, dtype=np.float64) for k, v in self.net['p'].items()}
        for i, (a, b) in enumerate(zip(self.net['widths'], self.net['widths'][1:])):
            for name, shape in ((f'W{i}', (a, b)), (f'b{i}', (b,))):
                p = self.net['p'][name]
                if p.shape != shape or not np.isfinite(p).all():
                    raise ValueError('Invalid frozen MLP parameters')
        n = self.state['normalizer']
        if not np.isfinite([n['energy_mean_ev'], n['energy_scale_ev']]).all() or n['energy_scale_ev'] <= 0:
            raise ValueError('Invalid energy normalization')

    def gates(self, positions):
        batch = geometries(positions)
        s = self.state
        if s.get('encoding_version'):
            from ...dense_force.geometry import build_angles, ENCODING_VERSION
            import torch
            if s['encoding_version'] != ENCODING_VERSION:
                raise ValueError('Unsupported encoding version')
            result = []
            for positions in batch:
                gates, angles = build_angles(torch.tensor(positions, dtype=torch.float64),
                    s['theta'], s['templates'], s['normalizer'], s['radii'])
                result.append([dict(g, angle=float(a.detach())) for g, a in zip(gates, angles)])
            return result
        encoded = encode_features(features(batch, **s['radii']), s['normalizer'])
        return [instances(s['templates'], {k: encoded[k][i] for k in ('x1', 'x2', 'x3', 'w2', 'w3')}, s['theta'])
                for i in range(len(batch))]

    def energy(self, z):
        n = self.state['normalizer']
        return n['energy_mean_ev'] + n['energy_scale_ev'] * mlp_full.predict(self.net, readouts(z))
