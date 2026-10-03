import assert from 'node:assert/strict';
import { modelCircuit, physicalCircuit, circuitLayers } from '../src/lib/aimd-circuit.ts';
import { simulate } from '../src/lib/quantum-simulator.ts';

const model = modelCircuit(), physical = physicalCircuit(model);
assert.equal(model.length,16);
assert.equal(new Set(model.filter(op=>op.expression).map(op=>op.expression)).size,14);
assert.ok(model.every(op=>op.gate.angle===undefined),'No demo angles bound to the displayed model');
assert.ok(physical.every(op=>['Ry','Rz','CZ'].includes(op.gate.type)));
assert.ok(physical.filter(op=>op.gate.type==='CZ').every(op=>Math.abs(op.gate.qubits[0]-op.gate.qubits[1])===1));
assert.ok(physical.every(op=>model.some(original=>original.source===op.source)));
assert.ok(physical.every(op=>model[op.origin].source===op.source));
const bind=(operations,values)=>operations.map(op=>({...op.gate,angle:op.expression&&Object.hasOwn(values,op.expression)?values[op.expression]:op.gate.angle}));
for(let trial=0;trial<12;trial++) {
  const values={};
  model.forEach((op,i)=>{if(op.expression)values[op.expression]=Math.sin((trial+1)*(i+1)) * 2.8;});
  const a=simulate(bind(model,values)), b=simulate(bind(physical,values));
  let re=0,im=0;
  a.re.forEach((r,i)=>{re+=r*b.re[i]+a.im[i]*b.im[i];im+=r*b.im[i]-a.im[i]*b.re[i];});
  assert.ok(Math.abs(re*re+im*im-1)<1e-11,`Parameterized native decomposition equivalence ${trial}`);
}
for(const operations of [model,physical]) {
  const columns=circuitLayers(operations), busy=[0,0,0];
  operations.forEach((op,i)=>{for(let q=Math.min(...op.gate.qubits);q<=Math.max(...op.gate.qubits);q++){assert.ok(columns[i]>busy[q]);busy[q]=columns[i];}});
}
console.log(`PASS: actual symbolic F2/A2 structure, 14 unbound parameters, ${physical.length} native gates, source links, 12 bound state-equivalence cases, collision-free layers.`);
