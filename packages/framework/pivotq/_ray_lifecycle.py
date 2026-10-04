"""Share one process-wide Ray connection without taking over caller ownership."""

from dataclasses import dataclass, field
from importlib import import_module
from threading import RLock
from typing import Any
from uuid import uuid4

from .errors import UnavailableError

_lock = RLock()


@dataclass
class _Connection:
    ray: Any
    identity: tuple[str, str]
    owned: bool
    address: str | None
    leases: set[str] = field(default_factory=set)


_connection: _Connection | None = None


def _identity(ray: Any) -> tuple[str, str]:
    context = ray.get_runtime_context()
    return str(context.get_job_id()), str(context.get_node_id())


def acquire(address: str | None) -> tuple[Any, str]:
    """Connect lazily, recording whether the SDK created this connection."""
    global _connection
    with _lock:
        ray = import_module("ray")
        if _connection is not None:
            if not ray.is_initialized() or _identity(ray) != _connection.identity:
                raise UnavailableError("Ray connection changed while a PivotQ runtime was active")
            if address not in (None, "auto", _connection.address):
                raise ValueError("another PivotQ runtime already uses a different Ray address")
        else:
            owned = not ray.is_initialized()
            if owned:
                ray.init(address=address or "local")
            elif address not in (None, "auto"):
                raise ValueError("Ray is already initialized; omit address to reuse it")
            _connection = _Connection(ray, _identity(ray), owned, address)
        token = uuid4().hex
        _connection.leases.add(token)
        return ray, token


def release(token: str) -> None:
    """Disconnect only the last lease of an SDK-created connection."""
    global _connection
    with _lock:
        connection = _connection
        if connection is None or token not in connection.leases:
            return
        connection.leases.remove(token)
        if connection.leases:
            return
        _connection = None
        if (connection.owned and connection.ray.is_initialized()
                and _identity(connection.ray) == connection.identity):
            connection.ray.shutdown()
