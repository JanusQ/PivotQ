import type { Gate } from './quantum-simulator';

export interface CircuitOperation {
  gate: Gate;
  expression?: string;
  source: number;
  origin: number;
}

// The parameterized F2/A2 model in public/aimd/generate_circuit.py.
// No illustrative training or geometry values are bound here.
export function modelCircuit(): CircuitOperation[] {
  const operations: CircuitOperation[] = [];
  const add = (type: Gate['type'], qubits: number[], stage: string, source: number, expression?: string, word?: string) => {
    operations.push({ gate: { id: `model-${operations.length}`, type, qubits, stage, word }, source, origin: operations.length, expression });
  };
  for (let q = 0; q < 3; q++) add('Ry', [q], '几何编码', 1, `enc[${q}]`);
  for (let q = 0; q < 3; q++) add('Ry', [q], '初始层', 4, `theta[${q}]`);
  add('CZ', [0, 1], '初始层', 5); add('CZ', [1, 2], '初始层', 6);
  for (let q = 0; q < 3; q++) add('Rx', [q], '初始层', 8, `theta[${q + 3}]`);
  ['IYZ', 'YII', 'YZI', 'IIX', 'YII'].forEach((word, i) => add('Pauli', [0, 1, 2].filter(q => word[q] !== 'I'), 'ADAPT 层', 10, `theta[${i + 6}]`, word));
  return operations;
}

// Use the same inverse basis-change sequence as the exported model.
// Expressions stay symbolic; physical gates are not fitted to the CSV.
export function physicalCircuit(logical: CircuitOperation[]): CircuitOperation[] {
  const result: CircuitOperation[] = [];
  for (const operation of logical) {
    const { gate, source } = operation;
    const add = (type: Gate['type'], qubits: number[], expression?: string, angle?: number) => result.push({ gate: { id: `physical-${result.length}`, type, qubits, angle, stage: gate.stage }, expression, source, origin: operation.origin });
    const h = (q: number, inverse = false) => {
      if (inverse) { add('Ry', [q], '−π/2', -Math.PI / 2); add('Rz', [q], '−π', -Math.PI); }
      else { add('Rz', [q], 'π', Math.PI); add('Ry', [q], 'π/2', Math.PI / 2); }
    };
    const rx = (q: number, expression: string, angle?: number) => { add('Rz', [q], 'π/2', Math.PI / 2); add('Ry', [q], expression, angle); add('Rz', [q], '−π/2', -Math.PI / 2); };
    const cx = (a: number, b: number, inverse = false) => { h(b, inverse); add('CZ', [a, b]); h(b, inverse); };
    if (gate.type === 'Ry' || gate.type === 'Rz') add(gate.type, gate.qubits, operation.expression, gate.angle);
    else if (gate.type === 'CZ') add('CZ', gate.qubits);
    else if (gate.type === 'Rx') rx(gate.qubits[0], operation.expression!, gate.angle);
    else if (gate.type === 'Pauli') {
      const support = gate.qubits;
      for (const q of support) {
        if (gate.word![q] === 'X') h(q);
        if (gate.word![q] === 'Y') rx(q, 'π/2', Math.PI / 2);
      }
      for (let i = 0; i < support.length - 1; i++) cx(support[i], support[i + 1]);
      add('Rz', [support.at(-1)!], operation.expression, gate.angle);
      for (let i = support.length - 2; i >= 0; i--) cx(support[i], support[i + 1], true);
      for (const q of support.slice().reverse()) {
        if (gate.word![q] === 'X') h(q, true);
        if (gate.word![q] === 'Y') rx(q, '−π/2', -Math.PI / 2);
      }
    } else throw new Error('模型电路中出现不支持的门');
  }
  return result;
}

export function circuitLayers(operations: CircuitOperation[]): number[] {
  const latest = [0, 0, 0];
  return operations.map(({ gate }) => {
    // Include the intermediate wire so a multi-qubit gate cannot cross another gate.
    const wires = Array.from({ length: Math.max(...gate.qubits) - Math.min(...gate.qubits) + 1 }, (_, i) => Math.min(...gate.qubits) + i);
    const layer = Math.max(...wires.map(q => latest[q])) + 1;
    wires.forEach(q => latest[q] = layer);
    return layer;
  });
}
