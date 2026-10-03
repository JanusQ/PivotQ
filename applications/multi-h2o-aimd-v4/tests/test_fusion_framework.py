"""Run on pcie5 with the application and framework installed/on PYTHONPATH."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pytest

from water10_v4.integration.fusion_framework.model import FrozenModel, geometries, readouts
from water10_v4.integration.fusion_framework.config import load_config, resolve_template
from water10_v4.integration.fusion_framework.components import ClassicalComponent, CLASSICAL_ID
from water10_v4.integration.fusion_framework.client import FusionPotential
from water10_v4.integration.fusion_framework.qpu import QPUFeatures, bound_circuit_pair, decode_results
from water10_v4.integration.fusion_framework.registration import register_fusion_components
from water10_v4.integration.fusion_framework.runner import run_aimd, _trajectory, read_geometry
from water10_v4.integration.fusion_framework.submit_job import build_job_spec

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT/'models/final/best_model.json'
DIGEST = hashlib.sha256(MODEL.read_bytes()).hexdigest()


def config():
    c = resolve_template(ROOT/'configs/fusion_cpu.json', ROOT)
    c.update(model_path=str(MODEL), model_sha256=DIGEST)
    return c


def context(output=None):
    return SimpleNamespace(run_id='water10-test', output_dir=output,
        raise_if_stop_requested=lambda: None, stop_requested=False, trace_collector=None)


def distribution(identity='sample.X', basis='X'):
    return dict(circuit_id=identity, measurement_basis=basis, shots=100,
        measurement_qubits=list(range(30)), probabilities={'1'+'0'*29: .75, '0'*30: .25})


class Contracts(unittest.TestCase):
    def test_template_is_resolved_before_shared_runtime_config(self):
        with self.assertRaisesRegex(ValueError, 'absolute shared-cluster'):
            load_config(ROOT/'configs/fusion_cpu.json')
        resolved = resolve_template(ROOT/'configs/fusion_cpu.json', ROOT)
        self.assertEqual(Path(resolved['model_path']), MODEL)
        self.assertEqual(Path(resolved['geometry_path']), ROOT/'configs/fusion_geometry.json')
        self.assertEqual(resolved['model_sha256'], DIGEST)

    def test_sparse_30bit_order_and_x_before_z(self):
        raw = [distribution(), distribution('sample.Z', 'Z')]
        raw[1]['probabilities'] = {'0'*29+'1': 1.}
        z = decode_results(raw, [('sample.X', 'X'), ('sample.Z', 'Z')], 100)
        self.assertEqual(z.shape, (1, 60))
        self.assertEqual(z[0, 0], -.5)
        self.assertEqual(z[0, 29], 1.)
        self.assertEqual(z[0, 30], 1.)
        self.assertEqual(z[0, 59], -1.)

    def test_reject_corrupt_results(self):
        base = [distribution(), distribution('sample.Z', 'Z')]
        changes = [dict(circuit_id='wrong'), dict(measurement_basis='Z'), dict(shots=99),
            dict(measurement_qubits=list(reversed(range(30)))), dict(probabilities={'0'*30: .1}),
            dict(probabilities={'000': 1.}), dict(probabilities={'0'*30: float('nan')}),
            dict(status='failed', error='device failure')]
        for change in changes:
            with self.subTest(change=change):
                raw = copy.deepcopy(base); raw[0].update(change)
                with self.assertRaises((ValueError, RuntimeError)):
                    decode_results(raw, [('sample.X', 'X'), ('sample.Z', 'Z')], 100)
        with self.assertRaises(ValueError):
            decode_results(base[:1], [('sample.X', 'X'), ('sample.Z', 'Z')], 100)

    def test_legacy_service_rejected_before_submission(self):
        with self.assertRaises(ValueError):
            QPUFeatures(SimpleNamespace(describe=lambda: dict(num_qubits=3)), shots=100)

    def test_qpu_bound_circuits_and_round_trip(self):
        seen = []
        def run(**kwargs):
            seen.append(kwargs)
            return [dict(distribution(r.circuit_id, r.measurement_basis), probabilities={'0'*30: 1.})
                    for r in kwargs['circuits']]
        service = SimpleNamespace(describe=lambda: dict(num_qubits=30, result_bit_order='q0..q29',
            measurement_bases=['X', 'Z']), run_quantum_circuits=run)
        qpu = QPUFeatures(service, shots=100, request_factory=lambda **k: SimpleNamespace(**k))
        np.testing.assert_equal(qpu.evaluate_batch([[], []]), np.ones((2, 60)))
        requests = seen[0]['circuits']
        self.assertEqual([r.measurement_basis for r in requests], ['X', 'Z', 'X', 'Z'])
        for r in requests:
            self.assertEqual(r.circuit.num_qubits, 30)
            self.assertEqual(r.circuit.num_clbits, 0)
            self.assertFalse(r.circuit.parameters)
            self.assertFalse(any(i.operation.name.startswith('save_') for i in r.circuit.data))
        self.assertEqual(requests[0].circuit.count_ops()['h'], 30)
        self.assertEqual(seen[0]['step'], 0)

    def test_shared_parameter_shift_is_per_instance_with_chain_factors(self):
        qpu = object.__new__(QPUFeatures)
        calls = []
        def evaluate(gates, shifts):
            calls.append(shifts)
            return np.array([np.ones(60)*2, np.zeros(60)])
        qpu.evaluate_batch = evaluate
        gates = [dict(parameter='a', coefficient=.5), dict(parameter='a', coefficient=-.2),
                 dict(parameter=None, coefficient=1)]
        jac = qpu.jacobian(gates, ['a'])
        np.testing.assert_allclose(jac, .3)
        self.assertEqual([s[0][0] for s in calls], [0, 1])
        self.assertEqual(calls[0][0][1], np.pi/2)

    def test_model_hash_and_input_contract(self):
        with self.assertRaises(ValueError):
            FrozenModel(MODEL, '0'*64)
        for bad in (np.zeros((1, 3, 3)), np.zeros((0, 30, 3)), np.full((1, 30, 3), np.nan)):
            with self.assertRaises(ValueError): geometries(bad)
        for bad in (np.zeros((1, 14)), np.ones((1, 60))*1.1):
            with self.assertRaises(ValueError): readouts(bad)

    def test_classical_cpu_matches_training_tanh_network_and_cleanup(self):
        from water10_v4 import mlp_full
        model = FrozenModel(MODEL, DIGEST)
        z = np.random.default_rng(1).uniform(-1, 1, (4, 60))
        actor = ClassicalComponent(); actor.create(str(MODEL), DIGEST, 'cpu')
        n = model.state['normalizer']
        expected = n['energy_mean_ev'] + n['energy_scale_ev'] * mlp_full.predict(model.net, z)
        np.testing.assert_allclose(actor.predict(z), expected, atol=1e-12)
        actor.terminate(); actor.close()
        with self.assertRaises(RuntimeError): actor.predict(z)

    def test_no_cuda_fallback(self):
        with patch('torch.cuda.is_available', return_value=False):
            with self.assertRaises(RuntimeError): ClassicalComponent().create(str(MODEL), DIGEST, 'cuda')

    def test_fd_sign_shape_and_batch(self):
        obj = object.__new__(FusionPotential); obj.config = dict(fd_step_A=.001)
        batches = []
        def energy(batch):
            batches.append(batch)
            return (batch**2).sum(axis=(1, 2))
        obj.energy = energy
        r = np.arange(90).reshape(30, 3)/100
        e, f = obj.energy_force(r)
        np.testing.assert_allclose(f, -2*r, atol=1e-10)
        self.assertAlmostEqual(e, (r*r).sum())
        self.assertEqual(batches[0].shape, (181, 30, 3))

    def test_config_force_opt_in_and_legacy_qpu_gate(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'config.json'; c = config(); c['mode'] = 'aimd'
            p.write_text(json.dumps(c))
            with self.assertRaises(ValueError): load_config(p)
            c['mode'] = 'energy'; c['quantum_target'] = 'qpu'; p.write_text(json.dumps(c))
            with self.assertRaises(ValueError): load_config(p)

    def test_native_job_spec_and_shell_quoting(self):
        import shlex
        spec = build_job_spec(submission_id='test1', working_dir=str(ROOT),
            config_path='/shared/with space/config.json', output_dir='/shared/output')
        parts = shlex.split(spec.entrypoint)
        self.assertIn('ray_quantum.jobs.driver', parts)
        self.assertEqual(dict(spec.runtime_environment.env_vars)['WATER10_FUSION_CONFIG'], '/shared/with space/config.json')
        self.assertIn('water10_v4.integration.fusion_framework.runner:run_aimd', parts)


class FrameworkIntegration(unittest.TestCase):
    @pytest.mark.heavy
    def test_real_local_executor_cpu_inference_and_runner(self):
        from ray_quantum.framework import ComponentRegistry, FusionFramework
        from ray_quantum.executors import LocalExecutor
        from ray_quantum.observability import TraceCollector
        from water10_v4.parallel_training import FastSimulator
        from water10_v4.data import load_panel
        from water10_v4.revision import build_block_circuit
        sid = json.loads((ROOT/'models/final/circuit_source/display_manifest.json').read_text())['sample_id']
        positions = load_panel([sid])['positions_angstrom']
        c = config(); model = FrozenModel(MODEL, DIGEST)
        gates = model.gates(positions)[0]
        compiled, _ = FastSimulator().compile(gates)
        self.assertEqual(compiled, build_block_circuit(gates))
        x, z = bound_circuit_pair(gates)
        self.assertEqual(z[1], build_block_circuit(gates, readout=False))
        reference = model.energy(FastSimulator().evaluate(compiled)[None])
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            c['geometry_path'] = str(out/'geometry.json')
            Path(c['geometry_path']).write_text(json.dumps(dict(atomic_numbers=[8, 1, 1]*10,
                pbc=False, molecular_geometries_A=positions.tolist())))
            cfg = out/'config.json'; cfg.write_text(json.dumps(c))
            registry = ComponentRegistry(); trace = TraceCollector(max_records=100)
            fw = FusionFramework(LocalExecutor(registry, trace_collector=trace))
            try:
                register_fusion_components(fw, c)
                self.assertTrue(fw.describe(CLASSICAL_ID).stateful)
                ctx = context(out); ctx.trace_collector = trace
                with patch.dict('os.environ', WATER10_FUSION_CONFIG=str(cfg)):
                    run_aimd(fw, ctx)
                got = json.loads((out/'water10/energies.json').read_text())['energy_ev']
                np.testing.assert_allclose(got, reference, atol=1e-10, rtol=1e-10)
                summary = json.loads((out/'water10/run_summary.json').read_text())
                self.assertEqual(summary['status'], 'succeeded')
                self.assertEqual(summary['scientific_status'], 'not_validated')
                self.assertEqual(summary['calls']['quantum_batches'], 1)
                manifest = json.loads((out/'water10/artifacts.json').read_text())
                for name, row in manifest.items():
                    self.assertEqual(row['sha256'], hashlib.sha256((out/'water10'/name).read_bytes()).hexdigest())
                # A second session on the same real framework Actor must be possible.
                with FusionPotential(fw, context(), c):
                    pass
            finally:
                fw.close(); registry.close()

    def test_failed_invocation_release_and_body_exception_cleanup(self):
        class Framework:
            def __init__(self): self.methods = []; self.released = []
            def submit(self, component, method, *args, **kwargs): self.methods.append(method); return method
            def result(self, handle):
                return SimpleNamespace(succeeded=handle != 'execute_with_metadata', value=None, error='injected')
            def release(self, handle): self.released.append(handle)
        fw = Framework()
        with self.assertRaises(RuntimeError):
            with FusionPotential(fw, context(), config()) as p:
                p.energy(np.zeros((1, 30, 3)))
        self.assertEqual(fw.methods, ['create', 'execute_with_metadata', 'terminate'])
        self.assertEqual(fw.released, fw.methods)

    def test_unknown_terminal_not_released(self):
        fw = SimpleNamespace(submit=lambda *a, **k: 'h', result=lambda h: (_ for _ in ()).throw(TimeoutError()),
                             release=lambda h: self.fail('must not release unknown terminal'))
        obj = object.__new__(FusionPotential); obj.framework = fw; obj.context = context()
        with self.assertRaises(TimeoutError): obj.invoke('x', 'y')

    def test_runner_failure_and_stop_preserve_status(self):
        for stop in (False, True):
            with self.subTest(stop=stop), tempfile.TemporaryDirectory() as d:
                out = Path(d); c = config(); c['geometry_path'] = str(out/'missing.json')
                cfg = out/'config.json'; cfg.write_text(json.dumps(c))
                ctx = context(out); ctx.stop_requested = stop
                if stop:
                    ctx.raise_if_stop_requested = lambda: (_ for _ in ()).throw(InterruptedError('stop'))
                with patch.dict('os.environ', WATER10_FUSION_CONFIG=str(cfg)):
                    with self.assertRaises((FileNotFoundError, InterruptedError)):
                        run_aimd(None, ctx)
                summary = json.loads((out/'water10/run_summary.json').read_text())
                self.assertEqual(summary['status'], 'cancelled' if stop else 'failed')
                self.assertTrue((out/'water10/artifacts.json').exists())

    def test_ase_md_control_flow_and_cached_force_count_with_analytic_proxy(self):
        from ase.io import read
        class HarmonicPotential:
            calls = 0
            def energy_force(self, positions):
                self.calls += 1
                return float(.5*(positions**2).sum()), -positions
        c = config(); c.update(steps=2, temperature_K=0)
        potential = HarmonicPotential()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            _trajectory(potential, np.arange(90).reshape(30, 3)/100, c, context(out), out)
            rows = [json.loads(line) for line in (out/'md_log.jsonl').read_text().splitlines()]
            frames = read(out/'trajectory.traj', index=':')
            self.assertEqual([r['step'] for r in rows], [0, 1, 2])
            self.assertEqual(len(frames), 3)
            self.assertEqual(potential.calls, 3)
            self.assertTrue(np.isfinite(frames[-1].positions).all())

    def test_geometry_units_are_not_silently_reinterpreted(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'geometry.json'
            path.write_text(json.dumps(dict(atomic_numbers=[8, 1, 1]*10, pbc=False,
                position_unit='bohr', molecular_geometries_A=np.zeros((1, 30, 3)).tolist())))
            with self.assertRaises(ValueError): read_geometry(path)


if __name__ == '__main__':
    unittest.main()
