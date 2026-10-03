export const metrics = {
  potential_energy_eV: { label: '势能', unit: 'eV', color: '#2875d1' },
  kinetic_energy_eV: { label: '动能', unit: 'eV', color: '#21a29b' },
  total_energy_eV: { label: '总能量', unit: 'eV', color: '#8a69ce' },
  temperature_K: { label: '温度', unit: 'K', color: '#d39738' },
  oh1_length_A: { label: 'O–H₁ 键长', unit: 'Å', color: '#2875d1' },
  oh2_length_A: { label: 'O–H₂ 键长', unit: 'Å', color: '#21a29b' },
  hoh_angle_deg: { label: 'H–O–H 键角', unit: '°', color: '#8a69ce' },
} as const;
export type MetricKey = keyof typeof metrics;
export type Vec3 = [number, number, number];
export type Frame = { step: number; time: number; atoms: [Vec3, Vec3, Vec3]; values: Record<MetricKey, number> };

export function parseCSV(text: string): Record<string, string>[] {
  const lines = text.replace(/^\uFEFF/, '').trim().split(/\r?\n/);
  // These numerical trajectory files contain no quoted multiline fields.
  const split = (line: string) => {
    const cells: string[] = []; let value = '', quoted = false;
    for (let i = 0; i < line.length; i++) {
      if (line[i] === '"') { if (quoted && line[i + 1] === '"') { value += '"'; i++; } else quoted = !quoted; }
      else if (line[i] === ',' && !quoted) { cells.push(value); value = ''; } else value += line[i];
    }
    if (quoted) throw new Error('CSV 引号未闭合'); cells.push(value); return cells;
  };
  const headers = split(lines[0]);
  return lines.slice(1).filter(Boolean).map(line => {
    const cells = split(line);
    if (cells.length !== headers.length) throw new Error('CSV 列数不一致');
    return Object.fromEntries(headers.map((key, i) => [key, cells[i]]));
  });
}

const numeric = (row: Record<string, string>, key: string) => {
  if (row[key] === undefined || row[key].trim() === '' || !Number.isFinite(Number(row[key]))) throw new Error(`数据缺少有效数值：${key}`);
  return Number(row[key]);
};
export function loadFrames(logText: string, positionText: string): Frame[] {
  const log = parseCSV(logText), positions = parseCSV(positionText);
  if (!log.length || log.length !== positions.length) throw new Error('日志与坐标帧数不一致');
  const frames = log.map((row, i): Frame => {
    const position = positions[i], step = numeric(row, 'step'), time = numeric(row, 'time_fs');
    if (!Number.isInteger(step) || step < 0 || numeric(position, 'step') !== step || Math.abs(numeric(position, 'time_fs') - time) > 1e-8) throw new Error('日志与坐标时间步不匹配');
    const values = Object.fromEntries(Object.keys(metrics).map(key => [key, numeric(row, key)])) as Record<MetricKey, number>;
    if (Math.abs(values.total_energy_eV - values.potential_energy_eV - values.kinetic_energy_eV) > 1e-8) throw new Error('总能量与势能、动能之和不一致');
    const atoms = ['O', 'H1', 'H2'].map(atom => ['x', 'y', 'z'].map(axis => numeric(position, `${atom}_${axis}_A`))) as [Vec3, Vec3, Vec3];
    const a = atoms[1].map((v, j) => v - atoms[0][j]), b = atoms[2].map((v, j) => v - atoms[0][j]);
    const r1 = Math.hypot(...a), r2 = Math.hypot(...b);
    const angle = Math.acos(Math.min(1, Math.max(-1, a.reduce((sum, v, j) => sum + v * b[j], 0) / (r1 * r2)))) * 180 / Math.PI;
    if (Math.abs(r1 - values.oh1_length_A) > 1e-6 || Math.abs(r2 - values.oh2_length_A) > 1e-6 || Math.abs(angle - values.hoh_angle_deg) > 1e-5) throw new Error('坐标与键长、键角记录不一致');
    return { step, time, atoms, values };
  });
  frames.slice(1).forEach((frame, i) => {
    if (frame.step <= frames[i].step || frame.time <= frames[i].time) throw new Error('时间序列没有递增');
  });
  return frames;
}

export function chartRange(values: number[]): [number, number] {
  const min = Math.min(...values), max = Math.max(...values);
  const pad = Math.max((max - min) * .12, Math.abs(max) * .002, 1e-5);
  return [min - pad, max + pad];
}
