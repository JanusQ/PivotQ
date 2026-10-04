import json
import pytest
from pivotq._internal.qpu_integration.component import QPUClientFactory
from pivotq._internal.qpu_integration.device_adapter import DeviceProtocolNotConfiguredError


def test_device_id_selects_its_own_node_local_credentials(tmp_path, monkeypatch):
    config = tmp_path / 'devices.json'
    config.write_text(json.dumps({'qpu-a': {'url': 'http://device-a', 'api_key': 'a'},
                                 'qpu-b': {'url': 'http://device-b', 'api_key': 'b', 'timeout_seconds': 1800}}))
    monkeypatch.setenv('QPU_DEVICE_CONFIG_FILE', str(config))
    monkeypatch.setenv('QPU_DEVICE_ID', 'qpu-b')
    client = QPUClientFactory()()
    assert client._adapter._server_url == 'http://device-b'
    assert client._adapter._api_key == 'b'
    assert client._adapter._probability_source == 'expr_prob'
    assert client._adapter._timeout_seconds == 1800


def test_unknown_device_does_not_fall_back_to_global_endpoint(tmp_path, monkeypatch):
    config = tmp_path / 'devices.json'
    config.write_text('{}')
    monkeypatch.setenv('QPU_DEVICE_CONFIG_FILE', str(config))
    monkeypatch.setenv('QPU_DEVICE_ID', 'missing')
    monkeypatch.setenv('QPU_DEVICE_URL', 'http://unrelated-device')
    with pytest.raises(DeviceProtocolNotConfiguredError, match='configuration is unavailable'):
        QPUClientFactory()()


@pytest.mark.parametrize('timeout', [-1, 0, float('nan'), 90000, True])
def test_invalid_device_timeout_is_rejected(timeout):
    from pivotq._internal.qpu_integration.device_adapter import QPUDeviceAdapter
    with pytest.raises(DeviceProtocolNotConfiguredError):
        QPUDeviceAdapter(timeout_seconds=timeout)
