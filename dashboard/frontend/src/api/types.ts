export type Values = Record<string, string | number>;
export interface InputSchema {
  type: string;
  title: string;
  default: string | number;
  minimum?: number;
  maximum?: number;
}
export interface Stage {
  id: string;
  title: string;
  description?: string;
  allowed_devices: string[];
  default_device: string;
  fixed_device?: boolean;
  depends_on: string[];
}
export interface Task {
  id: string;
  version: string;
  title: string;
  stages: Stage[];
  input_schema: { properties: Record<string, InputSchema> };
}
export interface Target {
  id: string;
  title: string;
  kind: string;
  available: boolean;
  status?: string;
  resources?: Record<string, unknown>;
  target_snapshot?: TargetSnapshot;
}
export interface TargetSnapshot {
  id: string;
  kind: string;
  title: string;
  profile_version: string;
  profile_sha256: string;
  virtual?: boolean;
  logical_qubits?: number;
  parameters: {
    qubits?: number;
    topology?: {
      rows: number;
      columns: number;
      nodes: number[];
      edges: [number, number][];
    };
    shot_rate?: number;
    submit_latency_us?: number;
    model?: string;
    calibrated?: boolean;
    [key: string]: unknown;
  };
  numerical_limits?: {
    max_logical_qubits?: number;
    h2o_logical_qubits?: number;
    actual_backend?: string;
  };
}
export interface Project {
  id: string;
  task_id: string;
  name?: string;
  updated_at?: string;
  files?: ProjectFile[];
}
export interface ProjectFile {
  path: string;
  content?: string | null;
}
export interface Example {
  id: string;
  task_id: string;
  code: string;
  title: string;
}
export interface Capability {
  available: boolean;
  reason?: string;
}
export interface Capabilities {
  compile?: Capability;
  run?: Capability;
  performance?: Capability;
}
export interface System {
  executor: string;
  executor_label: string;
  mode?: string;
  capabilities?: Capabilities & { tasks?: Record<string, Capabilities> };
  tasks?: Record<string, Capabilities>;
  qperfsim?: Capability;
}
export interface RequestSnapshot {
  task_id: string;
  task_version: string;
  source: string;
  inputs: Values;
  hardware: Record<string, string>;
  hardware_profile_digests?: Record<string, string>;
}
export interface Diagnostic {
  line?: number;
  message: string;
  path?: string;
  severity?: string;
}
export interface Circuit {
  valid: boolean;
  qubits: number;
  gates: { name: string; args: (number | number[])[]; line?: number }[];
  gate_count: number;
  scope?: string;
  variants?: Record<string, Circuit>;
}
export interface Plan {
  task_id: string;
  normalized_inputs: Values;
  stages: {
    id: string;
    title: string;
    device: string;
    target_id?: string;
    target_snapshot?: TargetSnapshot;
  }[];
}
export interface Program {
  source: string;
  source_sha256: string;
  execution_sha256?: string;
  circuit?: Circuit;
}
export interface Compile {
  valid: boolean;
  diagnostics?: Diagnostic[];
  circuit?: Circuit;
  plan?: Plan;
  program?: Program;
  run?: Run;
}
export interface RunEvent {
  type: string;
  phase?: string;
  stage_id?: string;
  progress?: number;
  completed_steps?: number;
  total_steps?: number;
  message?: string;
  [key: string]: unknown;
}
export interface Artifact {
  id?: string;
  artifact_id?: string;
  name: string;
  available: boolean;
  type?: string;
  download_url?: string;
  size_bytes?: number;
}
export interface RunResult {
  execution_mode?: string;
  actual_device?: string;
  device_name?: string;
  runtime_execution?: Record<string, unknown>;
  summary?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  scientific_status?: string;
  calculation_checks?: { id: string; label: string; passed: boolean; criterion: string; observed?: string | null }[];
  artifacts?: Artifact[];
  logs?: string[];
  probabilities?: Record<string, number>;
  counts?: Record<string, number>;
  stage_results?: {
    stage_id: string;
    device: string;
    actual_device?: string;
    status: string;
  }[];
  quantum_execution?: {
    actual_device?: string;
    requested_device?: string;
    backend?: string;
  };
}
export interface Run {
  id: string;
  task_id: string;
  status: string;
  progress: number;
  request?: RequestSnapshot & { program?: Program };
  plan: Plan;
  events: RunEvent[];
  result?: RunResult | null;
}
export interface ResultResponse {
  run_id: string;
  status: string;
  result: RunResult | null;
  events: RunEvent[];
}
export interface SeriesPoint {
  step: number;
  time_fs: number;
  [key: string]: number | null;
}
export interface Series {
  items: SeriesPoint[];
  units?: Record<string, string>;
  complete?: boolean;
}
export interface Frame {
  step: number;
  time_fs: number;
  positions: number[][];
}
export interface Trajectory {
  symbols: string[];
  frames: Frame[];
  total: number;
  start: number;
  limit: number;
  complete: boolean;
}
export interface Prediction {
  id?: string;
  prediction_id?: string;
  plan: Plan;
  model_scope?: { notes?: string[] };
  request?: { scope_notes?: string[]; validation_scope?: string };
  result?: {
    prediction?: {
      latency_seconds?: number;
      stage_seconds?: Record<string, number>;
      phase_seconds?: Record<string, number>;
      throughput_jobs_per_hour?: number;
      main_bottleneck?: string;
    };
  };
}
