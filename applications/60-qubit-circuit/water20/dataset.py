"""Seeded independent MB-pol trajectories, compact labels, group isolation."""
from concurrent.futures import ProcessPoolExecutor
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import time

import h5py
import numpy as np
from ase import Atoms, units
from ase.md.langevin import Langevin
from ase.md.velocitydistribution import MaxwellBoltzmannDistribution, Stationary, ZeroRotation
from ase.optimize import FIRE
from scipy.spatial.transform import Rotation

from .reference import MBX


def validate_geometry(x):
    x = np.asarray(x)
    if x.shape != (60, 3) or not np.isfinite(x).all():
        raise ValueError("Expected finite (60,3) geometry")
    xyz = x.reshape(20, 3, 3)
    bonds = xyz[:, 1:] - xyz[:, :1]
    lengths = np.linalg.norm(bonds, axis=-1)
    cosine = np.sum(bonds[:, 0] * bonds[:, 1], axis=-1) / np.prod(lengths, axis=1)
    angles = np.degrees(np.arccos(np.clip(cosine, -1, 1)))
    d = np.linalg.norm(x[:, None] - x[None, :], axis=-1)
    inter = np.repeat(np.arange(20), 3)
    minimum = d[inter[:, None] != inter[None, :]].min()
    if lengths.min() < .75 or lengths.max() > 1.25 or angles.min() < 70 or angles.max() > 145 or minimum < .85:
        raise ValueError("Geometry outside water20 sampling domain")


def initial_cluster(rng):
    """Twenty genuine waters in a compact nonperiodic cluster; no reused data."""
    grid = np.array(list(np.ndindex(3, 3, 3)), float)
    grid = grid[np.argsort(np.linalg.norm(grid - 1, axis=1), kind="stable")[:20]]
    oxygens = (grid - grid.mean(0)) * 2.8 + rng.normal(0, .06, (20, 3))
    angle, length = np.radians(104.52), .9572
    monomer = np.array([[0, 0, 0], [length, 0, 0], [length*np.cos(angle), length*np.sin(angle), 0]])
    for _ in range(1000):
        xyz = np.stack([monomer @ Rotation.random(random_state=rng).as_matrix().T + o for o in oxygens]).reshape(60, 3)
        try:
            validate_geometry(xyz)
            return xyz
        except ValueError:
            continue
    raise RuntimeError("Cannot generate a clash-free water20 cluster")


def _group(arguments):
    group, split, config, library = arguments
    os.environ["OMP_NUM_THREADS"] = "1"
    rng = np.random.default_rng(np.random.SeedSequence([config["seed"], group]))
    reference = MBX(library, config["mbx_settings"])
    atoms = Atoms(numbers=[8, 1, 1]*20, positions=initial_cluster(rng), pbc=False)
    atoms.calc = reference
    optimizer = FIRE(atoms, logfile=None, maxstep=.035, dt=.025)
    optimizer.run(fmax=.08, steps=config["minimize_steps"])
    temperature = 650 if split == "test_ood" else config["temperatures_K"][group % 3]
    MaxwellBoltzmannDistribution(atoms, temperature_K=temperature, rng=rng)
    Stationary(atoms)
    ZeroRotation(atoms)
    dynamics = Langevin(atoms, config["dt_fs"]*units.fs, temperature_K=temperature,
                        friction=.02 / units.fs, rng=rng, logfile=None)
    dynamics.run(config["warmup_steps"])
    positions, energies, forces, categories, steps = [], [], [], [], []
    for frame in range(config["frames_per_group"]):
        dynamics.run(config["stride_steps"])
        x = atoms.positions.copy()
        category = "thermal"
        if split == "test_trajectory":
            category = "trajectory"
        elif split == "test_ood":
            category = "ood"
        elif frame % 10 in (7, 8):
            category = "distortion"
            x += rng.normal(0, .018, x.shape)
        elif frame % 10 == 9:
            category = "boundary"
            # Move one complete monomer through the circuit's cutoff region.
            m = frame // 10 % 20
            direction = x[3*m] - x[::3].mean(0)
            direction /= max(np.linalg.norm(direction), 1e-8)
            x[3*m:3*m+3] += rng.uniform(-.2, .3) * direction
        validate_geometry(x)
        energy, force = reference.evaluate(x)
        positions.append(x)
        energies.append(energy)
        forces.append(force)
        categories.append(category)
        steps.append(config["warmup_steps"] + (frame+1)*config["stride_steps"])
    return {"group": group, "split": split, "positions": np.array(positions), "energy": np.array(energies),
            "forces": np.array(forces), "category": categories, "step": steps,
            "temperature_K": temperature, "minimization_converged": bool(optimizer.converged())}


def generate(config_path, library, output):
    config_path, library, output = Path(config_path), Path(library).resolve(), Path(output)
    config = json.loads(config_path.read_text())
    if sum(config["group_splits"].values()) != config["n_groups"]:
        raise ValueError("Group quotas do not sum to n_groups")
    output.mkdir(parents=True, exist_ok=True)
    target = output / "water20.h5"
    if target.exists():
        raise FileExistsError("Dataset already exists; choose another output directory")
    start = time.monotonic()
    # Split ownership is determined before labels exist, never per random frame.
    owners = [name for name, count in config["group_splits"].items() for _ in range(count)]
    arguments = [(g, s, config, str(library)) for g, s in enumerate(owners)]
    with ProcessPoolExecutor(max_workers=config["workers"]) as pool:
        groups = []
        for result in pool.map(_group, arguments):
            groups.append(result)
            print(f"group {result['group']+1}/{len(arguments)} {result['split']}", flush=True)
    x = np.concatenate([g["positions"] for g in groups])
    energy = np.concatenate([g["energy"] for g in groups])
    force = np.concatenate([g["forces"] for g in groups])
    n = len(x)
    ids = [f"w20_{hashlib.sha256(row.tobytes()).hexdigest()[:24]}" for row in x]
    if len(set(ids)) != n:
        raise ValueError("Duplicate coordinates")
    splits = np.repeat(owners, config["frames_per_group"])
    group_ids = np.repeat(np.arange(len(groups)), config["frames_per_group"])
    with h5py.File(target.with_suffix(".h5.tmp"), "w") as h:
        for key, value in {"positions_angstrom": x, "energy_ev": energy, "forces_ev_per_angstrom": force,
                           "group_id": group_ids, "md_step": np.concatenate([g["step"] for g in groups]),
                           "temperature_K": np.repeat([g["temperature_K"] for g in groups], config["frames_per_group"])}.items():
            h.create_dataset(key, data=value, compression="gzip", compression_opts=4, shuffle=True)
        for key, values in {"sample_id": ids, "split": splits.tolist(),
                            "category": sum([g["category"] for g in groups], [])}.items():
            h.create_dataset(key, data=np.array(values, dtype=h5py.string_dtype()), compression="gzip")
        h["atomic_numbers"] = [8, 1, 1]*20
        h["molecule_id"] = np.repeat(np.arange(20), 3)
        h.attrs.update(position_unit="angstrom", energy_unit="eV", force_unit="eV/angstrom",
                       label_source="MB-pol", is_dft=False, pbc=False, schema_version=1,
                       n_molecules=20, sampling="MB-pol Langevin MD and explicit perturbations")
    target.with_suffix(".h5.tmp").replace(target)
    train = splits == "train"
    mass = np.tile([15.999, 1.008, 1.008], 20)
    centered = x[train] - (x[train]*mass[None, :, None]).sum(1)[:, None]/mass.sum()
    oxygens = centered[:, ::3].reshape(-1, 3)
    bonds = x[train].reshape(-1, 20, 3, 3)
    lengths = np.linalg.norm(bonds[:, :, 1:] - bonds[:, :, :1], axis=-1)
    normalizer = dict(oh_mean=float(lengths.mean()), oh_scale=float(max(lengths.std(), 1e-8)),
                      oxygen_mean=oxygens.mean(0).tolist(), oxygen_scale=np.maximum(oxygens.std(0), 1e-8).tolist(),
                      energy_mean_ev=float(energy[train].mean()), energy_scale_ev=float(max(energy[train].std(), 1e-8)),
                      fit_split="train", train_count=int(train.sum()), train_ids_sha256=hashlib.sha256("\n".join(np.array(ids)[train]).encode()).hexdigest(),
                      coordinate_policy="mass_centered", encoding_version="centered_bisector_xyz_no_floor_v1")
    (output / "normalizer.json").write_text(json.dumps(normalizer, indent=2)+"\n")
    manifest = dict(schema_version=1, dataset_id="water20_mbpol_v1", n_samples=n, n_atoms=60,
                    splits=dict(Counter(splits)), categories=dict(Counter(sum([g["category"] for g in groups], []))),
                    isolated_groups={s: [i for i, owner in enumerate(owners) if owner == s] for s in config["group_splits"]},
                    config=config, host=platform.node(), wall_seconds=time.monotonic()-start,
                    library_sha256=hashlib.sha256(library.read_bytes()).hexdigest(),
                    mbx_core_sha256=hashlib.sha256((library.parent/"libmbx.so.0").read_bytes()).hexdigest(),
                    config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
                    dataset_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                    energy_range_ev=[float(energy.min()), float(energy.max())], max_force_ev_per_angstrom=float(np.abs(force).max()),
                    minimization_converged_groups=[g["group"] for g in groups if g["minimization_converged"]],
                    reference="Full interacting MBX System.Energy(true), h2o; no sum of water10 labels", is_dft=False,
                    scientific_status="reference_dataset_generated; quantum_model_not_trained")
    (output/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest
