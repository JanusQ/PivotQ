import { chartRange, loadFrames, metrics, type MetricKey } from './aimd-data';

const namespace = 'http://www.w3.org/2000/svg';
const svgNode = (tag: string, attrs: Record<string, string | number>, text?: string) => {
  const node = document.createElementNS(namespace, tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
  if (text !== undefined) node.textContent = text; return node;
};
const format = (value: number, digits = 3) => value.toFixed(digits);
export async function mountAimdWorkbench(root: HTMLElement) {
  const el = <T extends HTMLElement = HTMLElement>(selector: string) => root.querySelector<T>(selector)!;
  const status = el('[data-load-status]');
  try {
    const responses = await Promise.all([fetch(root.dataset.logUrl!), fetch(root.dataset.positionUrl!)]);
    if (responses.some(response => !response.ok)) throw new Error('轨迹文件读取失败');
    const texts = await Promise.all(responses.map(response => response.text()));
    const frames = loadFrames(texts[0], texts[1]);
    root.dataset.loaded = 'true'; status.textContent = ''; status.hidden = true;
    let current = 0, revealed = 0, playing = false, visible = false, inspecting = false, windowSize = 0, previousTime = 0, animation = 0;
    let playbackRequested = false;
    const speed = 30;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const { moleculeView } = await import('./molecule-view');
    const molecule = moleculeView(el<HTMLCanvasElement>('[data-molecule]'), frames);
    const charts = Array.from(root.querySelectorAll<HTMLElement>('[data-chart]')).map(card => ({ card, svg: card.querySelector<SVGSVGElement>('[data-plot]')!, keys: card.dataset.keys!.split(',') as MetricKey[], disabled: new Set<MetricKey>(), domain: [0, frames.length - 1] as [number, number] }));
    const nearestFrame = (time: number) => {
      let low = 0, high = frames.length - 1;
      while (low < high) { const mid = Math.floor((low + high) / 2); if (frames[mid].time < time) low = mid + 1; else high = mid; }
      return low > 0 && time - frames[low - 1].time < frames[low].time - time ? low - 1 : low;
    };
    function drawChart(chart: typeof charts[number]) {
      const { svg, keys, disabled, card } = chart;
      const time = frames[current].time, first = windowSize ? nearestFrame(Math.max(frames[0].time, time - windowSize)) : 0, last = windowSize ? nearestFrame(Math.min(frames.at(-1)!.time, time + windowSize)) : frames.length - 1;
      chart.domain = [first, last];
      const visible = keys.filter(key => !disabled.has(key));
      // Keep the axes stable while revealing only the elapsed portion of the trajectory.
      const samples = frames.slice(first, Math.min(last, revealed) + 1);
      const [yMin, yMax] = chartRange(frames.slice(first, last + 1).flatMap(frame => visible.map(key => frame.values[key])));
      const tMin = frames[first].time, tMax = frames[last].time;
      // Match SVG units to the rendered width so 13px tick labels remain legible
      // on narrow cards. Reserve space for signed y values and the final x tick;
      // selectFrame uses these same margins to map pointer positions to time.
      const width = Math.max(200, Math.round(svg.clientWidth || 480));
      const plotLeft = 64, plotRight = width - 28;
      svg.setAttribute('viewBox', `0 0 ${width} 230`);
      const x = (t: number) => plotLeft + (t - tMin) / (tMax - tMin || 1) * (plotRight - plotLeft);
      const y = (v: number) => 184 - (v - yMin) / (yMax - yMin) * 157;
      const children: Element[] = [];
      for (let i = 0; i <= 4; i++) {
        const value = yMin + (yMax - yMin) * i / 4, yy = y(value);
        children.push(svgNode('line', { x1: plotLeft, x2: plotRight, y1: yy, y2: yy, stroke: '#e5edf5', 'stroke-dasharray': '3 4' }));
        children.push(svgNode('text', { x: plotLeft - 9, y: yy + 4, 'text-anchor': 'end', fill: '#7c8fa4', 'font-size': 13 }, Math.abs(value) >= 100 ? value.toFixed(0) : value.toFixed(3)));
      }
      // Keep labels at the same readable size; show fewer time ticks when the
      // plot is too narrow to separate five labels such as "75.0" and "100.0".
      const timeTickCount = plotRight - plotLeft < 220 ? 2 : 4;
      for (let i = 0; i <= timeTickCount; i++) { const t = tMin + (tMax - tMin) * i / timeTickCount; children.push(svgNode('text', { x: x(t), y: 206, 'text-anchor': 'middle', fill: '#7c8fa4', 'font-size': 13 }, t.toFixed(1))); }
      children.push(svgNode('text', { x: width - 14, y: 224, 'text-anchor': 'end', fill: '#7c8fa4', 'font-size': 13 }, '时间 / fs'));
      for (const key of visible) {
        const d = samples.map((frame, i) => `${i ? 'L' : 'M'}${x(frame.time).toFixed(2)},${y(frame.values[key]).toFixed(2)}`).join(' ');
        children.push(svgNode('path', { d, fill: 'none', stroke: metrics[key].color, 'stroke-width': 1.6, 'stroke-linejoin': 'round', 'data-metric': key, 'data-sample-count': samples.length }));
      }
      children.push(svgNode('line', { x1: x(time), x2: x(time), y1: 24, y2: 184, stroke: '#355a87', 'stroke-dasharray': '4 4', 'data-time-cursor': frames[current].step }));
      for (const key of visible) children.push(svgNode('circle', { cx: x(time), cy: y(frames[current].values[key]), r: 3.5, fill: metrics[key].color, stroke: '#fff', 'stroke-width': 1.5 }));
      svg.replaceChildren(...children);
      const output = card.querySelector<HTMLElement>('[data-chart-readout]')!; output.replaceChildren();
      for (const key of visible) { const span = document.createElement('span'); span.textContent = `${metrics[key].label} ${format(frames[current].values[key], key === 'temperature_K' ? 1 : 3)} ${metrics[key].unit}`; span.style.color = metrics[key].color; output.append(span); }
    }
    function update(index: number) {
      current = Math.max(0, Math.min(frames.length - 1, Math.round(index))); const frame = frames[current];
      revealed = Math.max(revealed, current); root.dataset.revealedFrame = String(frames[revealed].step);
      root.dataset.frame = String(frame.step);
      root.querySelectorAll<HTMLElement>('[data-value]').forEach(node => { const key = node.dataset.value as MetricKey; node.textContent = format(frame.values[key], key === 'hoh_angle_deg' ? 2 : 4); });
      molecule.setFrame(current); charts.forEach(drawChart);
    }
    function pause() { playing = false; cancelAnimationFrame(animation); previousTime = 0; }
    function start() {
      if (playing || !visible || inspecting || current === frames.length - 1 || document.hidden || (reducedMotion.matches && !playbackRequested)) return;
      playing = true; previousTime = 0; animation = requestAnimationFrame(tick);
    }
    function tick(timestamp: number) {
      if (!playing) return;
      if (!previousTime) previousTime = timestamp;
      const increments = Math.floor((timestamp - previousTime) * speed / 1000);
      if (increments > 0) {
        previousTime += increments * 1000 / speed; update(current + increments);
        if (current === frames.length - 1) { pause(); return; }
      }
      animation = requestAnimationFrame(tick);
    }
    el<HTMLSelectElement>('[data-chart-window]').addEventListener('change', event => { windowSize = Number((event.target as HTMLSelectElement).value); charts.forEach(drawChart); });
    el('[data-camera-reset]').addEventListener('click', molecule.reset);
    el<HTMLInputElement>('[data-trails]').addEventListener('change', event => molecule.setTrails((event.target as HTMLInputElement).checked));
    charts.forEach(chart => {
      chart.card.querySelectorAll<HTMLButtonElement>('[data-series]').forEach(button => {
        const key = button.dataset.series as MetricKey; button.style.setProperty('--series-color', metrics[key].color);
        button.addEventListener('click', () => { if (chart.disabled.has(key)) chart.disabled.delete(key); else if (chart.disabled.size < chart.keys.length - 1) chart.disabled.add(key); button.setAttribute('aria-pressed', String(!chart.disabled.has(key))); drawChart(chart); });
      });
      const selectFrame = (event: PointerEvent) => {
        // Invert the displayed plot scale, including its 64px/28px margins,
        // before choosing the nearest saved frame in the current time window.
        const rect = chart.svg.getBoundingClientRect(), width = chart.svg.viewBox.baseVal.width;
        const fraction = Math.max(0, Math.min(1, ((event.clientX - rect.left) / rect.width * width - 64) / (width - 92)));
        const [first, last] = chart.domain; inspecting = true; pause(); update(nearestFrame(frames[first].time + fraction * (frames[last].time - frames[first].time)));
      };
      let dragging = false;
      chart.svg.addEventListener('pointerdown', event => { dragging = true; chart.svg.setPointerCapture(event.pointerId); selectFrame(event); });
      chart.svg.addEventListener('pointermove', event => { if (dragging) selectFrame(event); });
      chart.svg.addEventListener('pointerup', () => { dragging = false; }); chart.svg.addEventListener('pointercancel', () => { dragging = false; });
      chart.svg.addEventListener('keydown', event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); inspecting = true; pause(); update(event.key === 'Home' ? 0 : event.key === 'End' ? frames.length - 1 : current + (event.key === 'ArrowLeft' ? -1 : 1)); } });
    });
    // Reflow paused charts as well as playing ones. Ignore height-only changes
    // caused by the new viewBox to avoid an observer/redraw feedback loop.
    const chartResizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        const chart = charts.find(({ svg }) => svg === entry.target);
        if (chart && Math.abs(chart.svg.viewBox.baseVal.width - Math.max(200, Math.round(chart.svg.clientWidth))) > 0.5) drawChart(chart);
      }
    });
    charts.forEach(({ svg }) => chartResizeObserver.observe(svg));
    window.addEventListener('pagehide', event => { if (!event.persisted) chartResizeObserver.disconnect(); }, { once: true });
    const observer = new IntersectionObserver(entries => {
      visible = entries[0].isIntersecting;
      if (visible) start(); else { pause(); inspecting = false; }
    }); observer.observe(root);
    document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); else start(); });
    reducedMotion.addEventListener('change', () => { playbackRequested = false; if (reducedMotion.matches) pause(); else start(); });
    window.addEventListener('pagehide', pause); root.addEventListener('workbench-hidden', pause);
    update(0);
    return {
      restart() {
        pause(); inspecting = false; revealed = 0;
        // A direct playback request also works when automatic motion is disabled.
        playbackRequested = true;
        update(0); start();
      },
    };
  } catch (error) { status.hidden = false; status.textContent = `无法加载数据：${error instanceof Error ? error.message : '请刷新重试'}`; status.setAttribute('role', 'alert'); }
}
