"""One energy head, coordinate forces, and ASE VelocityVerlet integration."""
import uuid

import numpy as np
from ase.calculators.calculator import Calculator, all_changes

from .geometry import angle_jacobian

DEFAULT_COORDINATE_FD_STEP = .02  # Angstrom; exploratory finite-shot force queries.


class Potential:
    def __init__(self, model, sampler):
        self.model, self.sampler = model, sampler
        self.evaluations = 0

    def features(self, gates, request_id=None):
        self.evaluations += 1
        if hasattr(self.sampler, "sample"):
            return self.sampler.sample(gates, request_id=request_id or "w20-"+uuid.uuid4().hex)
        return self.sampler.evaluate(gates)

    def energy(self, positions):
        gates, _ = self.model.gates(positions)
        return self.model.predict(self.features(gates))

    def energy_force(self, positions, *, method="adjoint", epsilon=1e-6):
        gates, groups = self.model.gates(positions)
        features = self.features(gates)
        energy, gradient = self.model.predict(features, gradient=True)
        if method == "adjoint":
            if not hasattr(self.sampler, "angle_gradient"):
                raise ValueError("Adjoint is only available on the explicit CPU simulator")
            angle_gradient = self.sampler.angle_gradient(gradient, len(gates))
        elif method == "parameter_shift":
            # Shift ONE gate instance; the classical head's feature derivative
            # remains fixed. Never apply the single-gate rule to total MLP energy.
            angle_gradient = np.empty(len(gates))
            for i in range(len(gates)):
                plus, minus = [dict(g) for g in gates], [dict(g) for g in gates]
                plus[i]["angle"] += np.pi/2
                minus[i]["angle"] -= np.pi/2
                angle_gradient[i] = gradient @ ((self.features(plus)-self.features(minus))/2)
        else:
            raise ValueError("Force method must be adjoint or parameter_shift")
        jacobian = angle_jacobian(positions, self.model.metadata["theta"], self.model.config,
                                  self.model.normalizer, groups, epsilon)
        forces = -(angle_gradient @ jacobian).reshape(60, 3)
        if not np.isfinite(forces).all():
            raise ArithmeticError("Nonfinite model forces")
        return energy, forces

    def coordinate_fd(self, positions, step=DEFAULT_COORDINATE_FD_STEP):
        """Hardware alternative: 361 geometries, 722 X/Z settings per query.

        Finite shots amplify force noise as step decreases. This verifies the
        execution path, not accuracy or energy conservation of untrained weights.
        """
        if not np.isfinite(step) or step <= 0:
            raise ValueError("Positive finite coordinate step required")
        x = np.asarray(positions, float)
        energy = self.energy(x)
        forces = np.empty_like(x)
        for k in range(x.size):
            a, b = x.copy(), x.copy()
            a.flat[k] += step
            b.flat[k] -= step
            forces.flat[k] = -(self.energy(a)-self.energy(b))/(2*step)
        return energy, forces


class ASEPotential(Calculator):
    implemented_properties = ["energy", "forces"]

    def __init__(self, potential, force_method="adjoint", fd_step=DEFAULT_COORDINATE_FD_STEP, **kwargs):
        super().__init__(**kwargs)
        self.potential, self.force_method = potential, force_method
        self.fd_step = fd_step

    def calculate(self, atoms=None, properties=("energy", "forces"), system_changes=all_changes):
        super().calculate(atoms, properties, system_changes)
        if list(atoms.numbers) != [8, 1, 1]*20 or np.any(atoms.pbc):
            raise ValueError("Isolated OHH-ordered water20 required")
        if self.force_method == "coordinate_fd":
            energy, forces = self.potential.coordinate_fd(atoms.positions, step=self.fd_step)
        else:
            energy, forces = self.potential.energy_force(atoms.positions, method=self.force_method)
        self.results = {"energy": energy, "forces": forces}
