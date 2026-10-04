"""Public Ray Job registration entrypoint, matching the single-water bridge."""
from .components import CLASSICAL_ID, QUANTUM_ID, ClassicalComponent, QuantumComponent
from .config import import_target, load_config


def register_fusion_components(framework, config):
    from pivotq._internal.framework import ComponentSpec, ExecutionMode, ResourceRequest
    if config['quantum_target'] == 'cpu':
        framework.register(ComponentSpec(component_id=QUANTUM_ID, execution=ExecutionMode.TASK,
            resources=ResourceRequest(num_cpus=config.get('quantum_num_threads', 1)),
            allowed_methods=('execute', 'execute_with_metadata'),
            timeout_seconds=config['quantum_timeout_seconds']), QuantumComponent)
    else:
        # The provider owns its QPU resource declaration, lifecycle and hardware mapping.
        import_target(config['qpu_registration'])(framework)
    framework.register(ComponentSpec(component_id=CLASSICAL_ID, execution=ExecutionMode.ACTOR,
        resources=ResourceRequest(num_cpus=.25, num_gpus=1 if config['classical_device'] == 'cuda' else 0),
        allowed_methods=('create', 'predict', 'terminate'), stateful=True, max_concurrency=1,
        timeout_seconds=config['classical_timeout_seconds']), ClassicalComponent)


def register_components(framework):
    register_fusion_components(framework, load_config())
