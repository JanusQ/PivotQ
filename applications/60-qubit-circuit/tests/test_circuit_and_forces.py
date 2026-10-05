from copy import deepcopy
import json

import h5py
import numpy as np
import pytest
from qiskit.quantum_info import Statevector, Pauli, Operator
from qiskit import QuantumCircuit

from water20.circuit import append_rotation, build, native, validate_templates
from water20.geometry import instances, switch
from water20.model import Model, ROOT
from water20.potential import Potential
from water20.simulator import ExactSimulator, components


@pytest.fixture
def model():
    return Model()


@pytest.fixture
def geometry():
    with h5py.File(ROOT/"dataset_water20_mbpol_v1/water20.h5") as h:
        return h["positions_angstrom"][0]


def test_shared_structure_and_dimensions(model, geometry):
    keys, checks = validate_templates(model.config)
    assert len(keys) == 48 and len(checks) == 28
    assert model.metadata["classical_parameter_count"] == 9857
    assert model.metadata["training_updates"] == 0
    assert all(.2 <= abs(value) <= .6 for value in model.metadata["theta"].values())
    assert len(set(model.metadata["theta"].values())) == 48
    gates, groups = model.gates(geometry)
    assert len(groups[1]) == 20
    assert groups[2] and groups[3]
    assert {q for g in gates for q in g["qubits"]} == set(range(60))
    circuit = build(gates)
    assert circuit.num_qubits == 60 and not circuit.num_clbits and not circuit.parameters
    assert not any(i.operation.name in ("reset", "measure", "initialize") for i in circuit.data)
    assert {g["parameter"] for g in gates if g["parameter"]} == set(keys)
    for stage in ("encoding", "trainable"):
        for body, count in ((1, 3), (2, 10), (3, 15)):
            for group in groups[body]:
                owned = [g for g in gates if g["stage"] == stage and g["body"] == body and g["molecules"] == list(group)]
                blocks = [g["feature"] for i, g in enumerate(owned) if i == 0 or g["feature"] != owned[i-1]["feature"]]
                assert blocks == list(range(count))
    max_wire = 3*(20-1)
    assert any(max_wire in g["qubits"] for g in gates)


@pytest.mark.parametrize("axis,qubits", [("X", [0]), ("Y", [1]), ("Z", [2]),
    ("XZ", [0, 2]), ("YZ", [2, 0]), ("XZZ", [2, 0, 1]), ("YZZ", [1, 2, 0])])
def test_pauli_decomposition(axis, qubits):
    from scipy.linalg import expm
    angle = .397
    circuit = QuantumCircuit(3)
    append_rotation(circuit, axis, qubits, angle)
    label = ["I"]*3
    for a, q in zip(axis, qubits):
        label[2-q] = a
    expected = expm(-.5j*angle*Pauli("".join(label)).to_matrix())
    np.testing.assert_allclose(Operator(circuit).data, expected, atol=1e-13)


def test_exact_factors_match_full_nine_qubit_statevector(model, geometry):
    gates, _ = instances(geometry[:9], model.metadata["theta"], model.config, model.normalizer)
    exact = ExactSimulator()
    actual = exact.evaluate(gates, n_qubits=9)
    state = Statevector.from_instruction(build(gates, n_qubits=9))
    expected = [state.expectation_value(Pauli(axis), [q]).real for axis in ("X", "Z") for q in range(9)]
    np.testing.assert_allclose(actual, expected, atol=2e-12)
    np.testing.assert_allclose(Statevector.from_instruction(native(build(gates, n_qubits=9))).data,
                               state.data, atol=2e-12)
    gradient = np.random.default_rng(91).normal(size=18)
    adjoint = exact.angle_gradient(gradient, len(gates), n_qubits=9)
    chosen = [0, 2, len(gates)//2, len(gates)-1]
    chosen += [i for i, g in enumerate(gates) if len(g["qubits"]) > 1][:3]
    for index in chosen:
        plus = ExactSimulator().evaluate([dict(g, angle=g["angle"]+(np.pi/2 if j == index else 0)) for j, g in enumerate(gates)], 9)
        minus = ExactSimulator().evaluate([dict(g, angle=g["angle"]-(np.pi/2 if j == index else 0)) for j, g in enumerate(gates)], 9)
        assert adjoint[index] == pytest.approx(gradient @ ((plus-minus)/2), abs=2e-11)


def test_all_sixty_qubits_and_force_chain_rule(model, geometry):
    simulator = ExactSimulator()
    potential = Potential(model, simulator)
    energy, forces = potential.energy_force(geometry)
    assert np.isfinite(energy) and forces.shape == (60, 3) and np.isfinite(forces).all()
    assert sorted(q for factor in simulator.last_metadata["factor_qubits"] for q in factor) == list(range(60))
    assert simulator.last_metadata["truncated"] is False
    np.testing.assert_allclose(forces.sum(0), 0, atol=1e-7)
    for coordinate in (0, 26, 59, 177):
        plus, minus = geometry.copy(), geometry.copy()
        plus.flat[coordinate] += 2e-5
        minus.flat[coordinate] -= 2e-5
        numerical = -(potential.energy(plus)-potential.energy(minus))/(4e-5)
        assert forces.flat[coordinate] == pytest.approx(numerical, abs=2e-5)


def test_translation_and_smooth_support(model, geometry):
    original, groups = model.gates(geometry)
    translated, translated_groups = model.gates(geometry+[9, -4, 2])
    assert groups == translated_groups
    np.testing.assert_allclose([g["angle"] for g in original], [g["angle"] for g in translated], atol=1e-13)
    assert switch(2., [2., 3.]) == 1
    assert switch(3., [2., 3.]) == 0
    assert switch(2.5, [2., 3.]) == pytest.approx(.5)
    for edge in (2., 3.):
        derivative = (switch(edge+1e-5, [2., 3.])-switch(edge-1e-5, [2., 3.]))/2e-5
        assert abs(derivative) < 1e-8
    for q in (1, 3, 4):
        assert all(not g.get("encoding_min_abs_angle") for g in original)


def test_shared_parameter_derivative_accumulates_instances(model, geometry):
    x = geometry[:6]
    gates, _ = instances(x, model.metadata["theta"], model.config, model.normalizer)
    simulator = ExactSimulator()
    feature = simulator.evaluate(gates, 6)
    gradient = np.random.default_rng(9).normal(size=12)
    derivatives = simulator.angle_gradient(gradient, len(gates), 6)
    key = "b1_f0_g0"
    chain = sum(d*g["coefficient"] for d, g in zip(derivatives, gates) if g["parameter"] == key)
    theta_a, theta_b = dict(model.metadata["theta"]), dict(model.metadata["theta"])
    theta_a[key] += 1e-6
    theta_b[key] -= 1e-6
    ga = instances(x, theta_a, model.config, model.normalizer)[0]
    gb = instances(x, theta_b, model.config, model.normalizer)[0]
    numeric = gradient @ (ExactSimulator().evaluate(ga, 6)-ExactSimulator().evaluate(gb, 6))/2e-6
    assert chain == pytest.approx(numeric, abs=2e-8)


def test_large_factor_is_rejected_without_fallback():
    gates = [dict(axis="XZ", qubits=[i, i+1], angle=.2) for i in range(20)]
    with pytest.raises(MemoryError):
        ExactSimulator(max_factor_qubits=20).evaluate(gates, 60)
