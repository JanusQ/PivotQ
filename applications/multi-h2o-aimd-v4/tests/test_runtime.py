"""Host, cgroup v1/v2 and ancestor limits must bound large allocations."""
from types import SimpleNamespace

import pytest

from water10_v4 import runtime


def test_v2_nested_limit_and_parent_headroom(tmp_path):
    group = tmp_path/'job'
    group.mkdir()
    (group/'memory.max').write_text('max')
    (tmp_path/'memory.max').write_text(str(120*2**30))
    (tmp_path/'memory.current').write_text(str(40*2**30))
    mounts = f'1 0 0:1 / {tmp_path} rw - cgroup2 cgroup rw\n'
    limits = runtime._cgroup_memory_limits('0::/job\n', mounts)
    assert len(limits) == 1
    assert limits[0]['headroom_bytes'] == 80*2**30
    assert limits[0]['path'] == str(tmp_path)


def test_v1_container_mount_root_and_unlimited_value(tmp_path):
    (tmp_path/'memory.limit_in_bytes').write_text(str(128*2**30))
    (tmp_path/'memory.usage_in_bytes').write_text(str(8*2**30))
    mounts = f'1 0 0:1 /host/job {tmp_path} rw - cgroup cgroup rw,memory\n'
    limits = runtime._cgroup_memory_limits('4:memory:/host/job\n', mounts)
    assert limits[0]['headroom_bytes'] == 120*2**30
    # Membership may be relative to a private cgroup namespace.
    assert runtime._cgroup_memory_limits('4:memory:/\n', mounts) == limits
    (tmp_path/'memory.limit_in_bytes').write_text('9223372036854771712')
    assert runtime._cgroup_memory_limits('4:memory:/host/job\n', mounts) == []


def test_memory_budget_uses_smallest_available_bound(monkeypatch):
    monkeypatch.setattr(runtime.psutil, 'virtual_memory', lambda: SimpleNamespace(available=1000*2**30))
    monkeypatch.setattr(runtime, '_cgroup_memory_limits', lambda: [{'headroom_bytes': 80*2**30}])
    with pytest.raises(MemoryError, match='80.00 GiB'):
        runtime.require_memory_budget(96)
    assert runtime.require_memory_budget(32)['effective_available_bytes'] == 80*2**30
    monkeypatch.setattr(runtime, '_cgroup_memory_limits', lambda: [])
    assert runtime.require_memory_budget(96)['cgroup_headroom_bytes'] is None
    monkeypatch.setattr(runtime.psutil, 'virtual_memory', lambda: SimpleNamespace(available=4*2**30))
    with pytest.raises(MemoryError):
        runtime.require_memory_budget(32)


@pytest.mark.parametrize('required', [True, 0, -1, float('nan'), float('inf')])
def test_invalid_budget(required):
    with pytest.raises(ValueError):
        runtime.require_memory_budget(required)
