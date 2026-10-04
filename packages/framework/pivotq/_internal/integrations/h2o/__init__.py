"""Optional H2O bridge. AIMD and Torch are loaded only when explicitly used."""


def register_components(framework):
    from .bridge import register_components as register
    return register(framework)


def run(framework, context):
    from .bridge import run as run_aimd
    return run_aimd(framework, context)


def __getattr__(name):
    if name in {"SimulatedQPUCircuitFeatureExtractor", "CPUQuantumFeaturesComponent", "CPUClassicalSessionsComponent"}:
        from . import adapters
        return getattr(adapters, name)
    raise AttributeError(name)


__all__ = ["register_components", "run", "SimulatedQPUCircuitFeatureExtractor"]
