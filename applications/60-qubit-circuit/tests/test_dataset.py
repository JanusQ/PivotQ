import hashlib
import json

import h5py
import numpy as np

from water20.dataset import validate_geometry
from water20.model import ROOT


def test_dataset_units_full_labels_hashes_and_group_separation():
    directory = ROOT/"dataset_water20_mbpol_v1"
    manifest = json.loads((directory/"manifest.json").read_text())
    target = directory/"water20.h5"
    assert hashlib.sha256(target.read_bytes()).hexdigest() == manifest["dataset_sha256"]
    with h5py.File(target) as h:
        assert h["positions_angstrom"].shape == (5000, 60, 3)
        assert h["forces_ev_per_angstrom"].shape == (5000, 60, 3)
        assert h.attrs["label_source"] == "MB-pol" and not h.attrs["is_dft"] and not h.attrs["pbc"]
        assert h.attrs["energy_unit"] == "eV" and h.attrs["force_unit"] == "eV/angstrom"
        assert np.array_equal(h["atomic_numbers"][:], [8, 1, 1]*20)
        ids, splits, groups = h["sample_id"].asstr()[:], h["split"].asstr()[:], h["group_id"][:]
        assert len(set(ids)) == 5000
        for group in np.unique(groups):
            assert len(set(splits[groups == group])) == 1
        assert {s: int((splits == s).sum()) for s in set(splits)} == manifest["splits"]
        for start in range(0, 5000, 100):
            x = h["positions_angstrom"][start:start+100]
            force = h["forces_ev_per_angstrom"][start:start+100]
            assert np.isfinite(x).all() and np.isfinite(force).all()
            for row in x:
                validate_geometry(row)
        assert np.isfinite(h["energy_ev"][:]).all()
        normalizer = json.loads((directory/"normalizer.json").read_text())
        train = splits == "train"
        assert normalizer["train_count"] == 3500
        assert normalizer["energy_mean_ev"] == np.mean(h["energy_ev"][:][train])
        assert normalizer["train_ids_sha256"] == hashlib.sha256("\n".join(ids[train]).encode()).hexdigest()
