import type { TargetSnapshot } from "../api/types";
import s from "../App.module.css";

/** Renders server-supplied parameters, including historical snapshots. */
export default function TargetDetails({
  snapshot,
}: {
  snapshot: TargetSnapshot;
}) {
  const params = snapshot.parameters,
    topology = params.topology;
  if (!topology)
    return (
      <div className={s.targetDetails}>
        <div className={s.targetMetadata}>
          <span>
            {params.calibrated === false ? "参考假设值" : "参考硬件参数"}
          </span>
          <span>参数只读 · {snapshot.profile_version}</span>
        </div>
        {typeof params.peak_flops_tflops_per_node === "number" && (
          <dl className={s.chipParameters}>
            <div>
              <dt>每节点峰值计算能力</dt>
              <dd>{params.peak_flops_tflops_per_node} TFLOPS</dd>
            </div>
            <div>
              <dt>每节点内存带宽</dt>
              <dd>{String(params.memory_bandwidth_gbps_per_node)} GB/s</dd>
            </div>
          </dl>
        )}
        {typeof params.source === "string" && <p>{params.source}</p>}
      </div>
    );
  const spacing = 42,
    margin = 22,
    x = (qubit: number) => margin + (qubit % topology.columns) * spacing,
    y = (qubit: number) =>
      margin + Math.floor(qubit / topology.columns) * spacing;
  return (
    <div className={s.targetDetails}>
      <div className={s.targetMetadata}>
        <span>虚拟芯片模型 · 未经实机标定</span>
        <span>参数只读 · {snapshot.profile_version}</span>
      </div>
      <svg
        className={s.chipTopology}
        viewBox={`0 0 ${margin * 2 + (topology.columns - 1) * spacing} ${margin * 2 + (topology.rows - 1) * spacing}`}
        role="img"
        aria-label={`${snapshot.title} 拓扑：${topology.nodes.length} 个比特，${topology.edges.length} 条无向边`}
      >
        {topology.edges.map(([a, b]) => (
          <line key={`${a}-${b}`} x1={x(a)} y1={y(a)} x2={x(b)} y2={y(b)} />
        ))}
        {topology.nodes.map((qubit) => (
          <g key={qubit}>
            <circle cx={x(qubit)} cy={y(qubit)} r="13" />
            <text x={x(qubit)} y={y(qubit)} dy="0.35em">
              {qubit}
            </text>
          </g>
        ))}
      </svg>
      <dl className={s.chipParameters}>
        <div>
          <dt>目标芯片模型容量</dt>
          <dd>{params.qubits} 比特</dd>
        </div>
        <div>
          <dt>有效采样吞吐</dt>
          <dd>{params.shot_rate?.toLocaleString("en-US")} shots/s</dd>
        </div>
        <div>
          <dt>每批提交时延</dt>
          <dd>{Number(params.submit_latency_us) / 1000} ms</dd>
        </div>
        {snapshot.logical_qubits !== undefined && (
          <div>
            <dt>电路使用的逻辑量子比特</dt>
            <dd>{snapshot.logical_qubits}</dd>
          </div>
        )}
      </dl>
      <p>
        这是模型容量，不表示使用了相同比特数的真机。按行编号，连接上下左右最近邻。拓扑仅展示；预测采用吞吐模型，不计布线、门深度与噪声。
      </p>
      <p>
        CPU 数值模拟仅使用实际电路宽度：自编电路 1–
        {snapshot.numerical_limits?.max_logical_qubits ?? 12} 比特，单水{" "}
        {snapshot.numerical_limits?.h2o_logical_qubits ?? 3} 比特。
      </p>
    </div>
  );
}
