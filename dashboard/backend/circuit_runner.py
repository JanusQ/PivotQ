"""Execute validated circuit IR using a resource-bound FusionFramework task."""
import json
import math
import os
from pathlib import Path
import time
from .program import digest
from .circuit_parser import parse_quantum_circuit

def simulate(circuit, shots, seed, device='cuda'):
    import torch
    n = circuit['qubits']
    state = torch.zeros(2**n, dtype=torch.complex128, device=device)
    state[0] = 1
    for gate in circuit['gates']:
        name, args = gate['name'], gate['args']
        if name == 'MEASURE':
            continue
        if name in ('CX','CZ'):
            indices = torch.arange(2**n, device=device)
            control, target = [1 << (n-1-q) for q in args]
            active = (indices & control) != 0
            if name == 'CX':
                state = state[torch.where(active, indices ^ target, indices)]
            else:
                state = state * torch.where(active & ((indices & target) != 0), -1, 1)
            continue
        q = args[-1]
        matrices = {'H':[[1/math.sqrt(2),1/math.sqrt(2)],[1/math.sqrt(2),-1/math.sqrt(2)]],
                    'X':[[0,1],[1,0]], 'Y':[[0,-1j],[1j,0]], 'Z':[[1,0],[0,-1]]}
        if name in ('RX','RY','RZ'):
            c,s = math.cos(args[0]/2),math.sin(args[0]/2)
            matrix = {'RX':[[c,-1j*s],[-1j*s,c]],'RY':[[c,-s],[s,c]],'RZ':[[c-1j*s,0],[0,c+1j*s]]}[name]
        else:
            matrix = matrices[name]
        order = [q] + [i for i in range(n) if i != q]
        inverse = [order.index(i) for i in range(n)]
        moved = state.reshape([2]*n).permute(order).reshape(2,-1)
        state = (torch.tensor(matrix,dtype=state.dtype,device=device) @ moved).reshape([2]*n).permute(inverse).reshape(-1)
    probabilities = state.abs().square()
    generator = torch.Generator(device=device).manual_seed(seed)
    sampled = torch.multinomial(probabilities, shots, replacement=True, generator=generator)
    counts = torch.bincount(sampled,minlength=2**n)
    return {format(i,f'0{n}b'):float(p) for i,p in enumerate(probabilities.tolist()) if p > 1e-12}, {format(i,f'0{n}b'):int(c) for i,c in enumerate(counts.tolist()) if c}

def verify(program):
    value = dict(program)
    expected = value.pop('execution_sha256')
    if digest(json.dumps(value,sort_keys=True,ensure_ascii=True)) != expected or digest(program['source']) != program['source_sha256']:
        raise ValueError('程序快照校验失败')
    actual = parse_quantum_circuit(program['source'])
    if not actual['valid'] or actual != program['circuit']:
        raise ValueError('执行电路与源代码不一致')

class CircuitComponent:
    device = 'cuda'

    def describe(self):
        return {'name':'editor-circuit','component_api_version':'1.0','execution':'task','allowed_methods':['execute']}

    def execute(self, program):
        import torch
        import ray
        verify(program)
        if self.device == 'cuda' and (not torch.cuda.is_available() or not ray.get_runtime_context().get_accelerator_ids().get('GPU')):
            raise RuntimeError('未分配真实 CUDA GPU；禁止回退到 CPU')
        if self.device == 'cuda':
            torch.cuda.synchronize()
        started = time.perf_counter()
        probabilities, counts = simulate(program['circuit'],program['inputs']['shots'],program['inputs']['seed'],device=self.device)
        if self.device == 'cuda':
            torch.cuda.synchronize()
        elapsed = time.perf_counter()-started
        device_name = torch.cuda.get_device_name(0) if self.device == 'cuda' else 'CPU'
        return {'probabilities':probabilities,'counts':counts,'seconds':elapsed,'compute_seconds':elapsed,
                'source_sha256':program['source_sha256'],'execution_sha256':program['execution_sha256'],
                'device_name':device_name,'actual_device':'gpu' if self.device == 'cuda' else 'cpu',
                **({'gpu_name':device_name} if self.device == 'cuda' else {}),
                'ray_node_id':ray.get_runtime_context().get_node_id(),
                'accelerator_ids':ray.get_runtime_context().get_accelerator_ids(),'bit_order':'q0 → q(n−1)'}

class CPUCircuitComponent(CircuitComponent):
    device = 'cpu'

def register_cpu_components(framework):
    from pivotq._internal.framework import ComponentSpec, ExecutionMode, ResourceRequest
    target = os.environ.get('CIRCUIT_LOGICAL_TARGET', 'cpu')
    if target not in {'cpu', 'gpu', 'qpu'}:
        raise ValueError('Unsupported logical circuit target')
    if target != 'cpu' and not framework.simulation:
        raise ValueError('Virtual circuit targets require simulation mode')
    framework.register(ComponentSpec(component_id='editor-circuit',execution=ExecutionMode.TASK,
        resources=ResourceRequest(num_cpus=1, num_gpus=1 if target == 'gpu' else 0,
                                  custom_resources={'QPU': 1} if target == 'qpu' else {}),
        allowed_methods=('execute',),timeout_seconds=120),CPUCircuitComponent)
    if target != 'cpu':
        framework.register_simulation_adapter(
            'editor-circuit', factory=CPUCircuitComponent,
            resources=ResourceRequest(num_cpus=1), required_devices=(target.upper(),),
            availability=lambda: False, backend='torch_cpu_statevector',
        )

def register_components(framework):
    from pivotq._internal.framework import ComponentSpec, ExecutionMode, ResourceRequest
    framework.register(ComponentSpec(component_id='editor-circuit',execution=ExecutionMode.TASK,
        resources=ResourceRequest(num_cpus=1,num_gpus=1,custom_resources=json.loads(os.environ['CIRCUIT_NODE_RESOURCES'])),
        allowed_methods=('execute',),timeout_seconds=120),CircuitComponent)

def run_circuit(framework, context):
    started = time.perf_counter()
    program_path = os.environ.get('CIRCUIT_PROGRAM_PATH')
    program = json.loads(Path(program_path).read_text(encoding='utf-8') if program_path else os.environ['CIRCUIT_PROGRAM_JSON'])
    verify(program)
    handle = framework.submit('editor-circuit','execute',program,invocation_id=context.run_id+'.circuit')
    try:
        result = framework.result(handle)
        if not result.succeeded:
            raise result.error or RuntimeError('Circuit execution failed')
        actual = result.value
    finally:
        framework.release(handle)
    actual['worker_seconds'] = time.perf_counter()-started
    actual['runtime_execution'] = framework.execution_report()
    actual['target_snapshots'] = program.get('target_snapshots', {})
    actual['hardware_targets'] = program['hardware_targets']
    actual['logical_qubits'] = program['circuit']['qubits']
    out = Path(context.output_dir) / f'{context.run_id}.circuit-result.json'
    out.write_text(json.dumps(actual,ensure_ascii=False),encoding='utf-8')
    if context.trace_collector is not None:
        from pivotq._internal.observability import export_trace_jsonl
        export_trace_jsonl(context.trace_collector, Path(context.output_dir) / f'{context.run_id}.trace.jsonl')
