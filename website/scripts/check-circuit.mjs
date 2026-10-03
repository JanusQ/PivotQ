import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { applyGate, defaultCircuit, initialState, probabilities, moments, simulate } from '../src/lib/quantum-simulator.ts';

const close = (actual, expected, description) => {
  assert.equal(actual.length, expected.length, description);
  actual.forEach((v, i) => assert.ok(Math.abs(v - expected[i]) < 1e-11, `${description}[${i}]: ${v} != ${expected[i]}`));
};
const gate = (type, qubits, angle) => ({ id: 'test', type, qubits, angle, stage: 'test' });
close(probabilities(initialState(), 'Z'), [1, 0, 0, 0, 0, 0, 0, 0], 'zero state');
close(probabilities(initialState(), 'X'), Array(8).fill(1 / 8), 'zero state in X');
close(probabilities(simulate([gate('X', [0])]), 'Z'), [0, 0, 0, 0, 1, 0, 0, 0], 'q0 is leftmost');
close(probabilities(simulate([gate('X', [2])]), 'Z'), [0, 1, 0, 0, 0, 0, 0, 0], 'q2 is rightmost');
close(probabilities(simulate([gate('H', [0]), gate('H', [0])]), 'Z'), [1, 0, 0, 0, 0, 0, 0, 0], 'H squared');
const bell = simulate([gate('H', [0]), gate('CX', [0, 1])]);
close(probabilities(bell, 'Z'), [.5, 0, 0, 0, 0, 0, .5, 0], 'Bell pair');
close(moments(bell, 'Z'), [0, 0, 1, 1, 0, 0, 1], 'Bell Z correlations');
close(probabilities(simulate([gate('H', [0]), gate('H', [1]), gate('CZ', [0, 1]), gate('H', [1])]), 'Z'), [.5, 0, 0, 0, 0, 0, .5, 0], 'CZ interference');
close(probabilities(simulate([gate('H', [0]), gate('Rz', [0], Math.PI), gate('H', [0])]), 'Z'), [0, 0, 0, 0, 1, 0, 0, 0], 'Rz relative phase');
close(simulate([gate('Ry', [0], Math.PI / 2)]).re, [Math.SQRT1_2, 0, 0, 0, Math.SQRT1_2, 0, 0, 0], 'Ry sign');
close(simulate([gate('Rx', [0], Math.PI)]).im, [0, 0, 0, 0, -1, 0, 0, 0], 'Rx sign');
assert.throws(() => applyGate(initialState(), gate('Ry', [0], NaN)), /Invalid angle/);
assert.throws(() => applyGate(initialState(), gate('CZ', [1, 1])), /distinct/);
const fixtures = JSON.parse(readFileSync(new URL('./fixtures/f2-native-reference.json', import.meta.url)));
for (const [caseIndex, fixture] of fixtures.cases.entries()) {
  const circuit = defaultCircuit();
  let e = 0, s = 0, a = 0;
  for (const g of circuit) {
    if (g.stage === '角度编码') g.angle = fixture.encoding[e++];
    else if (g.stage === 'ADAPT') g.angle = fixture.adapt[a++];
    else if (g.angle !== undefined) g.angle = fixture.seed[s++];
  }
  const state = simulate(circuit);
  close(probabilities(state, 'Z'), fixture.z, `native F2 ${caseIndex} Z`);
  close(probabilities(state, 'X'), fixture.x, `native F2 ${caseIndex} X`);
  // Native gate compilation may introduce a physically irrelevant global phase.
  let overlapRe = 0, overlapIm = 0;
  state.re.forEach((r, i) => { overlapRe += r * fixture.re[i] + state.im[i] * fixture.im[i]; overlapIm += r * fixture.im[i] - state.im[i] * fixture.re[i]; });
  assert.ok(Math.abs(overlapRe ** 2 + overlapIm ** 2 - 1) < 1e-11, `native state fidelity ${caseIndex}`);
  for (let step = 0; step <= circuit.length; step++) {
    const p = probabilities(simulate(circuit, step), 'Z');
    assert.ok(Math.abs(p.reduce((a, b) => a + b, 0) - 1) < 1e-12, 'every prefix is normalized');
  }
}
console.log('PASS: analytic gate/phase/endianness/Bell cases, 3 original native-compiler fixtures in Z/X, all 51 prefix norms.');
