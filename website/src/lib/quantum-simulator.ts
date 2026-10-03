/** Three-qubit ideal state vector. Display order is q0 q1 q2 (q0 is MSB). */
export type GateType = 'H' | 'X' | 'Ry' | 'Rx' | 'Rz' | 'CZ' | 'CX' | 'Pauli';
export interface Gate {
  id: string;
  type: GateType;
  qubits: number[];
  angle?: number;
  word?: string;
  label?: string;
  stage: string;
}
export type Basis = 'Z' | 'X';
export type State = { re: number[]; im: number[] };
export const MAX_GATES = 32;
export const BASIS_LABELS = Array.from({ length: 8 }, (_, i) => i.toString(2).padStart(3, '0'));

export function defaultCircuit(): Gate[] {
  // Illustrative angles only; these are not the frozen AIMD training parameters.
  const gates: Gate[] = [];
  const add = (gate: Omit<Gate, 'id'>) => gates.push({ ...gate, id: `f2-${gates.length}` });
  [Math.PI / 4, Math.PI / 8, Math.PI / 4].forEach((angle, q) =>
    add({ type: 'Ry', qubits: [q], angle, label: `x${q}`, stage: '角度编码' }));
  [0.4, -0.6, 0.8].forEach((angle, q) =>
    add({ type: 'Ry', qubits: [q], angle, label: `θ${q}`, stage: '初始层' }));
  add({ type: 'CZ', qubits: [0, 1], stage: '初始层' });
  add({ type: 'CZ', qubits: [1, 2], stage: '初始层' });
  [0.3, -0.5, 0.7].forEach((angle, q) =>
    add({ type: 'Rx', qubits: [q], angle, label: `θ${q + 3}`, stage: '初始层' }));
  ['IYZ', 'YII', 'YZI', 'IIX', 'YII'].forEach((word, i) =>
    add({ type: 'Pauli', qubits: [0, 1, 2], word, angle: [0.45, -0.35, 0.55, 0.25, -0.2][i], label: `θ${i + 6}`, stage: 'ADAPT' }));
  return gates;
}

export function initialState(): State {
  return { re: [1, 0, 0, 0, 0, 0, 0, 0], im: Array(8).fill(0) };
}

export function applyGate(state: State, gate: Gate): State {
  const { re, im } = state;
  const out: State = { re: Array(8).fill(0), im: Array(8).fill(0) };
  if (!gate.qubits.length || gate.qubits.some(q => !Number.isInteger(q) || q < 0 || q > 2)) throw new Error('Invalid qubit');
  if (gate.angle !== undefined && !Number.isFinite(gate.angle)) throw new Error('Invalid angle');
  if (gate.type === 'CZ' || gate.type === 'CX') {
    const [control, target] = gate.qubits;
    if (gate.qubits.length !== 2 || control === target) throw new Error('Two distinct qubits required');
    const c = 1 << (2 - control), t = 1 << (2 - target);
    for (let i = 0; i < 8; i++) {
      const j = gate.type === 'CX' && (i & c) ? i ^ t : i;
      const sign = gate.type === 'CZ' && (i & c) && (i & t) ? -1 : 1;
      out.re[j] = re[i] * sign; out.im[j] = im[i] * sign;
    }
    return out;
  }
  if (gate.type === 'Pauli') {
    const word = gate.word ?? '';
    if (!/^[IXYZ]{3}$/.test(word) || word === 'III') throw new Error('Invalid Pauli word');
    const c = Math.cos((gate.angle ?? 0) / 2), s = Math.sin((gate.angle ?? 0) / 2);
    for (let i = 0; i < 8; i++) { out.re[i] = c * re[i]; out.im[i] = c * im[i]; }
    for (let i = 0; i < 8; i++) {
      let j = i, phaseRe = 1, phaseIm = 0;
      for (let q = 0; q < 3; q++) {
        const mask = 1 << (2 - q), bit = (i & mask) !== 0;
        if (word[q] === 'X' || word[q] === 'Y') j ^= mask;
        if (word[q] === 'Z' && bit) { phaseRe = -phaseRe; phaseIm = -phaseIm; }
        if (word[q] === 'Y') {
          const sign = bit ? -1 : 1;
          [phaseRe, phaseIm] = [-sign * phaseIm, sign * phaseRe];
        }
      }
      const pr = phaseRe * re[i] - phaseIm * im[i];
      const pi = phaseRe * im[i] + phaseIm * re[i];
      // exp(-i θP/2) = cos(θ/2) I - i sin(θ/2) P.
      out.re[j] += s * pi; out.im[j] -= s * pr;
    }
    return out;
  }
  const mask = 1 << (2 - gate.qubits[0]);
  const c = Math.cos((gate.angle ?? 0) / 2), s = Math.sin((gate.angle ?? 0) / 2);
  for (let a = 0; a < 8; a++) {
    if (a & mask) continue;
    const b = a | mask;
    if (gate.type === 'H') {
      out.re[a] = (re[a] + re[b]) / Math.SQRT2; out.im[a] = (im[a] + im[b]) / Math.SQRT2;
      out.re[b] = (re[a] - re[b]) / Math.SQRT2; out.im[b] = (im[a] - im[b]) / Math.SQRT2;
    } else if (gate.type === 'X') {
      out.re[a] = re[b]; out.im[a] = im[b]; out.re[b] = re[a]; out.im[b] = im[a];
    } else if (gate.type === 'Ry') {
      out.re[a] = c * re[a] - s * re[b]; out.im[a] = c * im[a] - s * im[b];
      out.re[b] = s * re[a] + c * re[b]; out.im[b] = s * im[a] + c * im[b];
    } else if (gate.type === 'Rx') {
      out.re[a] = c * re[a] + s * im[b]; out.im[a] = c * im[a] - s * re[b];
      out.re[b] = c * re[b] + s * im[a]; out.im[b] = c * im[b] - s * re[a];
    } else if (gate.type === 'Rz') {
      out.re[a] = c * re[a] + s * im[a]; out.im[a] = c * im[a] - s * re[a];
      out.re[b] = c * re[b] - s * im[b]; out.im[b] = c * im[b] + s * re[b];
    }
  }
  return out;
}

export function simulate(gates: Gate[], steps = gates.length): State {
  return gates.slice(0, steps).reduce(applyGate, initialState());
}

export function probabilities(state: State, basis: Basis): number[] {
  const measured = basis === 'X' ? [0, 1, 2].reduce((s, q) => applyGate(s, { id: '', type: 'H', qubits: [q], stage: '' }), state) : state;
  return measured.re.map((r, i) => r * r + measured.im[i] ** 2);
}

export function moments(state: State, basis: Basis): number[] {
  const p = probabilities(state, basis);
  // 1-, 2-, and 3-body correlators: q0, q1, q2, q0q1, q0q2, q1q2, q0q1q2.
  return [4, 2, 1, 6, 5, 3, 7].map(mask => p.reduce((sum, value, i) => {
    let parity = 0;
    for (let bits = i & mask; bits; bits >>= 1) parity ^= bits & 1;
    return sum + (parity ? -value : value);
  }, 0));
}
