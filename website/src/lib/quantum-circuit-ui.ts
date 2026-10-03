import { BASIS_LABELS, MAX_GATES, defaultCircuit, moments, probabilities, simulate, type Basis, type Gate, type GateType } from './quantum-simulator';
import { mountNativeCircuit } from './native-circuit-ui';

const title = (gate: Gate) => gate.type === 'Pauli' ? `${gate.word}(${gate.label ?? 'θ'})` : `${gate.type}${gate.label ? `(${gate.label})` : ''}`;
const clone = (gates: Gate[]) => gates.map(g => ({ ...g, qubits: [...g.qubits] }));

export function mountCircuit(root: HTMLElement) {
  if (root.dataset.mounted) return;
  root.dataset.mounted = 'true';
  const el = <T extends HTMLElement = HTMLElement>(selector: string) => root.querySelector<T>(selector)!;
  const button = (action: string) => el<HTMLButtonElement>(`[data-action="${action}"]`);
  const canvas = el('[data-canvas]');
  const chart = el('[data-probabilities]');
  const number = el<HTMLInputElement>('[data-angle-number]');
  const angleSlider = el<HTMLInputElement>('[data-angle-slider]');
  const progress = el<HTMLInputElement>('[data-progress]');
  let gates = defaultCircuit(), selected = gates[0].id, step = gates.length, basis: Basis = 'Z';
  let pending: GateType | null = null, timer: ReturnType<typeof setInterval> | undefined;
  let counter = 0, modified = false;
  const history: { gates: Gate[]; selected: string; modified: boolean }[] = [];
  const announce = (text: string) => { el('[data-announcement]').textContent = text; };
  const save = () => {
    history.push({ gates: clone(gates), selected, modified });
    if (history.length > 50) history.shift();
    button('undo').disabled = false;
  };
  const pause = () => {
    if (timer) clearInterval(timer);
    timer = undefined;
    button('play').textContent = '▶ 播放过程';
    button('play').setAttribute('aria-pressed', 'false');
  };
  const make = <K extends keyof HTMLElementTagNameMap>(tag: K, className: string, text?: string) => {
    const node = document.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  BASIS_LABELS.forEach(label => {
    const group = make('div', 'qc-bar-group');
    group.append(make('span', 'qc-bar-value'), make('div', 'qc-bar'), make('span', 'qc-bar-label', label));
    chart.append(group);
  });

  function updateState() {
    const state = simulate(gates, step), p = probabilities(state, basis);
    progress.max = String(gates.length); progress.value = String(step);
    el('[data-progress-text]').textContent = `${step} / ${gates.length}`;
    el('[data-stage]').textContent = step === 0 ? '初态 |000⟩' : step === gates.length ? '全部完成' : `${gates[step - 1].stage} · ${title(gates[step - 1])}`;
    chart.querySelectorAll<HTMLElement>('.qc-bar-group').forEach((group, i) => {
      const percent = p[i] * 100;
      group.style.setProperty('--p', String(percent));
      const text = percent < 0.05 && percent > 1e-8 ? '<0.1%' : `${percent.toFixed(1)}%`;
      group.querySelector('.qc-bar-value')!.textContent = text;
      group.setAttribute('aria-label', `${BASIS_LABELS[i]}：${percent.toFixed(4)}%`);
      group.title = `${BASIS_LABELS[i]}：${percent.toFixed(4)}%`;
    });
    el('[data-prob-sum]').textContent = `概率合计 ${(p.reduce((a, b) => a + b, 0) * 100).toFixed(0)}%`;
    const featureRows = el('[data-features]');
    featureRows.replaceChildren();
    (['Z', 'X'] as Basis[]).forEach(b => {
      const row = make('tr', ''); row.append(make('th', '', b));
      moments(state, b).forEach(v => row.append(make('td', '', (Math.abs(v) < 0.00005 ? 0 : v).toFixed(4))));
      featureRows.append(row);
    });
    canvas.querySelectorAll<HTMLButtonElement>('[data-gate]').forEach(node => {
      const i = gates.findIndex(g => g.id === node.dataset.gate);
      node.classList.toggle('is-pending', i >= step);
      node.classList.toggle('is-current', i === step - 1);
      node.classList.toggle('is-selected', node.dataset.gate === selected);
      node.setAttribute('aria-pressed', String(node.dataset.gate === selected));
      const gate = gates[i];
      node.title = `${title(gate)} · ${gate.angle === undefined ? '点击查看' : `${gate.angle.toFixed(4)} rad`}`;
    });
    const readout = canvas.querySelector('.qc-readout');
    if (readout) readout.textContent = `${basis} 基`;
  }

  function updateInspector() {
    const i = gates.findIndex(g => g.id === selected), gate = gates[i];
    const hasAngle = gate?.angle !== undefined;
    el('[data-angle-editor]').hidden = !hasAngle;
    el('[data-angle-error]').textContent = '';
    number.removeAttribute('aria-invalid');
    el('[data-selection-title]').textContent = gate ? title(gate) : '选择一个门';
    el('[data-selection-stage]').textContent = gate ? `${gate.stage} · ${gate.qubits.map(q => `q${q}`).join(', ')}` : '';
    const descriptions: Record<GateType, string> = {
      H: 'Hadamard 门，在计算基与叠加态之间变换。', X: 'Pauli-X 门，交换 |0⟩ 与 |1⟩。',
      Ry: '绕 Y 轴旋转；调节角度，观察各测量结果的概率。', Rx: '绕 X 轴旋转，改变振幅和相对相位。', Rz: '绕 Z 轴旋转，改变相对相位。',
      CZ: '当两个比特均为 1 时，振幅变号；这一步会影响后续干涉。', CX: '控制比特为 1 时翻转目标比特，图中 ⊕ 为目标。',
      Pauli: `Pauli 旋转 exp(−iθP/2)，${gate?.word ?? ''} 的字符从左到右对应 q0、q1、q2。`,
    };
    el('[data-description]').textContent = gate ? descriptions[gate.type] : '从门库选择一个门，点击「＋」或追加到末尾开始搭建。';
    if (hasAngle) {
      number.value = gate.angle!.toFixed(4); angleSlider.value = String(gate.angle);
      el('[data-angle-pi]').textContent = `${(gate.angle! / Math.PI).toFixed(3)}π`;
    }
    button('earlier').disabled = i <= 0; button('later').disabled = i < 0 || i >= gates.length - 1;
    button('delete').disabled = !gate;
  }

  function renderCanvas() {
    canvas.replaceChildren();
    const columns: { indices: number[]; occupied: number[]; stage: string; type: GateType }[] = [];
    gates.forEach((g, i) => {
      const last = columns.at(-1);
      // Compact only consecutive, disjoint single-qubit operations of the same kind.
      if (last && g.type !== 'Pauli' && g.qubits.length === 1 && last.stage === g.stage && last.type === g.type && !last.occupied.includes(g.qubits[0]) && last.indices.every(j => gates[j].qubits.length === 1)) {
        last.indices.push(i); last.occupied.push(g.qubits[0]);
      } else columns.push({ indices: [i], occupied: [...g.qubits], stage: g.stage, type: g.type });
    });
    const width = Math.max(720, 174 + columns.length * 78);
    canvas.style.width = `${width}px`;
    const spacing = (width - 174) / Math.max(columns.length, 1);
    [0, 1, 2].forEach(q => {
      const y = 88 + q * 70, wire = make('div', 'qc-wire'), label = make('span', 'qc-wire-label', `q${q} |0⟩`);
      wire.style.top = label.style.top = `${y}px`; canvas.append(wire, label);
    });
    const insert = (index: number, left: number) => {
      const node = make('button', 'qc-insert', '+'); node.type = 'button'; node.dataset.insert = String(index);
      node.style.left = `${left}px`; node.setAttribute('aria-label', index === 0 ? '在电路起点插入门' : `在第 ${index} 个门后插入`);
      node.title = pending ? `插入 ${pending}` : '先从门库选择要插入的门';
      node.classList.toggle('is-ready', !!pending); canvas.append(node);
    };
    insert(0, 50);
    columns.forEach((col, ci) => {
      const x = 84 + ci * spacing;
      if (ci === 0 || columns[ci - 1].stage !== col.stage) {
        let last = ci; while (columns[last + 1]?.stage === col.stage) last++;
        const label = make('span', 'qc-column-label', col.stage);
        label.style.left = `${x - 5}px`; label.style.width = `${(last - ci) * spacing + 66}px`; canvas.append(label);
      }
      col.indices.forEach(i => {
        const g = gates[i], node = make('button', 'qc-gate'); node.type = 'button'; node.dataset.gate = g.id;
        node.style.left = `${x}px`;
        const low = Math.min(...g.qubits), high = Math.max(...g.qubits);
        node.style.top = `${66 + low * 70}px`; node.style.height = `${44 + (high - low) * 70}px`;
        node.setAttribute('aria-label', `第 ${i + 1} 门 ${title(g)}，${g.qubits.map(q => `q${q}`).join('、')}`);
        node.title = `${title(g)} · ${g.angle === undefined ? '点击查看' : `${g.angle.toFixed(4)} rad`}`;
        if (g.type === 'CZ' || g.type === 'CX') {
          node.classList.add('qc-entangler');
          node.append(make('span', 'qc-dot'), make('b', '', g.type), make('span', `qc-dot${g.type === 'CX' ? ' qc-target-dot' : ''}`, g.type === 'CX' ? '⊕' : ''));
        } else {
          node.append(make('span', '', g.type === 'Pauli' ? g.word : g.type));
          if (g.label) node.append(make('small', '', g.label));
        }
        canvas.append(node);
      });
      insert(col.indices.at(-1)! + 1, x + spacing - 29);
    });
    const readout = make('div', 'qc-readout', `${basis} 基`); readout.style.left = `${width - 76}px`; canvas.append(readout);
    el('[data-gate-count]').textContent = `3 比特 · ${gates.length} 个门`;
    el('[data-model-name]').textContent = modified ? '自定义演示' : 'F2/A2 演示';
    button('play').disabled = button('step').disabled = gates.length === 0;
    button('append').disabled = !pending || gates.length >= MAX_GATES;
    updateInspector(); updateState();
  }

  function chooseType(type: GateType) {
    pending = type;
    root.querySelectorAll<HTMLElement>('[data-add]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.add === type)));
    el('[data-hint]').textContent = `已选择 ${type}：拖到电路上，或点击「＋」选择插入位置。`;
    button('append').disabled = gates.length >= MAX_GATES;
    canvas.querySelectorAll('.qc-insert').forEach(n => n.classList.add('is-ready'));
  }

  function addGate(index: number, qubit?: number) {
    if (!pending) { el('[data-hint]').textContent = '请先从门库选择一个门，再选择插入位置。'; return; }
    if (gates.length >= MAX_GATES) { announce(`演示最多容纳 ${MAX_GATES} 个门，请先删除一些门。`); el('[data-hint]').textContent = `最多 ${MAX_GATES} 个门。可删除、撤销或恢复 F2/A2。`; return; }
    pause(); save();
    const q = qubit ?? Number(el<HTMLSelectElement>('[data-add-qubit]').value);
    const gate: Gate = { id: `custom-${counter++}`, type: pending, qubits: pending === 'CZ' || pending === 'CX' ? [q === 2 ? 1 : q, q === 2 ? 2 : q + 1] : [q], stage: '自由编辑' };
    if (['Ry', 'Rx', 'Rz'].includes(pending)) gate.angle = Math.PI / 2;
    gates.splice(index, 0, gate); selected = gate.id; modified = true; step = gates.length;
    renderCanvas(); announce(`已添加 ${gate.type} 门。`);
  }

  const editAngle = (value: number, record: boolean) => {
    const gate = gates.find(g => g.id === selected);
    if (!gate || gate.angle === undefined) return false;
    if (!Number.isFinite(value) || Math.abs(value) > 2 * Math.PI) {
      el('[data-angle-error]').textContent = '请输入 −2π 至 2π 之间的角度。'; number.setAttribute('aria-invalid', 'true'); return false;
    }
    pause(); if (record) save(); gate.angle = value; modified = true; step = gates.length;
    el('[data-angle-error]').textContent = ''; number.removeAttribute('aria-invalid');
    angleSlider.value = String(value); el('[data-angle-pi]').textContent = `${(value / Math.PI).toFixed(3)}π`;
    el('[data-model-name]').textContent = '自定义演示'; updateState(); return true;
  };
  let numberEditing = false;
  number.addEventListener('input', () => {
    if (editAngle(number.value.trim() === '' ? NaN : Number(number.value), !numberEditing)) numberEditing = true;
  });
  number.addEventListener('blur', () => { numberEditing = false; });
  let sliding = false;
  angleSlider.addEventListener('input', () => { editAngle(Number(angleSlider.value), !sliding); sliding = true; number.value = Number(angleSlider.value).toFixed(4); });
  angleSlider.addEventListener('change', () => { sliding = false; });
  progress.addEventListener('input', () => { pause(); step = Number(progress.value); updateState(); });
  let suppressClick = false;
  root.addEventListener('click', event => {
    if (suppressClick) return;
    const target = (event.target as Element).closest<HTMLButtonElement>('button'); if (!target || target.disabled) return;
    if (target.dataset.add) { chooseType(target.dataset.add as GateType); return; }
    if (target.dataset.gate) { pause(); selected = target.dataset.gate; updateInspector(); updateState(); return; }
    if (target.dataset.insert !== undefined) { addGate(Number(target.dataset.insert)); return; }
    if (target.dataset.angle !== undefined) { const value = Number(target.dataset.angle); editAngle(value, true); number.value = value.toFixed(4); return; }
    if (target.dataset.basis) {
      basis = target.dataset.basis as Basis;
      root.querySelectorAll<HTMLElement>('[data-basis]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.basis === basis)));
      updateState(); return;
    }
    const action = target.dataset.action;
    if (action === 'play') {
      if (timer) { pause(); announce('已暂停。'); return; }
      if (step === gates.length) step = 0;
      button('play').textContent = 'Ⅱ 暂停'; button('play').setAttribute('aria-pressed', 'true'); updateState();
      timer = setInterval(() => { step++; updateState(); if (step >= gates.length) { pause(); announce('电路演化完成。'); } }, 850);
      return;
    }
    if (action === 'step') { pause(); step = step === gates.length ? 1 : step + 1; updateState(); return; }
    if (action === 'start') { pause(); step = 0; updateState(); announce('已回到初态 |000⟩，保留当前电路。'); return; }
    if (action === 'append') { addGate(gates.length); return; }
    if (action === 'restore') {
      pause(); save(); gates = defaultCircuit(); selected = gates[0].id; step = gates.length; modified = false;
      pending = null; root.querySelectorAll('[data-add]').forEach(b => b.setAttribute('aria-pressed', 'false'));
      el('[data-hint]').textContent = '已恢复 F2/A2 拓扑和演示角度。'; renderCanvas(); announce('已恢复 F2/A2。'); return;
    }
    if (action === 'undo') {
      const previous = history.pop(); if (!previous) return;
      pause(); gates = previous.gates; selected = previous.selected; modified = previous.modified; step = gates.length;
      renderCanvas(); button('undo').disabled = !history.length; announce('已撤销上一次编辑。'); return;
    }
    const i = gates.findIndex(g => g.id === selected);
    if (i < 0 || !['earlier', 'later', 'delete'].includes(action ?? '')) return;
    pause(); save(); modified = true;
    if (action === 'delete') { gates.splice(i, 1); selected = gates[Math.min(i, gates.length - 1)]?.id ?? ''; }
    else { const j = action === 'earlier' ? i - 1 : i + 1; [gates[i], gates[j]] = [gates[j], gates[i]]; }
    step = gates.length; renderCanvas(); announce(action === 'delete' ? '已删除选中门，可撤销。' : '已调整门的顺序。');
  });
  // Pointer capture supports the same drag gesture on mouse, pen and touch.
  let drag: { source: HTMLElement; type: GateType; x: number; y: number; active: boolean; ghost?: HTMLElement } | null = null;
  const clearDrag = () => {
    drag?.ghost?.remove(); drag = null;
    canvas.querySelectorAll('.qc-dragover').forEach(n => n.classList.remove('qc-dragover'));
  };
  root.addEventListener('pointerdown', event => {
    const source = (event.target as Element).closest<HTMLElement>('[data-add]');
    if (!source?.dataset.add || event.button !== 0) return;
    drag = { source, type: source.dataset.add as GateType, x: event.clientX, y: event.clientY, active: false };
    source.setPointerCapture(event.pointerId);
  });
  root.addEventListener('pointermove', event => {
    if (!drag) return;
    if (!drag.active && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) > 8) {
      drag.active = true; chooseType(drag.type);
      drag.ghost = make('div', 'qc-drag-preview', drag.type); root.append(drag.ghost);
    }
    if (!drag.active) return;
    event.preventDefault();
    drag.ghost!.style.left = `${event.clientX + 14}px`; drag.ghost!.style.top = `${event.clientY + 14}px`;
    canvas.querySelectorAll('.qc-dragover').forEach(n => n.classList.remove('qc-dragover'));
    const target = document.elementFromPoint(event.clientX, event.clientY);
    if (target && canvas.contains(target)) target.closest('[data-insert], [data-gate]')?.classList.add('qc-dragover');
  });
  root.addEventListener('pointerup', event => {
    if (!drag) return;
    const active = drag.active, type = drag.type;
    const hit = document.elementFromPoint(event.clientX, event.clientY);
    if (active) {
      suppressClick = true; window.setTimeout(() => { suppressClick = false; }, 0);
      if (hit && canvas.contains(hit)) {
        pending = type;
        const target = hit.closest<HTMLElement>('[data-insert], [data-gate]');
        const index = target?.dataset.insert !== undefined ? Number(target.dataset.insert) : target?.dataset.gate ? gates.findIndex(g => g.id === target.dataset.gate) + 1 : gates.length;
        const y = event.clientY - canvas.getBoundingClientRect().top;
        const q = y < 250 ? Math.max(0, Math.min(2, Math.round((y - 88) / 70))) : undefined;
        addGate(index, q);
      }
    }
    clearDrag();
  });
  root.addEventListener('pointercancel', clearDrag);
  document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); });
  window.addEventListener('pagehide', pause);
  mountNativeCircuit(root, () => clone(gates));
  root.addEventListener('workbench-hidden', pause);
  renderCanvas();
}
