"""Shared stage policy for task validation and the public task catalog."""
import os


def stage_policy(stage, *, prediction=False):
    if prediction:
        if stage.id == "circuit_execution":
            return "qpu", ("cpu", "gpu", "qpu")
        if stage.id == "quantum_features":
            return stage.default_device, ("cpu", *stage.allowed_devices)
        return stage.default_device, stage.allowed_devices
    mode = os.environ.get('FUSION_EXECUTOR')
    if mode == 'local_cpu':
        if stage.id in ('quantum_features', 'circuit_execution'):
            return 'qpu', ('cpu', 'gpu', 'qpu')
        if stage.id == 'classical_predict':
            return 'gpu', ('cpu', 'gpu')
        return 'cpu', ('cpu',)
    if mode == 'ray':
        allowed = (('gpu',) if stage.id == 'classical_predict' else
                   ('cpu',) if stage.id == 'trajectory_analysis' else
                   tuple(d for d in stage.allowed_devices if d != 'qpu_simulator'))
        return stage.default_device, allowed
    return stage.default_device, stage.allowed_devices
