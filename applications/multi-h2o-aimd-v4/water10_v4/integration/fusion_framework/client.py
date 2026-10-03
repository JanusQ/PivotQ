"""Synchronous driver-side potential with bounded quantum/MLP batches."""
from uuid import uuid4
import numpy as np

from .components import CLASSICAL_ID, QUANTUM_ID
from .config import import_target
from .model import FrozenModel, geometries, readouts
from .qpu import QPUFeatures


class FusionPotential:
    def __init__(self, framework, context, config):
        self.framework, self.context, self.config = framework, context, config
        self.calls = dict(energy_queries=0, geometries=0, quantum_batches=0, classical_batches=0)
        self.quantum_executions = []
        self.active = False
        self.model = FrozenModel(config['model_path'], config['model_sha256'])
        self.qpu = None
        if config['quantum_target'] == 'qpu':
            service = import_target(config['qpu_service_factory'])(framework, context)
            self.qpu = QPUFeatures(service, shots=config['shots'], physical_qubits=config.get('physical_qubits'))

    def invoke(self, component, method, *args):
        from ray_quantum.models import StringMetadata
        handle = self.framework.submit(component, method, *args, invocation_id=f'water10.{uuid4().hex}',
            trace_context=StringMetadata.from_mapping({'run_id': self.context.run_id, 'operation': method}))
        terminal = False
        try:
            result = self.framework.result(handle)
            terminal = True
            if not result.succeeded:
                raise RuntimeError(f'{component}.{method} failed: {result.error}')
            return result.value
        finally:
            # If result() itself raises, its terminal state is unknown. Driver close owns cleanup.
            if terminal:
                self.framework.release(handle)

    def __enter__(self):
        c = self.config
        try:
            self.invoke(CLASSICAL_ID, 'create', c['model_path'], c['model_sha256'], c['classical_device'])
            self.active = True
        except BaseException:
            # Driver/framework close also handles an interrupted or ambiguous create.
            try:
                self.invoke(CLASSICAL_ID, 'terminate')
            except BaseException:
                pass
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.active:
            self.active = False
            try:
                self.invoke(CLASSICAL_ID, 'terminate')
            except BaseException as error:
                if exc is None:
                    raise
                exc.add_note(f'Classical session cleanup also failed: {error}')

    def energy(self, positions):
        if not self.active:
            raise RuntimeError('Use FusionPotential as a context manager')
        batch = geometries(positions)
        c, outputs = self.config, []
        self.calls['energy_queries'] += 1
        for start in range(0, len(batch), c['batch_size']):
            self.context.raise_if_stop_requested()
            part = batch[start:start+c['batch_size']]
            if self.qpu is None:
                result = self.invoke(QUANTUM_ID, 'execute_with_metadata', c['model_path'],
                    c['model_sha256'], part.tolist(), c['statevector_memory_mb'],
                    c.get('quantum_num_threads', 1))
                z = result['features']
                self.quantum_executions.extend(result['executions'])
            else:
                z = self.qpu.evaluate_batch(self.model.gates(part))
            z = readouts(z)
            if len(z) != len(part):
                raise ValueError('Quantum result batch size mismatch')
            self.calls['quantum_batches'] += 1
            self.context.raise_if_stop_requested()
            energies = np.asarray(self.invoke(CLASSICAL_ID, 'predict', z.tolist()), dtype=float)
            if energies.shape != (len(part),) or not np.isfinite(energies).all():
                raise ValueError('Invalid classical energy batch')
            outputs.extend(energies)
            self.calls['classical_batches'] += 1
            self.calls['geometries'] += len(part)
        return np.asarray(outputs)

    def energy_force(self, positions):
        """Experimental Cartesian FD: base + 90 positive + 90 negative geometries.

        No rigid-body projection: this globally encoded v4 model is not guaranteed
        translation/rotation invariant. Projection would silently change its force.
        """
        r = geometries(np.asarray(positions)[None])[0]
        h = self.config['fd_step_A']
        offsets = (np.eye(90) * h).reshape(90, 30, 3)
        batch = np.concatenate([r[None], r[None]+offsets, r[None]-offsets])
        energy = self.energy(batch)
        return float(energy[0]), (-(energy[1:91]-energy[91:])/(2*h)).reshape(30, 3)
