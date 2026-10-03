"""Verify explicit force opt-in, frozen split guards, and row alignment."""
import h5py
import numpy as np
import pytest
from water10_v4.data import DATASET, load_panel


def test_force_labels_preserve_requested_order_and_units():
    with h5py.File(DATASET/'selected/water10.h5', 'r') as h:
        ids = h['sample_id'].asstr()[:]
        rows = np.flatnonzero(h['split'].asstr()[:] == 'train')[:3][::-1]
        expected = np.stack([h['forces_ev_per_angstrom'][i] for i in rows])
        wanted = ids[rows].tolist()
    panel = load_panel(wanted, include_forces=True)
    assert panel['sample_id'].tolist() == wanted
    assert panel['forces_ev_per_angstrom'].shape == (3, 30, 3)
    np.testing.assert_array_equal(panel['forces_ev_per_angstrom'], expected)
    assert 'forces_ev_per_angstrom' not in load_panel(wanted)


def test_force_loading_does_not_unlock_test_set():
    with pytest.raises(ValueError, match='sealed'):
        load_panel(split='test_id', include_forces=True)
