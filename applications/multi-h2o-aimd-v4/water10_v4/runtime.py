"""Runtime resource checks shared by local and framework CPU entrypoints."""
import math
from pathlib import Path, PurePosixPath
import re

import psutil


def _mount_path(value):
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)


def _cgroup_memory_limits(cgroup_text=None, mountinfo_text=None):
    """Read finite memory limits at the process cgroup and visible ancestors."""
    if cgroup_text is None:
        path = Path('/proc/self/cgroup')
        if not path.exists():
            return []
        cgroup_text = path.read_text()
    if mountinfo_text is None:
        mountinfo_text = Path('/proc/self/mountinfo').read_text()
    groups = {}
    for line in cgroup_text.splitlines():
        _, controllers, location = line.split(':', 2)
        if not controllers:
            groups['v2'] = location
        elif 'memory' in controllers.split(','):
            groups['v1'] = location
    limits = []
    visited = set()
    for line in mountinfo_text.splitlines():
        before, after = line.split(' - ', 1)
        fields, filesystem = before.split(), after.split()
        if filesystem[0] == 'cgroup2':
            kind, limit_name, usage_name = 'v2', 'memory.max', 'memory.current'
        elif filesystem[0] == 'cgroup' and 'memory' in filesystem[2].split(','):
            kind, limit_name, usage_name = 'v1', 'memory.limit_in_bytes', 'memory.usage_in_bytes'
        else:
            continue
        if kind not in groups:
            continue
        root = PurePosixPath(_mount_path(fields[3]))
        mount = Path(_mount_path(fields[4]))
        group = PurePosixPath(groups[kind])
        try:
            relative = group.relative_to(root)
        except ValueError:
            # A cgroup namespace reports '/' while mountinfo retains the host root.
            if group != PurePosixPath('/'):
                raise RuntimeError(f'Cannot locate {kind} memory cgroup {group} under {root}')
            relative = PurePosixPath('.')
        if '..' in relative.parts:
            raise RuntimeError('Invalid cgroup membership path')
        directory = mount.joinpath(*relative.parts)
        while True:
            key = (kind, str(directory))
            path = directory / limit_name
            if key not in visited and path.exists():
                visited.add(key)
                raw = path.read_text().strip()
                if raw != 'max':
                    limit = int(raw)
                    # Linux cgroup v1 uses a page-aligned LONG_MAX for unlimited.
                    if 0 <= limit < 2**60:
                        usage = int((directory / usage_name).read_text())
                        limits.append(dict(version=kind, path=str(directory), limit_bytes=limit,
                                           usage_bytes=usage, headroom_bytes=max(0, limit-usage)))
            if directory == mount:
                break
            directory = directory.parent
    return limits


def require_memory_budget(required_gib: float) -> dict:
    """Fail before allocation if host or container cannot provide this budget.

    This is a preflight snapshot, not a cross-process memory reservation.
    """
    if isinstance(required_gib, bool) or not isinstance(required_gib, (int, float)) \
            or not math.isfinite(required_gib) or required_gib <= 0:
        raise ValueError('required_gib must be finite and positive')
    required = math.ceil(required_gib * 2**30)
    host = int(psutil.virtual_memory().available)
    limits = _cgroup_memory_limits()
    container = min((row['headroom_bytes'] for row in limits), default=None)
    effective = min(host, container) if container is not None else host
    report = dict(required_bytes=required, host_available_bytes=host,
                  cgroup_headroom_bytes=container, effective_available_bytes=effective,
                  cgroup_limits=limits)
    if effective < required:
        raise MemoryError(f'CPU statevector needs {required_gib:g} GiB; '
                          f'host/cgroup effective available memory is {effective / 2**30:.2f} GiB. '
                          'No reduced-qubit or MPS fallback.')
    return report
