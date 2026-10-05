"""PivotQ framework bridge: quantum Task/Actor -> persistent classical Actor.

Uses public opaque payload contracts; does not reuse the three-qubit QPU service.
The direct application CLI and this framework energy route are separate entries.
"""
from dataclasses import dataclass
from pathlib import Path
import uuid

import numpy as np

from .hardware import HardwareProfile
from .model import Model
from .potential import DEFAULT_COORDINATE_FD_STEP
from .qpu import QPUClient
from .simulator import ExactSimulator


class QuantumCPU:
    def describe(self):
        return dict(n_qubits=60, feature_order="X0..X59,Z0..Z59", backend="cpu_exact_tensor_factors")

    def execute(self, root, positions):
        model = Model(root)
        gates, _ = model.gates(positions)
        sampler = ExactSimulator()
        features = sampler.evaluate(gates)
        return dict(features=features.tolist(), quantum_metadata=sampler.last_metadata,
                    model_sha256=model.metadata["checkpoint_sha256"])


class QuantumQPU:
    def __init__(self, root, profile, journal, shots, timeout):
        self.model = Model(root)
        self.sampler = QPUClient(HardwareProfile.load(profile), journal, timeout_seconds=timeout)
        self.sampler.shots = shots

    def describe(self):
        return dict(n_qubits=60, feature_order="X0..X59,Z0..Z59", backend="real_qpu_http")

    def execute(self, root, positions):
        if Path(root).resolve() != self.model.root:
            raise ValueError("QPU Actor model root changed")
        gates, _ = self.model.gates(positions)
        features = self.sampler.sample(gates, "fusion-"+uuid.uuid4().hex)
        return dict(features=features.tolist(), quantum_metadata=self.sampler.last_metadata,
                    model_sha256=self.model.metadata["checkpoint_sha256"])

    def close(self):
        self.sampler.close()


class ClassicalActor:
    def __init__(self, root):
        self.model = Model(root)
        self.calls = 0

    def describe(self):
        return dict(widths=[120, 64, 32, 1], model_status="initialized_untrained")

    def predict(self, quantum_payload):
        if quantum_payload["model_sha256"] != self.model.metadata["checkpoint_sha256"]:
            raise ValueError("Quantum/classical checkpoint hashes differ")
        self.calls += 1
        return dict(energy_ev=self.model.predict(quantum_payload["features"]),
                    classical_calls=self.calls, quantum_metadata=quantum_payload["quantum_metadata"],
                    model_sha256=self.model.metadata["checkpoint_sha256"],
                    scientific_status="not_validated", training_updates=0)


@dataclass(frozen=True)
class ClassicalFactory:
    root: str

    def __call__(self):
        return ClassicalActor(self.root)


@dataclass(frozen=True)
class QPUFactory:
    root: str
    profile: str
    journal: str
    shots: int
    timeout: float

    def __call__(self):
        return QuantumQPU(self.root, self.profile, self.journal, self.shots, self.timeout)


def register(framework, root, *, backend="cpu", profile=None, journal=None, shots=3000, timeout=600):
    from ray_quantum.framework import ComponentSpec, ExecutionMode, ResourceRequest
    root = str(Path(root).resolve())
    if backend == "cpu":
        mode, factory = ExecutionMode.TASK, QuantumCPU
    elif backend == "qpu":
        HardwareProfile.load(profile)  # Reject missing capabilities before dispatch.
        mode = ExecutionMode.ACTOR
        factory = QPUFactory(root, str(Path(profile).resolve()), str(Path(journal).resolve()), shots, timeout)
    else:
        raise ValueError("backend must be cpu or qpu")
    framework.register(ComponentSpec(component_id="water20.quantum", execution=mode,
        resources=ResourceRequest(num_cpus=1), allowed_methods=("execute",),
        stateful=backend == "qpu", max_concurrency=1, timeout_seconds=timeout+120), factory)
    framework.register(ComponentSpec(component_id="water20.classical", execution=ExecutionMode.ACTOR,
        resources=ResourceRequest(num_cpus=.25), allowed_methods=("predict",), stateful=True,
        max_concurrency=1, timeout_seconds=60), ClassicalFactory(root))


class FusionEnergy:
    def __init__(self, framework, root):
        self.framework, self.root = framework, str(Path(root).resolve())
        self.calls = 0

    def energy(self, positions):
        prefix = "w20-"+uuid.uuid4().hex
        quantum = self.framework.submit("water20.quantum", "execute", self.root, positions,
            invocation_id=prefix+".quantum")
        classical = None
        try:
            classical = self.framework.submit("water20.classical", "predict", self.framework.reference(quantum),
                invocation_id=prefix+".classical", dependencies=(quantum.invocation_id,))
            result = self.framework.result(classical)
            if result.status.value != "succeeded":
                raise RuntimeError("Framework classical invocation did not succeed")
            self.last_metadata = result.value
            self.calls += 1
            return result.value["energy_ev"]
        finally:
            # Framework owns cleanup of Actors and unresolved invocations.
            if classical is not None:
                self.framework.release(classical)
            self.framework.release(quantum)

    def energy_force(self, positions, step=DEFAULT_COORDINATE_FD_STEP):
        if not np.isfinite(step) or step <= 0:
            raise ValueError("Positive finite coordinate step required")
        x = np.asarray(positions, dtype=float)
        energy = self.energy(x)
        forces = np.empty_like(x)
        for k in range(x.size):
            a, b = x.copy(), x.copy()
            a.flat[k] += step
            b.flat[k] -= step
            forces.flat[k] = -(self.energy(a)-self.energy(b))/(2*step)
        return energy, forces
