"""CPU dense statevector Task and a persistent CPU/CUDA classical Actor."""
import os
import resource
import time

import numpy as np

from .model import FrozenModel, geometries, readouts

QUANTUM_ID = 'water10.quantum.cpu'
CLASSICAL_ID = 'water10.classical'


class QuantumComponent:
    def describe(self):
        return dict(name=QUANTUM_ID, num_qubits=30, device='CPU', method='statevector')

    def execute(self, model_path, model_sha256, positions, statevector_memory_mb, num_threads=1):
        return self.execute_with_metadata(model_path, model_sha256, positions,
                                          statevector_memory_mb, num_threads)['features']

    def execute_with_metadata(self, model_path, model_sha256, positions,
                              statevector_memory_mb, num_threads=1):
        from ...revision import build_block_circuit
        from ...runtime import require_memory_budget
        from qiskit_aer import AerSimulator
        if isinstance(num_threads, bool) or not isinstance(num_threads, int) or num_threads < 1:
            raise ValueError('num_threads must be a positive integer')
        model = FrozenModel(model_path, model_sha256)
        from ...statevector import settings, require_memory
        options = settings(statevector_memory_mb)
        options['max_parallel_threads'] = num_threads
        simulator = AerSimulator(**options)
        rows, executions = [], []
        for gates in model.gates(geometries(positions)):
            require_memory(memory_mb=statevector_memory_mb)
            memory = require_memory_budget(statevector_memory_mb / 1024)
            circuit = build_block_circuit(gates)
            started = time.perf_counter()
            result = simulator.run(circuit, shots=1, seed_simulator=916).result()
            if not result.success:
                raise RuntimeError(str(result.status))
            metadata = result.results[0].metadata
            if metadata.get('method') != 'statevector' or metadata.get('num_qubits') != circuit.num_qubits:
                raise RuntimeError('Aer did not execute the full requested statevector')
            rows.append([result.data(0)[f'{a}{q}'] for a in ('X', 'Z') for q in range(30)])
            executions.append(dict(method=metadata['method'], num_qubits=metadata['num_qubits'],
                device=metadata.get('device'), precision=options['precision'],
                enable_truncation=options['enable_truncation'], num_threads=num_threads,
                parallel_state_update=metadata.get('parallel_state_update'),
                elapsed_seconds=time.perf_counter()-started,
                peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                process_id=os.getpid(), memory_preflight=memory))
        return dict(features=readouts(rows).tolist(), executions=executions)


class ClassicalComponent:
    def __init__(self):
        self.model = None
        self.weights = None
        self.device = None

    def describe(self):
        return dict(name=CLASSICAL_ID, stateful=True, loaded=self.model is not None, device=self.device)

    def create(self, model_path, model_sha256, device):
        if self.model is not None:
            raise RuntimeError('Classical session already created')
        if device not in ('cpu', 'cuda'):
            raise ValueError('Expected cpu or cuda')
        model = FrozenModel(model_path, model_sha256)
        weights = None
        if device == 'cuda':
            import torch
            if not torch.cuda.is_available():
                raise RuntimeError('CUDA requested but unavailable; no CPU fallback')
            weights = {k: torch.tensor(v, dtype=torch.float64, device='cuda') for k, v in model.net['p'].items()}
        self.model, self.weights, self.device = model, weights, device
        return dict(model_sha256=model.sha256, device=device)

    def predict(self, features):
        if self.model is None:
            raise RuntimeError('Classical session has not been created')
        z = readouts(features)
        if self.device == 'cpu':
            energy = self.model.energy(z)
        else:
            import torch
            with torch.no_grad():
                a = torch.tensor(z, dtype=torch.float64, device='cuda')
                for i in range(3):
                    a = a @ self.weights[f'W{i}'] + self.weights[f'b{i}']
                    if i < 2:
                        a = torch.tanh(a)
                n = self.model.state['normalizer']
                energy = (n['energy_mean_ev'] + n['energy_scale_ev'] * a[:, 0]).cpu().numpy()
        if not np.isfinite(energy).all():
            raise FloatingPointError('Nonfinite energy')
        return energy.tolist()

    def terminate(self):
        self.model, self.weights, self.device = None, None, None
        return True

    def close(self):
        self.terminate()
