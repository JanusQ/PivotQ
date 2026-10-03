import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadFrames, parseCSV } from '../src/lib/aimd-data.ts';
import { compileNative, scheduleNative } from '../src/lib/quantum-native.ts';
import { defaultCircuit, simulate } from '../src/lib/quantum-simulator.ts';

const log = readFileSync(new URL('../public/aimd/imported/md_log.csv', import.meta.url), 'utf8');
const positions = readFileSync(new URL('../public/aimd/imported/positions.csv', import.meta.url), 'utf8');
const frames = loadFrames(log, positions);
assert.equal(frames.length, 1001); assert.equal(frames.at(-1).step, 1000); assert.ok(Math.abs(frames.at(-1).time - 100) < 1e-8);
assert.equal(parseCSV('a,b,c\n1,"x,y",')[0].b, 'x,y');
assert.throws(() => loadFrames(log, positions.replace('0,0.0,', '1,0.0,')), /时间步/);
assert.throws(() => loadFrames(log.replace('0.5911674093739174', '3'), positions), /总能量/);
assert.throws(() => loadFrames(log, positions.replace('0.9266272064859951', '1.9')), /坐标与键长/);

const gate = (type, qubits, angle, word) => ({id:'test',type,qubits,angle,word,stage:'test'});
const seeds = [gate('Ry',[0],.3),gate('Rx',[1],-.9),gate('H',[2]),gate('CX',[2,0])];
const cases = [defaultCircuit(), ...['H','X','Ry','Rx','Rz'].flatMap(type=>[0,1,2].map(q=>[...seeds,gate(type,[q],-.743)])), ...[[0,1],[1,2],[0,2],[2,0],[1,0]].flatMap(pair=>['CZ','CX'].map(type=>[...seeds,gate(type,pair)])), ...['IYZ','YII','YZI','IIX','XXI','XIX','ZZZ','YYY'].map(word=>[...seeds,gate('Pauli',[0,1,2],.63,word)])];
for (const circuit of cases) {
  const native = compileNative(circuit);
  assert.ok(native.every(g=>['Ry','Rz','CZ'].includes(g.type)));
  assert.ok(native.filter(g=>g.type==='CZ').every(g=>Math.abs(g.qubits[0]-g.qubits[1])===1));
  const a = simulate(circuit), b = simulate(native);
  let re = 0, im = 0; a.re.forEach((r,i)=>{re+=r*b.re[i]+a.im[i]*b.im[i];im+=r*b.im[i]-a.im[i]*b.re[i];});
  assert.ok(Math.abs(re*re+im*im-1)<1e-11, `equivalence: ${JSON.stringify(circuit.at(-1))}`);
  const columns = scheduleNative(native); const last=[0,0,0]; native.forEach((g,i)=>g.qubits.forEach(q=>{assert.ok(columns[i]>last[q]);last[q]=columns[i];}));
}
console.log(`PASS: ${frames.length} frames aligned; energies and 3D geometry checked; malformed-data guards; ${cases.length} native decomposition/state/schedule cases.`);
console.log(`Imported total-energy change: ${frames.at(-1).values.total_energy_eV-frames[0].values.total_energy_eV} eV (shown without altering or reusing old summaries).`);
