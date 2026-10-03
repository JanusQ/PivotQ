"""Small-system backend checks; never allocate a full 30-qubit state here."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector
from qiskit_aer import AerSimulator

from water10_v4.statevector import settings, require_memory
from water10_v4.backend import Backend
from water10_v4.parallel_training import FastSimulator
from water10_v4.integration.fusion_framework.components import QuantumComponent
from water10_v4.integration.fusion_framework.config import resolve_template


def test_dense_amplitudes_and_idle_qubit_preserved():
    qc = QuantumCircuit(3)
    qc.ry(.37, 0)
    qc.cx(0, 1)
    reference = Statevector.from_instruction(qc).data
    qc.save_statevector()
    result = AerSimulator(**settings()).run(qc).result()
    assert result.success
    actual = np.asarray(result.get_statevector())
    assert actual.shape == (8,)
    np.testing.assert_allclose(actual, reference, atol=1e-14, rtol=0)
    assert result.results[0].metadata['method'] == 'statevector'
    assert result.results[0].metadata['num_qubits'] == 3


def test_all_simulator_entrypoints_are_dense():
    with tempfile.TemporaryDirectory() as d:
        sims = [Backend(Path(d)/'ledger.jsonl').sim, FastSimulator().sim]
        for sim in sims:
            assert sim.options.method == 'statevector'
            assert sim.options.precision == 'double'
            assert sim.options.enable_truncation is False
            assert sim.options.max_parallel_experiments == 1
            assert sim.options.max_memory_mb >= 32768
    assert QuantumComponent().describe()['method'] == 'statevector'


def test_memory_guard_counts_workers():
    with patch('water10_v4.statevector.psutil.virtual_memory', return_value=SimpleNamespace(available=64*2**30)):
        require_memory(2)
        with pytest.raises(MemoryError):
            require_memory(3)
    with pytest.raises(ValueError):
        settings(256)


def test_fusion_config_uses_dense_memory_budget():
    root = Path(__file__).resolve().parents[1]
    c = resolve_template(root/'configs/fusion_cpu.json', root)
    assert c['statevector_memory_mb'] == 32768
    assert 'mps_bond' not in c


def test_fusion_task_executes_statevector_with_small_fixture():
    from qiskit.quantum_info import Pauli
    qc = QuantumCircuit(3)
    qc.x(0)
    for axis in ('X', 'Z'):
        for q in range(30):
            qc.save_expectation_value(Pauli(axis), [q % 3], label=f'{axis}{q}')
    model = SimpleNamespace(gates=lambda positions: [None])
    with patch('water10_v4.integration.fusion_framework.components.FrozenModel', return_value=model), \
         patch('water10_v4.revision.build_block_circuit', return_value=qc), \
         patch('water10_v4.statevector.require_memory'), \
         patch('water10_v4.runtime.require_memory_budget', return_value={'required_bytes': 32 * 2**30}):
        result = QuantumComponent().execute_with_metadata('unused', 'unused', np.zeros((1, 30, 3)), 32768)
        z = result['features']
    expected = np.array([0.] * 30 + [-1., 1., 1.] * 10)[None]
    np.testing.assert_allclose(z, expected, atol=1e-14)
    assert result['executions'][0]['num_qubits'] == 3
    assert result['executions'][0]['method'] == 'statevector'
    assert result['executions'][0]['precision'] == 'double'


def test_old_training_history_cannot_be_silently_resumed():
    from water10_v4.parallel_training import train
    with patch('water10_v4.parallel_training.load_state', return_value={'plan': {}}):
        with pytest.raises(ValueError, match='Checkpoint backend'):
            train('/unused', 1, 10)
