"""Continuous v4 AIMD encoding generalized to twenty OHH-ordered waters."""
from itertools import combinations

import numpy as np

ENCODING_VERSION = "centered_bisector_xyz_no_floor_v1"


def switch(distance, radii):
    on, off = radii
    if not 0 < on < off:
        raise ValueError("Expected 0 < cutoff on < off")
    t = np.clip((distance-on)/(off-on), 0., 1.)
    return np.clip(1 - 10*t**3 + 15*t**4 - 6*t**5, 0., 1.)


def descriptors(positions, normalizer):
    x = np.asarray(positions, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] != 3 or len(x) % 3 or not np.isfinite(x).all():
        raise ValueError("Expected finite OHH-ordered coordinates")
    n = len(x)//3
    masses = np.tile([15.999, 1.008, 1.008], n)
    x = x - (x*masses[:, None]).sum(0)/masses.sum()
    xyz = x.reshape(n, 3, 3)
    oxygen = xyz[:, 0]
    bonds = xyz[:, 1:] - oxygen[:, None]
    lengths = np.linalg.norm(bonds, axis=-1)
    if lengths.min() < 1e-8:
        raise ValueError("Degenerate OH bond")
    unit = bonds/lengths[..., None]
    bisector = unit.sum(1)
    norms = np.linalg.norm(bisector, axis=-1)
    cross = np.linalg.norm(np.cross(unit[:, 0], unit[:, 1]), axis=-1)
    if norms.min() < 1e-8 or cross.min() < 1e-8:
        raise ValueError("Collinear water has undefined orientation")
    bisector /= norms[:, None]
    angle = np.arctan2(cross, (unit[:, 0]*unit[:, 1]).sum(-1))
    scales = np.asarray(normalizer["oxygen_scale"])
    if normalizer["oh_scale"] <= 0 or scales.shape != (3,) or np.any(scales <= 0):
        raise ValueError("Invalid normalizer scales")
    oh = np.pi/2*np.tanh((lengths-normalizer["oh_mean"])/normalizer["oh_scale"])
    x1 = np.column_stack((oh, angle))
    o = np.pi/2*np.tanh((oxygen-normalizer["oxygen_mean"])/scales)
    return x1, o, bisector, oxygen


def active_groups(positions, normalizer, radii):
    n = len(positions)//3
    oxygen = descriptors(positions, normalizer)[3]
    groups = {1: [(i,) for i in range(n)], 2: [], 3: []}
    weights = {}
    for body in (2, 3):
        for mols in combinations(range(n), body):
            ds = [np.linalg.norm(oxygen[i]-oxygen[j]) for i, j in combinations(mols, 2)]
            if min(ds) < 1e-8:
                raise ValueError("Coincident oxygens")
            if body == 2:
                w = float(switch(ds[0], radii["pair_radii"]))
            else:
                a, b, c = [switch(d, radii["triple_radii"]) for d in ds]
                w = float(np.clip(a*b+a*c+b*c-2*a*b*c, 0., 1.))
            if w > 0:
                groups[body].append(mols)
                weights[mols] = w
    return groups, weights


def instances(positions, theta, config, normalizer, *, groups=None):
    """Lexicographic groups; one continuous semantic slot per feature owner.

    Orientation slot 3 contains consecutive bx/by rotations, as in v4 AIMD;
    slot 4 contains bz. It deliberately differs from legacy azimuth/polar.
    Supplying fixed groups permits coordinate derivatives at support edges.
    """
    x1, o, bisector, oxygen = descriptors(positions, normalizer)
    if groups is None:
        groups, _ = active_groups(positions, normalizer, config["radii"])
    weights = {}
    for body in (2, 3):
        for mols in groups[body]:
            ds = [np.linalg.norm(oxygen[i]-oxygen[j]) for i, j in combinations(mols, 2)]
            if body == 2:
                w = switch(ds[0], config["radii"]["pair_radii"])
            else:
                a, b, c = [switch(d, config["radii"]["triple_radii"]) for d in ds]
                w = np.clip(a*b+a*c+b*c-2*a*b*c, 0., 1.)
            weights[mols] = float(w)
    gates = []
    for stage in ("encoding", "trainable"):
        for body in (1, 2, 3):
            for mols in groups[body]:
                weight = 1. if body == 1 else weights[mols]
                wires = [3*m+q for m in mols for q in range(3)]
                for f, block in enumerate(config["templates"][stage][str(body)]):
                    for j, gate in enumerate(block):
                        axis = gate["axis"]
                        coefficient = weight*gate["scale"]
                        key = f"b{body}_f{f}_g{j}" if stage == "trainable" else None
                        if key:
                            values = [(axis, coefficient*theta[key], "theta")]
                        elif body == 1:
                            values = [(axis, coefficient*x1[mols[0], f], ("OH1", "OH2", "HOH")[f])]
                        else:
                            owner, channel = mols[f//5], f % 5
                            if channel < 3:
                                values = [(axis, coefficient*o[owner, channel], ("Ox", "Oy", "Oz")[channel])]
                            elif channel == 3:
                                alt = ("Y" if axis[0] == "X" else "X")+axis[1:]
                                values = [(axis, coefficient*bisector[owner, 0], "bx"),
                                          (alt, coefficient*bisector[owner, 1], "by")]
                            else:
                                values = [(axis, coefficient*bisector[owner, 2], "bz")]
                        for actual_axis, angle, channel_name in values:
                            gates.append(dict(stage=stage, body=body, molecules=list(mols), feature=f,
                                              template_gate=j, axis=actual_axis, qubits=[wires[q] for q in gate["sites"]],
                                              angle=float(angle), parameter=key, coefficient=coefficient,
                                              weight=weight, channel=channel_name,
                                              block_id=f"{stage}.b{body}."+"-".join(map(str, mols))+f".f{f:02d}"))
    return gates, groups


def angle_jacobian(positions, theta, config, normalizer, groups, epsilon=1e-6):
    """Central difference of the classical smooth encoder, no quantum jobs.

    The active list remains fixed; the quintic switch and two zero derivatives
    make the omitted zero-support modules contribute zero at cutoff boundaries.
    This is not claimed to be an analytic geometry derivative.
    """
    x = np.asarray(positions, float).copy()
    jacobian = []
    for k in range(x.size):
        plus, minus = x.copy(), x.copy()
        plus.flat[k] += epsilon
        minus.flat[k] -= epsilon
        a = instances(plus, theta, config, normalizer, groups=groups)[0]
        b = instances(minus, theta, config, normalizer, groups=groups)[0]
        jacobian.append([(g["angle"]-h["angle"])/(2*epsilon) for g, h in zip(a, b)])
    return np.asarray(jacobian).T
