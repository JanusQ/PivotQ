"""Prediction normalization uses server snapshots without live execution services."""
import os
import unittest
from unittest.mock import patch
from backend import server
from backend.hardware import HardwareRegistry
from backend.hardware_profiles import target_snapshot
from backend.registry import validate_and_plan


class OfflinePredictionTests(unittest.TestCase):
    def test_ray_offline_allows_reference_cpu_and_quantum_prediction(self):
        body = {'task_id': 'h2o-hybrid-aimd', 'inputs': {'steps': 1},
                'hardware': {'classical_predict': 'cpu-0', 'quantum_features': 'fake-sc-36'}}
        with patch.dict(os.environ, {'FUSION_EXECUTOR': 'ray'}), \
             patch.object(server, 'HARDWARE', HardwareRegistry()), \
             patch.object(server, 'NETWORK_DEVICES', False), \
             patch.object(server, 'active_hardware', side_effect=AssertionError('must stay offline')):
            normalized = server._normalize_request(body, prediction=True)
            errors, plan = validate_and_plan(normalized, prediction=True)
            self.assertEqual(errors, [])
            self.assertIsNotNone(plan)
            self.assertEqual(normalized['hardware']['classical_predict'], 'cpu')
            self.assertEqual(normalized['target_snapshots']['quantum_features']['logical_qubits'], 3)
            self.assertIsNone(server.QPerfSimClient.prediction_reason(plan))

    def test_snapshot_digest_still_validated(self):
        body = {'task_id': 'h2o-hybrid-aimd', 'hardware': {'quantum_features': 'fake-sc-36'},
                'hardware_profile_digests': {'quantum_features': 'stale'}}
        with patch.object(server, 'HARDWARE', HardwareRegistry()), patch.object(server, 'NETWORK_DEVICES', False):
            with self.assertRaisesRegex(ValueError, '参数已更新'):
                server._normalize_request(body, prediction=True)
            body['hardware_profile_digests']['quantum_features'] = target_snapshot('fake-sc-36')['profile_sha256']
            normalized = server._normalize_request(body, prediction=True)
            self.assertEqual(normalized['target_snapshots']['quantum_features']['parameters']['qubits'], 36)
