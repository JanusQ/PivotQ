"""Checkpoint loading must preserve every trained quantum and classical weight."""
import hashlib
import json
from pathlib import Path

import pytest
import torch

from water10_v4.dense_force.model import EnergyForceModel
from water10_v4.integration.fusion_framework.model import FrozenModel

MODEL = Path(__file__).resolve().parents[1]/'models/experimental/current_model.json'


def test_complete_json_model_roundtrip_and_classical_predictions():
    raw = MODEL.read_bytes()
    spec = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    model = EnergyForceModel.from_json(MODEL, library=None, expected_sha256=digest)
    exported = model.export()
    assert exported['theta'] == spec['theta']
    assert exported['network'] == spec['network']
    assert exported['normalizer'] == spec['normalizer']
    assert model.model_sha256 == digest
    # Independently compare the loaded PyTorch head with the fusion NumPy head.
    z = torch.linspace(-.8, .8, 60, dtype=torch.float64)[None]
    expected = FrozenModel(MODEL, digest).energy(z.numpy())
    actual = z
    for j in range(3):
        actual = actual @ model.classical[f'W{j}'] + model.classical[f'b{j}']
        if j < 2:
            actual = torch.tanh(actual)
    actual = spec['normalizer']['energy_mean_ev']+spec['normalizer']['energy_scale_ev']*actual[:, 0]
    torch.testing.assert_close(actual.detach(), torch.tensor(expected), atol=1e-12, rtol=0)


@pytest.mark.parametrize('corruption', ['shape', 'nonfinite', 'missing', 'encoding', 'normalizer'])
def test_bad_model_fails_before_statevector_allocation(tmp_path, corruption):
    spec = json.loads(MODEL.read_bytes())
    if corruption == 'shape':
        spec['network']['p']['W0'] = [[0.0]]
    elif corruption == 'nonfinite':
        spec['theta'][next(iter(spec['theta']))] = float('nan')
    elif corruption == 'missing':
        del spec['network']['p']['b2']
    elif corruption == 'encoding':
        spec['encoding_version'] = 'legacy_encoding'
    else:
        spec['normalizer']['energy_scale_ev'] = 0.0
    path = tmp_path/'model.json'
    path.write_text(json.dumps(spec))
    with pytest.raises(ValueError):
        EnergyForceModel.from_json(path, library=None)


def test_model_sha256_mismatch():
    with pytest.raises(ValueError, match='SHA256'):
        EnergyForceModel.from_json(MODEL, library=None, expected_sha256='0'*64)
