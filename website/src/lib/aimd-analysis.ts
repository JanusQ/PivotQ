import { modelCircuit, physicalCircuit, circuitLayers, type CircuitOperation } from './aimd-circuit';
import { mountAimdWorkbench } from './aimd-workbench';

const NS = 'http://www.w3.org/2000/svg';
function svgElement(tag: string, attrs: Record<string, string | number> = {}, text?: string) {
  const node = document.createElementNS(NS, tag);
  Object.entries(attrs).forEach(([name, value]) => node.setAttribute(name, String(value)));
  if (text !== undefined) node.textContent = text;
  return node;
}

function circuitView(card: HTMLElement, highlightSource: (source: number) => void) {
  const viewport = card.querySelector<HTMLElement>('[data-circuit-viewport]')!;
  const svg = card.querySelector<SVGSVGElement>('[data-circuit-svg]')!;
  const clock = card.querySelector<HTMLButtonElement>('[data-clock]')!;
  const physical = card.dataset.circuitCard === 'physical';
  const name = physical ? '物理' : '逻辑';
  let operations: CircuitOperation[] = [], layers: number[] = [], depth = 0, zoom = 1, selected = -1, cursorLayer = 0, clockVisible = false;
  let link: (source: number) => void = () => {};
  const x = (layer: number) => 94 + (layer - 1) * 62;
  const y = (qubit: number) => 70 + qubit * 64;
  const wireTop = y(0), wireBottom = y(2);
  const label = (operation: CircuitOperation) => operation.gate.word ?? operation.gate.type;

  function describe(index: number) {
    const operation = operations[index];
    return `${label(operation)}${operation.expression ? `(${operation.expression})` : ''}`;
  }
  function select(index: number, synchronize = true) {
    if (!operations[index]) return;
    selected = index; cursorLayer = layers[index];
    svg.querySelectorAll<SVGElement>('[data-gate-index]').forEach(node => { const active = Number(node.dataset.gateIndex) === index; node.classList.toggle('selected', active); node.setAttribute('aria-pressed', String(active)); });
    positionCursor(); highlightSource(operations[index].source);
    if (synchronize) link(operations[index].origin);
  }
  function positionCursor() {
    const group = svg.querySelector('[data-cursor]');
    group?.setAttribute('transform', `translate(${x(cursorLayer || 1) - 29},0)`);
    svg.dataset.selectedLayer = String(cursorLayer);
    svg.querySelector('[data-cursor-handle]')?.setAttribute('aria-valuenow', String(cursorLayer || 1));
    svg.querySelectorAll<SVGElement>('[data-layer]').forEach(node => node.classList.toggle('active-layer', Number(node.dataset.layer) === cursorLayer));
  }
  function selectLayer(layer: number) {
    cursorLayer = Math.max(1, Math.min(depth, layer));
    const index = layers.findIndex(value => value === cursorLayer);
    if (index !== -1) select(index);
  }
  function render() {
    const width = Math.max(620, x(depth) + 72);
    svg.setAttribute('viewBox', `0 0 ${width} 272`);
    svg.style.width = `${width * zoom}px`; svg.style.height = `${272 * zoom}px`;
    const content: Element[] = [];
    for (let q = 0; q < 3; q++) {
      content.push(svgElement('line', { x1: 62, x2: width - 25, y1: y(q), y2: y(q), class: 'analysis-wire' }));
      content.push(svgElement('text', { x: 43, y: y(q) + 4, 'text-anchor': 'end', class: 'analysis-wire-label' }, `q[${q}]`));
    }
    for (let layer = 1; layer <= depth; layer++) {
      const group = svgElement('g', { class: `analysis-layer${clockVisible ? ' visible' : ''}`, 'data-layer': layer });
      group.append(svgElement('line', { x1: x(layer) - 29, x2: x(layer) - 29, y1: 43, y2: 223 }));
      group.append(svgElement('text', { x: x(layer) - 24, y: 246 }, String(layer)));
      content.push(group);
    }
    // A separate hover line follows the pointer without changing the selected gate.
    content.push(svgElement('line', { 'data-hover-cursor': '', class: 'analysis-hover-cursor', x1: 0, x2: 0, y1: wireTop, y2: wireBottom, visibility: 'hidden', 'aria-hidden': 'true' }));
    operations.forEach((operation, index) => {
      const { gate } = operation, xx = x(layers[index]), top = y(Math.min(...gate.qubits)), bottom = y(Math.max(...gate.qubits));
      const group = svgElement('g', { class: 'analysis-gate', 'data-gate-index': index, tabindex: 0, role: 'button', 'aria-label': `${name}门 ${index + 1} ${describe(index)}`, 'aria-pressed': 'false' });
      group.append(svgElement('title', {}, describe(index)));
      if (gate.type === 'CZ') {
        group.append(svgElement('rect', { x: xx - 18, y: top - 18, width: 36, height: bottom - top + 36, rx: 18, class: 'analysis-hit' }));
        group.append(svgElement('line', { x1: xx, x2: xx, y1: top, y2: bottom, class: 'analysis-link' }));
        gate.qubits.forEach(q => group.append(svgElement('circle', { cx: xx, cy: y(q), r: 5, class: 'analysis-control' })));
        group.append(svgElement('text', { x: xx + 10, y: (top + bottom) / 2 + 4, class: 'analysis-cz-label' }, 'CZ'));
      } else if (gate.type === 'Pauli') {
        group.append(svgElement('rect', { x: xx - 24, y: top - 21, width: 48, height: bottom - top + 42, rx: 14, class: 'analysis-gate-shape' }));
        group.append(svgElement('text', { x: xx, y: (top + bottom) / 2 + 4, 'text-anchor': 'middle', class: 'analysis-gate-text' }, gate.word!));
      } else {
        group.append(svgElement('circle', { cx: xx, cy: top, r: 20, class: 'analysis-gate-shape' }));
        group.append(svgElement('text', { x: xx, y: top + 4, 'text-anchor': 'middle', class: 'analysis-gate-text' }, gate.type));
      }
      group.addEventListener('click', () => select(index));
      group.addEventListener('keydown', event => { const key = (event as KeyboardEvent).key; if (key === 'Enter' || key === ' ') { event.preventDefault(); select(index); } });
      content.push(group);
    });
    const cursor = svgElement('g', { 'data-cursor': '', class: 'analysis-time-cursor', transform: `translate(${x(1)-29},0)` });
    cursor.append(svgElement('line', { x1: 0, x2: 0, y1: wireTop, y2: wireBottom }));
    cursor.append(svgElement('path', { d: `M-5 ${wireTop-7}h10l-5 7z M-5 ${wireBottom+7}h10l-5-7z` }));
    const handle = svgElement('rect', { x: -10, y: wireTop-12, width: 20, height: wireBottom-wireTop+24, fill: 'transparent', 'data-cursor-handle': '', tabindex: 0, role: 'slider', 'aria-label': `${name}电路时间定位线`, 'aria-valuemin': 1, 'aria-valuemax': depth, 'aria-valuenow': cursorLayer || 1 });
    handle.addEventListener('keydown', event => {
      const key = (event as KeyboardEvent).key;
      if (['ArrowLeft','ArrowRight','Home','End'].includes(key)) { event.preventDefault(); selectLayer(key==='Home'?1:key==='End'?depth:cursorLayer+(key==='ArrowLeft'?-1:1)); handle.setAttribute('aria-valuenow', String(cursorLayer)); }
    });
    cursor.append(handle); content.push(cursor); svg.replaceChildren(...content);
    if (selected >= 0) select(selected, false); else positionCursor();
  }
  clock.addEventListener('click', () => { clockVisible = !clockVisible; clock.setAttribute('aria-pressed', String(clockVisible)); svg.querySelectorAll('.analysis-layer').forEach(node => node.classList.toggle('visible', clockVisible)); });
  const changeZoom = (value: number) => { zoom = Math.max(.65, Math.min(1.6, value)); render(); };
  card.querySelector('[data-zoom-in]')!.addEventListener('click', () => changeZoom(zoom + .15));
  card.querySelector('[data-zoom-out]')!.addEventListener('click', () => changeZoom(zoom - .15));
  card.querySelector('[data-fit]')!.addEventListener('click', () => { zoom=1; viewport.scrollLeft=0; viewport.scrollTop=0; render(); });
  let drag: { clientX: number; scroll: number; cursor: boolean; moved: boolean } | null = null;
  const svgPoint = (clientX: number, clientY: number) => {
    const matrix=svg.getScreenCTM();
    return matrix ? new DOMPoint(clientX,clientY).matrixTransform(matrix.inverse()) : null;
  };
  const pointLayer = (clientX: number) => { const point=svgPoint(clientX,svg.getBoundingClientRect().top); return point ? Math.round((point.x-94)/62)+1 : 1; };
  const hideHover = () => svg.querySelector('[data-hover-cursor]')?.setAttribute('visibility','hidden');
  const showHover = (event: PointerEvent) => {
    const line=svg.querySelector('[data-hover-cursor]'), point=svgPoint(event.clientX,event.clientY);
    if(!line || !point || event.pointerType==='touch' || point.x<62 || point.x>svg.viewBox.baseVal.width-25 || point.y<wireTop || point.y>wireBottom) { hideHover(); return; }
    line.setAttribute('x1',String(point.x)); line.setAttribute('x2',String(point.x)); line.setAttribute('visibility','visible');
  };
  viewport.addEventListener('pointerdown', event => {
    if (event.button!==0) return;
    const target=event.target as Element;
    if (target.closest('.analysis-gate')) return;
    drag={clientX:event.clientX,scroll:viewport.scrollLeft,cursor:!!target.closest('[data-cursor-handle]'),moved:false};
    viewport.setPointerCapture(event.pointerId);
  });
  viewport.addEventListener('pointermove', event => {
    if (!drag) { showHover(event); return; }
    hideHover();
    if (Math.abs(event.clientX-drag.clientX)>3) drag.moved=true;
    if (drag.cursor) selectLayer(pointLayer(event.clientX)); else viewport.scrollLeft=drag.scroll-(event.clientX-drag.clientX);
  });
  viewport.addEventListener('pointerup', event => {
    if (drag && !drag.moved) selectLayer(pointLayer(event.clientX));
    drag=null;
    if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
    showHover(event);
  });
  viewport.addEventListener('pointerleave', hideHover);
  viewport.addEventListener('scroll', hideHover);
  viewport.addEventListener('pointercancel', () => { drag=null; hideHover(); });
  return {
    show(data: CircuitOperation[]) {
      operations=data; layers=circuitLayers(data); depth=Math.max(...layers); selected=-1; cursorLayer=1;
      card.querySelector<HTMLElement>('[data-empty]')!.hidden=true;
      card.querySelectorAll<HTMLElement>('[data-circuit-tools]').forEach(node=>node.hidden=false);
      viewport.hidden=false; viewport.scrollLeft=0;
      render();
    },
    origin(origin: number) { const index=operations.findIndex(operation=>operation.origin===origin); if(index!==-1) select(index,false); },
    setLink(callback: (source: number) => void) { link=callback; },
  };
}

export function mountAimdAnalysis(root: HTMLElement) {
  const lineMap=JSON.parse(root.dataset.lineMap!) as Record<string,number>;
  const code=root.querySelector<HTMLElement>('[data-source]')!;
  const lines=Array.from(code.querySelectorAll<HTMLElement>('.line'));
  let codeEditor: { highlight: (line: number) => void } | undefined;
  let highlightedSource: number | undefined;
  void import('./aimd-code-editor').then(({ mountCodeEditor }) => {
    codeEditor = mountCodeEditor(code);
    if (highlightedSource !== undefined) codeEditor.highlight(lineMap[highlightedSource]);
  }).catch(error => console.error('代码编辑器加载失败', error));
  const highlight=(source:number)=>{
    highlightedSource = source;
    if (codeEditor) { codeEditor.highlight(lineMap[source]); return; }
    lines.forEach((line,index)=>line.classList.toggle('active-code-line',index===lineMap[source]));
    const line=lines[lineMap[source]];
    if(line) { const offset=line.getBoundingClientRect().top-code.getBoundingClientRect().top+code.scrollTop; if(offset<code.scrollTop+30||offset>code.scrollTop+code.clientHeight-40) code.scrollTop=Math.max(0,offset-code.clientHeight*.4); }
  };
  const logical=circuitView(root.querySelector('[data-circuit-card="logical"]')!,highlight);
  const physical=circuitView(root.querySelector('[data-circuit-card="physical"]')!,highlight);
  logical.setLink(origin=>physical.origin(origin)); physical.setLink(origin=>logical.origin(origin));
  const circuit=modelCircuit();
  logical.show(circuit);
  physical.show(physicalCircuit(circuit));
  const results=root.querySelector<HTMLElement>('.analysis-results')!;
  const restart=results.querySelector<HTMLButtonElement>('[data-restart]')!;
  void mountAimdWorkbench(results.querySelector('[data-aimd-workbench]')!).then(workbench=>{
    if (!workbench) return;
    restart.addEventListener('click',workbench.restart);
    restart.disabled=false;
  });
}
