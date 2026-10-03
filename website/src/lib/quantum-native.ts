import type { Gate } from './quantum-simulator';

/** Exact gate decomposition onto the three-qubit linear Ry/Rz/CZ gate set. */
export function compileNative(logical: Gate[]): Gate[] {
  const native: Gate[] = [];
  let stage = '';
  const add = (type: 'Ry' | 'Rz' | 'CZ', qubits: number[], angle?: number) => native.push({ id: `native-${native.length}`, type, qubits: [...qubits], angle, stage });
  const h = (q: number) => { add('Rz', [q], Math.PI); add('Ry', [q], Math.PI / 2); };
  const rx = (q: number, angle: number) => { add('Rz', [q], Math.PI / 2); add('Ry', [q], angle); add('Rz', [q], -Math.PI / 2); };
  const adjacentCX = (control: number, target: number) => { h(target); add('CZ', [control, target]); h(target); };
  const swap = (a: number, b: number) => { adjacentCX(a, b); adjacentCX(b, a); adjacentCX(a, b); };
  const cx = (control: number, target: number) => {
    if (Math.abs(control - target) === 1) adjacentCX(control, target);
    else { swap(control, 1); adjacentCX(1, target); swap(control, 1); }
  };
  for (const gate of logical) {
    stage = gate.stage;
    if (!gate.qubits.length || gate.qubits.some(q => !Number.isInteger(q) || q < 0 || q > 2) || (gate.angle !== undefined && !Number.isFinite(gate.angle))) throw new Error('无法编译无效量子门');
    const q = gate.qubits[0];
    if (gate.type === 'Ry' || gate.type === 'Rz') add(gate.type, [q], gate.angle ?? 0);
    else if (gate.type === 'Rx') rx(q, gate.angle ?? 0);
    else if (gate.type === 'H') h(q);
    else if (gate.type === 'X') { add('Ry', [q], Math.PI); add('Rz', [q], Math.PI); }
    else if (gate.type === 'CX' || gate.type === 'CZ') {
      const target = gate.qubits[1]; if (target === undefined || target === q) throw new Error('双比特门必须作用于不同的比特');
      if (gate.type === 'CX') cx(q, target);
      else if (Math.abs(q - target) === 1) add('CZ', [q, target]);
      else { swap(q, 1); add('CZ', [1, target]); swap(q, 1); }
    } else if (gate.type === 'Pauli') {
      const word = gate.word ?? ''; if (!/^[IXYZ]{3}$/.test(word) || word === 'III') throw new Error('无效的 Pauli 算符');
      const active = [0, 1, 2].filter(i => word[i] !== 'I'), target = active.at(-1)!;
      for (const bit of active) { if (word[bit] === 'X') h(bit); if (word[bit] === 'Y') rx(bit, Math.PI / 2); }
      active.slice(0, -1).forEach(bit => cx(bit, target)); add('Rz', [target], gate.angle ?? 0);
      active.slice(0, -1).reverse().forEach(bit => cx(bit, target));
      for (const bit of active.slice().reverse()) { if (word[bit] === 'X') h(bit); if (word[bit] === 'Y') rx(bit, -Math.PI / 2); }
    } else throw new Error('不支持该量子门');
  }
  return native;
}

export function scheduleNative(gates: Gate[]) {
  const latest = [0, 0, 0];
  return gates.map(gate => { const column = Math.max(...gate.qubits.map(q => latest[q])) + 1; gate.qubits.forEach(q => latest[q] = column); return column; });
}
