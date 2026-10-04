"""Connection ownership tests without starting a Ray process."""

from unittest.mock import patch

import pytest

from pivotq import _ray_lifecycle as lifecycle


class FakeRay:
    def __init__(self, initialized=False):
        self.initialized = initialized
        self.init_calls = []
        self.shutdown_calls = 0
        self.generation = 1

    def is_initialized(self):
        return self.initialized

    def init(self, **kwargs):
        self.init_calls.append(kwargs)
        self.initialized = True

    def shutdown(self):
        self.shutdown_calls += 1
        self.initialized = False

    def get_runtime_context(self):
        return self

    def get_job_id(self):
        return str(self.generation)

    def get_node_id(self):
        return "node"


@pytest.fixture(autouse=True)
def reset_connection():
    previous = lifecycle._connection
    lifecycle._connection = None
    yield
    lifecycle._connection = previous


def test_sdk_owned_connection_survives_until_last_runtime():
    ray = FakeRay()
    with patch.object(lifecycle, "import_module", return_value=ray):
        _, first = lifecycle.acquire("local")
        _, second = lifecycle.acquire(None)
        lifecycle.release(first)
        assert ray.is_initialized()
        assert not ray.shutdown_calls
        lifecycle.release(second)
        assert ray.shutdown_calls == 1
        assert ray.init_calls == [{"address": "local"}]
        lifecycle.release(second)
        assert ray.shutdown_calls == 1


def test_external_ray_connection_is_never_shutdown():
    ray = FakeRay(initialized=True)
    with patch.object(lifecycle, "import_module", return_value=ray):
        _, first = lifecycle.acquire(None)
        _, second = lifecycle.acquire("auto")
        lifecycle.release(first)
        lifecycle.release(second)
        assert ray.is_initialized()
        assert not ray.init_calls
        assert not ray.shutdown_calls


def test_conflicting_explicit_address_does_not_silently_reuse_external_ray():
    ray = FakeRay(initialized=True)
    with patch.object(lifecycle, "import_module", return_value=ray):
        with pytest.raises(ValueError, match="already initialized"):
            lifecycle.acquire("local")
        assert not ray.shutdown_calls


def test_external_reinitialization_is_not_shutdown_by_old_runtime():
    ray = FakeRay()
    with patch.object(lifecycle, "import_module", return_value=ray):
        _, token = lifecycle.acquire(None)
        ray.generation += 1
        lifecycle.release(token)
        assert not ray.shutdown_calls
