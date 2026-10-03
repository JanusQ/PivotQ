"""Cheap orchestration tests; these deliberately do not claim 30-qubit evidence."""
import hashlib
import json

from ase.io import read
import numpy as np
import pytest
import torch

from water10_v4.dense_force import smoke


def _stub_runtime(monkeypatch, tmp_path, nonfinite=False):
    calls = []
    class Toy:
        def energy_forces(self, positions):
            calls.append(1)
            energy = .01 * positions.square().sum()
            force = -.02 * positions
            if nonfinite:
                force[0, 0] = float('nan')
            return energy, force
    library = tmp_path/'library.so'
    library.write_bytes(b'test library only')
    monkeypatch.setattr(smoke, 'require_memory_budget', lambda required: {'required_gib': required})
    monkeypatch.setattr(smoke, 'build_library', lambda path: library)
    monkeypatch.setattr(smoke.EnergyForceModel, 'from_json', lambda *a, **kw: Toy())
    return calls


def test_short_md_persists_two_frames_and_checkable_evidence(tmp_path, monkeypatch):
    calls = _stub_runtime(monkeypatch, tmp_path)
    out = tmp_path/'smoke'
    summary = smoke.run_smoke(out)
    assert summary['status'] == 'succeeded'
    assert summary['scientific_status'] == 'not_validated'
    assert summary['frames'] == 2
    assert summary['completed_steps'] == 1
    assert summary['completed_time_fs'] == .1
    assert len(calls) == 2
    with np.load(out/'frame_000000.npz') as first, np.load(out/'frame_000001.npz') as last:
        assert first['forces_ev_per_A'].shape == (30, 3)
        assert float(first['energy_ev']) == summary['initial_energy_ev']
        assert not np.array_equal(first['positions_A'], last['positions_A'])
    assert len(read(out/'trajectory.traj', ':')) == 2
    assert len(read(out/'trajectory.extxyz', ':')) == 2
    validation = json.loads((out/'validation.json').read_text())
    assert validation['status'] == 'passed' and validation['coordinates_changed']
    manifest = json.loads((out/'artifacts.json').read_text())
    for name, entry in manifest.items():
        assert hashlib.sha256((out/name).read_bytes()).hexdigest() == entry['sha256']
    with pytest.raises(FileExistsError):
        smoke.run_smoke(out)


def test_nonfinite_force_records_failure_and_raises(tmp_path, monkeypatch):
    _stub_runtime(monkeypatch, tmp_path, nonfinite=True)
    out = tmp_path/'smoke'
    with pytest.raises(FloatingPointError):
        smoke.run_smoke(out)
    summary = json.loads((out/'summary.json').read_text())
    assert summary['status'] == 'failed' and summary['frames'] == 0
    assert json.loads((out/'validation.json').read_text())['status'] == 'failed'


def test_insufficient_memory_does_not_build_library(tmp_path, monkeypatch):
    def reject(_):
        raise MemoryError('test container has insufficient memory')
    monkeypatch.setattr(smoke, 'require_memory_budget', reject)
    monkeypatch.setattr(smoke, 'build_library', lambda _: pytest.fail('allocated before preflight'))
    out = tmp_path/'smoke'
    with pytest.raises(MemoryError):
        smoke.run_smoke(out)
    assert json.loads((out/'summary.json').read_text())['status'] == 'failed'
