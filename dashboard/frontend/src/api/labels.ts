/** Presentation labels leave persisted IDs and parameter snapshots unchanged. */
export const phaseNames: Record<string, string> = {
  launcher_outer: "启动器外围开销",
  worker_exclusive: "工作进程其他开销",
  actor_setup: "初始化计算服务",
  dataset_and_ood_setup: "准备数据",
  diagnostic_input: "准备检查输入",
  prepare: "准备计算输入",
  circuits: "构造量子电路",
  qasm_export: "导出 QASM 电路",
  http_submit: "向 QPU 提交电路",
  acquisition: "QPU 运行与测量",
  decode: "解析测量结果",
  normalize_all: "归一化测量结果",
  host_features: "在主机端整理量子特征",
  classical: "经典模型预测能量",
  host_energies: "在主机端整理能量结果",
  force: "计算原子受力",
  preflight_absolute_difference: "比较预检查结果的绝对差",
  initial_state: "准备分子初始状态",
  record: "保存轨迹帧",
  bookkeeping: "更新位置并保存轨迹",
  plot_artifacts: "生成结果图表",
  actor_teardown: "释放计算服务",
  statevector: "量子模拟",
  classical_actor: "经典模型预测能量",
  force_host: "计算原子受力",
  framework_outer: "框架外围开销",
  worker_setup_teardown: "计算进程初始化与收尾",
  feature_readout: "提取量子特征",
  critical_path_QPU: "QPU 执行",
  critical_path_CPU: "CPU 执行",
  critical_path_GPU: "GPU 执行",
};

const stageNames: Record<string, string> = {
  initialization: "准备初始状态",
  quantum_features: "运行量子电路并提取特征",
  classical_predict: "用经典模型预测势能",
  force_and_integration: "计算受力，更新位置与速度",
  trajectory_analysis: "分析轨迹",
};
export const stageLabel = (id: string, fallback: string) => stageNames[id] || fallback;
export function targetLabel(target?: { id?: string; title?: string } | null, fallback = "未记录") {
  if (target?.id === "fake-sc-36") return "SC-36 虚拟超导芯片（6×6，36 比特）";
  if (target?.title === "参考 CPU") return "参考 CPU（性能模型）";
  return target?.title || fallback;
}

/** Do not round a positive contribution down to a misleading zero. */
export function forecastShare(amount: number, total: number) {
  if (!Number.isFinite(amount) || !Number.isFinite(total) || amount < 0 || total <= 0) return "占比未提供";
  const percentage = amount / total * 100;
  return percentage > 0 && percentage < 1 ? "占比 <1%" : `占预计总耗时 ${Math.round(percentage)}%`;
}
