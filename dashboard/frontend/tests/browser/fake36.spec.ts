import { test, expect } from "@playwright/test";

const source =
  "from pivotq.quantum import QuantumCircuit\ncircuit = QuantumCircuit(2)\ncircuit.h(0)\ncircuit.cx(0, 1)\ncircuit.measure([0, 1])";
const nodes = Array.from({ length: 36 }, (_, i) => i);
const edges = nodes.flatMap((i) => [
  ...(i % 6 < 5 ? [[i, i + 1]] : []),
  ...(i < 30 ? [[i, i + 6]] : []),
]);
const profile = {
  id: "fake-sc-36",
  kind: "qpu",
  title: "Fake SC-36 · 6×6 超导芯片",
  profile_version: "fake-sc-36-v1",
  profile_sha256: "saved-profile-digest",
  virtual: true,
  parameters: {
    qubits: 36,
    topology: { rows: 6, columns: 6, nodes, edges },
    shot_rate: 10000,
    submit_latency_us: 1000,
    model: "shot_throughput",
    calibrated: false,
  },
  numerical_limits: {
    max_logical_qubits: 12,
    h2o_logical_qubits: 3,
    actual_backend: "cpu",
  },
};
const plan = {
  task_id: "quantum-circuit",
  normalized_inputs: { shots: 1024, seed: 42 },
  stages: [
    {
      id: "circuit_execution",
      title: "电路执行",
      device: "qpu",
      target_id: profile.id,
      target_snapshot: { ...profile, logical_qubits: 2 },
    },
  ],
};
const circuit = {
  valid: true,
  qubits: 2,
  gate_count: 3,
  gates: [
    { name: "H", args: [0] },
    { name: "CX", args: [0, 1] },
    { name: "MEASURE", args: [[0, 1]] },
  ],
};
const program = {
  source,
  source_sha256: "source-digest",
  execution_sha256: "execution-digest",
  circuit,
};
const run = {
  id: "fake-run",
  task_id: "quantum-circuit",
  status: "SUCCEEDED",
  progress: 100,
  events: [],
  request: { program },
  plan,
};
const prediction = {
  id: "fake-prediction",
  plan,
  model_scope: { notes: ["吞吐模型示例参数"] },
  request: { scope_notes: ["吞吐模型示例参数"] },
  result: {
    prediction: {
      latency_seconds: 0.1034,
      phase_seconds: { acquisition: 0.1034 },
    },
  },
};

async function setup(page: import("@playwright/test").Page) {
  const requests: { path: string; body: Record<string, unknown> }[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "POST")
      requests.push({ path, body: route.request().postDataJSON() });
    let payload: unknown;
    if (path.endsWith("/task-types"))
      payload = {
        items: [
          {
            id: "quantum-circuit",
            version: "1.0",
            title: "量子电路",
            input_schema: {
              properties: {
                shots: { type: "integer", title: "采样次数", default: 1024 },
                seed: { type: "integer", title: "采样种子", default: 42 },
              },
            },
            stages: [
              {
                id: "circuit_execution",
                title: "电路执行",
                default_device: "qpu",
                allowed_devices: ["cpu", "gpu", "qpu"],
                depends_on: [],
              },
            ],
          },
        ],
      };
    else if (path.endsWith("/projects"))
      payload = {
        items: [{ id: "project-circuit", task_id: "quantum-circuit" }],
      };
    else if (path.endsWith("/examples"))
      payload = { items: [{ task_id: "quantum-circuit", code: source }] };
    else if (path.endsWith("/hardware-targets"))
      payload = {
        items: [
          { id: "cpu-0", title: "逻辑 CPU", kind: "cpu", available: true },
          {
            id: profile.id,
            title: profile.title,
            kind: "qpu",
            available: true,
            target_snapshot: profile,
          },
        ],
      };
    else if (path.endsWith("/system/status"))
      payload = {
        executor: "local_cpu",
        capabilities: {
          compile: { available: true },
          run: { available: true },
          performance: { available: true },
        },
        qperfsim: { available: true },
      };
    else if (path.endsWith("/compile"))
      payload = { valid: true, program, circuit, plan };
    else if (
      path.endsWith("/performance/run") ||
      path.endsWith("/performance/runs/fake-prediction")
    )
      payload = prediction;
    else if (path.endsWith("/run"))
      payload = { valid: true, program, circuit, plan, run };
    else if (path.endsWith("/fake-run")) payload = run;
    else if (path.endsWith("/fake-run/result"))
      payload = {
        status: "SUCCEEDED",
        events: [],
        result: {
          actual_device: "cpu",
          device_name: "CPU",
          execution_mode: "local_cpu",
          probabilities: { "00": 0.5, "11": 0.5 },
          counts: { "00": 510, "11": 514 },
          metrics: { compute_seconds: 0.01 },
          stage_results: [
            {
              stage_id: "circuit_execution",
              // Older records may use this field for the logical target.
              device: "qpu",
              status: "SUCCEEDED",
            },
          ],
        },
      };
    else payload = { items: [] };
    await route.fulfill({ json: payload });
  });
  return requests;
}

test("selects the virtual chip, shows its topology and shares targets across run and prediction", async ({
  page,
}) => {
  const requests = await setup(page);
  await page.goto("/");
  await expect(
    page.getByRole("combobox", { name: "电路执行硬件" }),
  ).toHaveValue("fake-sc-36");
  await expect(
    page.getByRole("img", { name: "编译后的量子电路" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "提交任务", exact: true }).click();
  await expect(page).toHaveURL(/results\.html\?run=fake-run/);
  await expect(
    page.getByLabel("所选运行的详情").getByText("已完成", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("CPU 实测用时", { exact: true })).toBeVisible();
  const assignments = page.getByLabel("保存的目标硬件配置");
  await expect(
    assignments.getByText("实际执行：CPU 数值模拟", { exact: true }),
  ).toBeVisible();
  await expect(
    assignments.getByText("电路使用：2 个逻辑量子比特 / 目标芯片模型容量：36 个量子比特", {
      exact: true,
    }),
  ).toBeVisible();
  await assignments.getByText("本次采用的设备参数", { exact: true }).click();
  const topology = assignments.getByRole("img", {
    name: /拓扑：36 个比特，60 条无向边/,
  });
  await expect(topology.locator("circle")).toHaveCount(36);
  await expect(topology.locator("line")).toHaveCount(60);
  await expect(
    assignments.getByText("10,000 shots/s", { exact: true }),
  ).toBeVisible();
  await expect(assignments.getByText("1 ms", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "工作台 编写与配置", exact: true }).click();
  await expect(
    page.getByRole("img", { name: "编译后的量子电路" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "性能预测", exact: true }).click();
  await expect(page).toHaveURL(/performance\.html\?prediction=fake-prediction/);
  await expect(page.getByText("预计总耗时", { exact: true })).toBeVisible();
  await expect(page.getByText("QPU 运行与测量", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "估算条件与适用范围" })).toBeVisible();
  await expect(page.getByText("吞吐模型示例参数", { exact: true })).toHaveCount(
    2,
  );
  expect(
    requests.filter((request) => request.path.endsWith("/run")),
  ).toHaveLength(2);
  expect(
    requests.filter((request) => request.path.endsWith("/compile")),
  ).toHaveLength(2);
  for (const request of requests) {
    expect(request.body.hardware).toEqual({ circuit_execution: "fake-sc-36" });
    expect(request.body.hardware_profile_digests).toEqual({
      circuit_execution: profile.profile_sha256,
    });
  }
  await page.reload();
  await expect(page.getByText("预计总耗时", { exact: true })).toBeVisible();
  await page.getByText("本次采用的设备参数", { exact: true }).click();
  await expect(page.getByText(/参数版本 fake-sc-36-v1/)).toBeVisible();
});

test("preserves old CPU drafts and explains the absent target model", async ({
  page,
}) => {
  await setup(page);
  await page.addInitScript(
    ({ source }) => {
      localStorage.setItem(
        "qhai-dashboard-draft-quantum-circuit",
        JSON.stringify({
          task_id: "quantum-circuit",
          source,
          inputs: { shots: 100, seed: 7 },
          hardware: { circuit_execution: "cpu-0" },
        }),
      );
    },
    { source },
  );
  await page.goto("/");
  await expect(
    page.getByRole("combobox", { name: "电路执行硬件" }),
  ).toHaveValue("cpu-0");
  await expect(
    page.getByRole("button", { name: "提交任务", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("button", { name: /预测：所选量子目标暂无预测模型/ }),
  ).toBeDisabled();
  await page
    .getByRole("combobox", { name: "电路执行硬件" })
    .selectOption("fake-sc-36");
  await expect(
    page.getByRole("button", { name: "性能预测", exact: true }),
  ).toBeEnabled();
});

test("restores historical prediction parameters independently of current discovery", async ({
  page,
}) => {
  await setup(page);
  await page.route("**/api/v1/hardware-targets", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: profile.id,
            title: "Current renamed chip",
            kind: "qpu",
            available: true,
            target_snapshot: {
              ...profile,
              title: "Current renamed chip",
              profile_version: "future-v2",
              profile_sha256: "new-digest",
              parameters: { ...profile.parameters, shot_rate: 20000 },
            },
          },
        ],
      },
    }),
  );
  await page.goto("/performance.html?prediction=fake-prediction");
  const saved = page.getByLabel("保存的目标硬件配置");
  await expect(
    saved.getByText("预测配置：SC-36 虚拟超导芯片（6×6，36 比特）", { exact: true }),
  ).toBeVisible();
  await saved.getByText("本次采用的设备参数", { exact: true }).click();
  await expect(
    saved.getByText("10,000 shots/s", { exact: true }),
  ).toBeVisible();
  await expect(saved.getByText(/future-v2/)).toHaveCount(0);
});
