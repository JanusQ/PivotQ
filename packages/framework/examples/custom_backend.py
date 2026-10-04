"""Register an offline quantum provider: python custom_backend.py --executor ray.

The same provider can be implemented in a separate installed Python package.
No private PivotQ interfaces are needed, and no physical device is contacted.
"""

import argparse
import json

from pivotq import Runtime
from pivotq.providers import BackendCapabilities, ProviderResult, QuantumRequest


class CustomStatevectorProvider:
    def __init__(self, *, source="example_statevector_samples"):
        self.source = source

    def run(self, request: QuantumRequest) -> ProviderResult:
        from qiskit.quantum_info import Statevector

        # PivotQ supplies a bound, measurement-free copy. Return all logical
        # qubits in q[n-1]...q0 order; PivotQ restores the user's measurements.
        state = Statevector.from_instruction(request.circuit)
        state.seed(request.seed)
        counts = state.sample_counts(shots=request.shots)
        return ProviderResult(
            shots=request.shots,
            source=self.source,
            counts={str(key): int(count) for key, count in counts.items()},
        )

    def close(self):
        # Close an HTTP client or vendor SDK session here if one is used.
        pass


def build_circuit():
    from qiskit import QuantumCircuit

    circuit = QuantumCircuit(3, 2)
    circuit.x(0)
    circuit.h(2)
    circuit.measure(0, 1)
    circuit.measure(2, 0)
    return circuit


def summarize(result):
    return {
        "backend": result.backend,
        "is_simulated": result.is_simulated,
        "counts": result.counts,
        "probabilities": result.probabilities,
        "shots": result.shots,
        "bit_order": result.bit_order,
        "source": result.metadata["source"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor", choices=("local", "ray"), default="local")
    parser.add_argument("--shots", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    with Runtime(executor=args.executor) as runtime:
        runtime.register_quantum_backend(
            "custom-simulator", CustomStatevectorProvider,
            capabilities=BackendCapabilities(max_qubits=16, is_simulated=True, supports_seed=True),
        )
        backend = runtime.quantum_backend("custom-simulator", source="example_statevector_samples")
        circuit = runtime.submit(build_circuit)
        measurement = backend.submit(circuit, shots=args.shots, seed=args.seed)
        summary = runtime.submit(summarize, measurement)
        print(json.dumps(runtime.get(summary), ensure_ascii=False, sort_keys=True))
        runtime.release(summary, measurement, circuit)


if __name__ == "__main__":
    main()
