import { compileNative, scheduleNative } from './quantum-native';
import { probabilities, simulate, type Gate } from './quantum-simulator';

export function mountNativeCircuit(root: HTMLElement, getLogical: () => Gate[]) {
  const query = <T extends HTMLElement = HTMLElement>(selector: string) => root.querySelector<T>(selector)!;
  const panel = query('[data-native-panel]'), canvas = query('[data-native-canvas]'), progress = query<HTMLInputElement>('[data-native-progress]');
  const compile = query<HTMLButtonElement>('[data-native-compile]');
  let gates: Gate[] = [], columns: number[] = [], step = 0, showTime = false, signature = '';
  const update = () => {
    progress.value = String(step); query('[data-native-step]').textContent = `${step} / ${gates.length}`;
    const current = gates[step - 1]; query('[data-native-selection]').textContent = current ? `${current.type} · ${current.qubits.map(q => `q${q}`).join(' ↔ ')}${current.angle === undefined ? '' : ` · ${current.angle.toFixed(4)} rad`} · 时序 ${columns[step - 1]}` : '初态 |000⟩';
    canvas.querySelectorAll<HTMLElement>('[data-native-gate]').forEach(node => { const i = Number(node.dataset.nativeGate); node.classList.toggle('is-selected', i === step - 1); node.classList.toggle('is-pending', i >= step); node.setAttribute('aria-pressed', String(i === step - 1)); });
    const p = probabilities(simulate(gates, step), 'Z');
    const distribution = query('[data-native-probabilities]'); distribution.replaceChildren();
    p.forEach((value, i) => { const cell = document.createElement('span'); cell.textContent = `${i.toString(2).padStart(3, '0')} ${(100 * value).toFixed(2)}%`; distribution.append(cell); });
    const cursor = canvas.querySelector<HTMLElement>('.native-cursor'); if (cursor) cursor.style.left = `${step ? 74 + (columns[step - 1] - 1) * 62 : 48}px`;
    panel.dataset.step = String(step);
  };
  function render() {
    canvas.replaceChildren(); const depth = Math.max(1, ...columns); const width = Math.max(720, 150 + depth * 62); canvas.style.width = `${width}px`;
    for (let q = 0; q < 3; q++) { const wire = document.createElement('div'); wire.className = 'qc-wire'; wire.style.top = `${62 + q * 58}px`; const label = document.createElement('span'); label.className = 'qc-wire-label'; label.style.top = wire.style.top; label.textContent = `q${q}`; canvas.append(wire, label); }
    gates.forEach((gate, i) => {
      const button = document.createElement('button'); button.type = 'button'; button.className = `native-gate${gate.type === 'CZ' ? ' native-cz' : ''}`; button.dataset.nativeGate = String(i);
      const lo = Math.min(...gate.qubits), hi = Math.max(...gate.qubits);
      button.style.left = `${54 + (columns[i] - 1) * 62}px`; button.style.top = `${42 + lo * 58}px`; button.style.height = `${40 + (hi - lo) * 58}px`;
      button.textContent = gate.type; button.setAttribute('aria-label', `原生门 ${i + 1} ${gate.type} ${gate.qubits.map(q => `q${q}`).join(' ')}`); button.title = `${gate.type} ${gate.angle?.toFixed(4) ?? ''} · 点击查看此步状态`;
      button.addEventListener('click', () => { step = i + 1; update(); }); canvas.append(button);
    });
    for (let i = 1; i <= depth; i++) { const line = document.createElement('div'); line.className = 'native-time-line'; line.style.left = `${74 + (i - 1) * 62}px`; line.textContent = String(i); canvas.append(line); }
    const cursor = document.createElement('div'); cursor.className = 'native-cursor'; canvas.append(cursor); canvas.classList.toggle('show-time', showTime); update();
  }
  compile.addEventListener('click', () => {
    const logical = getLogical();
    try {
      const native = compileNative(logical), a = simulate(logical), b = simulate(native);
      let re = 0, im = 0; a.re.forEach((r, i) => { re += r * b.re[i] + a.im[i] * b.im[i]; im += r * b.im[i] - a.im[i] * b.re[i]; });
      if (Math.abs(re * re + im * im - 1) > 1e-9) throw new Error('分解后状态不一致');
      gates = native; columns = scheduleNative(gates); step = gates.length; signature = JSON.stringify(logical); panel.hidden = false;
      progress.max = String(gates.length); query('[data-native-summary]').textContent = `${gates.length} 个原生门 · 深度 ${Math.max(0, ...columns)} · CZ ${gates.filter(g=>g.type === 'CZ').length} · 线形连接 q0–q1–q2`;
      query('[data-native-status]').textContent = '分解完成，理想态等价性校验通过'; compile.textContent = '重新编译'; render();
    } catch (error) { panel.hidden = false; query('[data-native-status]').textContent = `编译失败：${error instanceof Error ? error.message : '请检查电路'}`; }
  });
  query('[data-native-clock]').addEventListener('click', () => { showTime = !showTime; query('[data-native-clock]').setAttribute('aria-pressed', String(showTime)); canvas.classList.toggle('show-time', showTime); });
  progress.addEventListener('input', () => { step = Number(progress.value); update(); });
  query('[data-native-next]').addEventListener('click', () => { if (gates.length) step = step >= gates.length ? 1 : step + 1; update(); });
  query('[data-native-start]').addEventListener('click', () => { step = 0; update(); });
  const stale = () => queueMicrotask(() => { if (signature && signature !== JSON.stringify(getLogical())) { panel.hidden = true; signature = ''; compile.textContent = '编译原生电路'; } });
  root.addEventListener('input', stale); root.addEventListener('click', stale); root.addEventListener('pointerup', stale);
}
