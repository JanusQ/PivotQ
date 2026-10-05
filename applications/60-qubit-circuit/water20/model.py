"""Inference-only tanh total-energy head; seeded weights are not trained."""
import hashlib
import json
from pathlib import Path

import numpy as np

from .circuit import validate_templates
from .geometry import ENCODING_VERSION, instances

ROOT = Path(__file__).resolve().parents[1]


def initialize(root=ROOT, seed=20261004):
    root = Path(root)
    config = json.loads((root/"configs/circuit.json").read_text())
    keys, _ = validate_templates(config)
    rng = np.random.default_rng(seed)
    theta = dict(zip(keys, (rng.choice([-1., 1.], len(keys)) * rng.uniform(.2, .6, len(keys))).tolist()))
    arrays = {}
    widths = config["widths"]
    for layer, (a, b) in enumerate(zip(widths[:-1], widths[1:])):
        arrays[f"W{layer}"] = rng.normal(0, np.sqrt(2/(a+b)), (a, b))
        arrays[f"b{layer}"] = np.zeros(b)
    folder = root/"models"
    folder.mkdir(exist_ok=True)
    path = folder/"initial_model.npz"
    if path.exists():
        raise FileExistsError("Never overwrite a model checkpoint")
    np.savez_compressed(path, **arrays)
    metadata = dict(schema_version=1, seed=seed, theta=theta, n_qubits=60, widths=widths,
                    encoding_version=ENCODING_VERSION, training_updates=0, model_status="initialized_untrained",
                    scientific_status="not_validated", classical_parameter_count=sum(v.size for v in arrays.values()),
                    quantum_parameter_count=len(theta), checkpoint_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    normalizer_sha256=hashlib.sha256((root/"dataset_water20_mbpol_v1/normalizer.json").read_bytes()).hexdigest(),
                    circuit_config_sha256=hashlib.sha256((root/"configs/circuit.json").read_bytes()).hexdigest())
    (folder/"model.json").write_text(json.dumps(metadata, indent=2)+"\n")


class Model:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.config = json.loads((self.root/"configs/circuit.json").read_text())
        self.metadata = json.loads((self.root/"models/model.json").read_text())
        self.normalizer = json.loads((self.root/"dataset_water20_mbpol_v1/normalizer.json").read_text())
        checkpoint = self.root/"models/initial_model.npz"
        if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != self.metadata["checkpoint_sha256"]:
            raise ValueError("Model checkpoint hash mismatch")
        if hashlib.sha256((self.root/"configs/circuit.json").read_bytes()).hexdigest() != self.metadata["circuit_config_sha256"]:
            raise ValueError("Circuit configuration changed after model initialization")
        if hashlib.sha256((self.root/"dataset_water20_mbpol_v1/normalizer.json").read_bytes()).hexdigest() != self.metadata["normalizer_sha256"]:
            raise ValueError("Normalizer changed after model initialization")
        keys, _ = validate_templates(self.config)
        if set(self.metadata["theta"]) != set(keys) or self.metadata["encoding_version"] != ENCODING_VERSION:
            raise ValueError("Parameter/encoding contract mismatch")
        if self.config["n_qubits"] != 60 or self.config["widths"] != [120, 64, 32, 1]:
            raise ValueError("Wrong water20 model dimensions")
        with np.load(checkpoint, allow_pickle=False) as archive:
            self.network = {key: archive[key].copy() for key in archive.files}
        expected = {f"{kind}{i}" for i in range(3) for kind in ("W", "b")}
        if set(self.network) != expected or not all(np.isfinite(v).all() for v in self.network.values()):
            raise ValueError("Missing or nonfinite classical weights")
        for i, (a, b) in enumerate(zip(self.config["widths"][:-1], self.config["widths"][1:])):
            if self.network[f"W{i}"].shape != (a, b) or self.network[f"b{i}"].shape != (b,):
                raise ValueError("Classical checkpoint layer dimensions differ")
        if not all(isinstance(v, (int, float)) and np.isfinite(v) for v in self.metadata["theta"].values()):
            raise ValueError("Invalid quantum parameter values")

    def gates(self, positions):
        if np.shape(positions) != (60, 3):
            raise ValueError("water20 model requires (60,3) geometry")
        return instances(positions, self.metadata["theta"], self.config, self.normalizer)

    def predict(self, features, gradient=False):
        z = np.asarray(features, dtype=float)
        if z.shape != (120,) or not np.isfinite(z).all() or np.any(np.abs(z) > 1+1e-8):
            raise ValueError("Expected 120 finite X/Z expectations")
        activations = [z]
        for layer in range(3):
            z = z @ self.network[f"W{layer}"] + self.network[f"b{layer}"]
            if layer < 2:
                z = np.tanh(z)
            activations.append(z)
        scale = self.normalizer["energy_scale_ev"]
        energy = float(z[0]*scale+self.normalizer["energy_mean_ev"])
        if not gradient:
            return energy
        derivative = np.array([scale])
        for layer in reversed(range(3)):
            if layer < 2:
                derivative = derivative * (1-activations[layer+1]**2)
            derivative = self.network[f"W{layer}"] @ derivative
        return energy, derivative
