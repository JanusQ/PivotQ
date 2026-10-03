"""Versioned deployment configuration; paths refer to shared cluster storage."""
import importlib
import json
import math
import os
from pathlib import Path
import re

CONFIG_ENV = 'WATER10_FUSION_CONFIG'


def load_config(path=None):
    c = json.loads(Path(path or os.environ[CONFIG_ENV]).read_text())
    return validate_config(c)


def resolve_template(path, application_root):
    """Resolve the portable template before writing a shared runtime config."""
    c = json.loads(Path(path).read_text())
    for name in ('model_path', 'geometry_path'):
        value = Path(c[name]).expanduser()
        c[name] = str((value if value.is_absolute() else Path(application_root) / value).resolve())
    return validate_config(c)


def validate_config(c):
    if c.get('schema_version') != 1:
        raise ValueError('Expected fusion schema_version=1')
    for name in ('model_path', 'geometry_path'):
        if not Path(c[name]).is_absolute():
            raise ValueError(f'{name} must be an absolute shared-cluster path')
    if re.fullmatch('[0-9a-f]{64}', c['model_sha256']) is None:
        raise ValueError('Expected model_sha256')
    if c['quantum_target'] not in ('cpu', 'qpu') or c['classical_device'] not in ('cpu', 'cuda'):
        raise ValueError('Use quantum_target cpu/qpu and classical_device cpu/cuda')
    if c['mode'] not in ('energy', 'energy_force', 'aimd'):
        raise ValueError('Unknown execution mode')
    for name in ('quantum_timeout_seconds', 'classical_timeout_seconds', 'fd_step_A', 'timestep_fs'):
        value = c[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be finite and positive')
    for name in ('batch_size', 'statevector_memory_mb', 'steps'):
        if isinstance(c[name], bool) or not isinstance(c[name], int) or c[name] <= 0:
            raise ValueError(f'{name} must be a positive integer')
    threads = c.get('quantum_num_threads', 1)
    if isinstance(threads, bool) or not isinstance(threads, int) or threads <= 0:
        raise ValueError('quantum_num_threads must be a positive integer')
    from ...statevector import settings
    settings(c['statevector_memory_mb'])
    if 'mps_bond' in c:
        raise ValueError('mps_bond is obsolete; use statevector_memory_mb')
    if not math.isfinite(c['temperature_K']) or c['temperature_K'] < 0:
        raise ValueError('temperature_K must be finite and nonnegative')
    if isinstance(c['seed'], bool) or not isinstance(c['seed'], int) or c['seed'] < 0:
        raise ValueError('seed must be a nonnegative integer')
    if c['mode'] != 'energy' and c.get('allow_unvalidated_forces') is not True:
        raise ValueError('v4 force/MD is unvalidated; explicitly set allow_unvalidated_forces=true')
    if c['quantum_target'] == 'qpu':
        for key in ('qpu_service_factory', 'qpu_registration'):
            if not c.get(key):
                raise ValueError(f'{key} is required: built-in framework QOS is fixed to 3 qubits')
            validate_target(c[key])
        if isinstance(c.get('shots'), bool) or not isinstance(c.get('shots'), int) or c['shots'] <= 0:
            raise ValueError('Positive integer QPU shots required; no default shot budget')
    return c


def validate_target(target):
    if not isinstance(target, str) or re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*', target) is None:
        raise ValueError('Expected package.module:callable')


def import_target(target):
    validate_target(target)
    module, name = target.split(':')
    result = getattr(importlib.import_module(module), name)
    if not callable(result):
        raise TypeError('Import target must be callable')
    return result
