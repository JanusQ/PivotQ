import { test, expect } from "@playwright/test";
const source =
  "from pivotq.quantum import QuantumCircuit\ncircuit = QuantumCircuit(2)\ncircuit.h(0)\ncircuit.cx(0, 1)\ncircuit.measure([0, 1])";
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
const task = {
  id: "quantum-circuit",
  version: "1.0",
  title: "量子电路实验",
  input_schema: {
    properties: {
      shots: {
        type: "integer",
        title: "采样次数",
        default: 1024,
        minimum: 1,
        maximum: 100000,
      },
      seed: { type: "integer", title: "采样种子", default: 42 },
    },
  },
  stages: [
    {
      id: "circuit_execution",
      title: "电路执行",
      default_device: "cpu",
      allowed_devices: ["cpu"],
      depends_on: [],
    },
  ],
};
const plan = {
  task_id: task.id,
  normalized_inputs: { shots: 1024, seed: 42 },
  stages: [
    {
      id: "circuit_execution",
      title: "电路执行",
      device: "cpu",
      target_id: "cpu-local",
    },
  ],
};
const program = {
  source,
  source_sha256: "1234567890abcdef",
  execution_sha256: "1234567890abcdef",
  circuit,
};
test.beforeEach(async ({ page }) => {
  let polls = 0;
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let payload: unknown = {};
    if (path.endsWith("/task-types")) payload = { items: [task] };
    else if (path.endsWith("/projects"))
      payload = { items: [{ id: "project-circuit-demo", task_id: task.id }] };
    else if (path.endsWith("/examples"))
      payload = { items: [{ task_id: task.id, code: source }] };
    else if (path.endsWith("/hardware-targets"))
      payload = {
        items: [
          { id: "cpu-local", title: "本地 CPU", kind: "cpu", available: true },
        ],
      };
    else if (path.endsWith("/system/status"))
      payload = {
        executor: "local_cpu",
        executor_label: "CPU 本地计算",
        capabilities: {
          run: { available: true },
          compile: { available: true },
          performance: { available: false, reason: "CPU 路径暂不支持性能预测" },
        },
      };
    else if (path.endsWith("/compile")) {
      await new Promise((r) => setTimeout(r, 350));
      payload = { valid: true, program, circuit, plan };
    } else if (path.endsWith("/run"))
      payload = {
        valid: true,
        program,
        circuit,
        run: {
          id: "run-test",
          task_id: task.id,
          status: "QUEUED",
          progress: 0,
          events: [],
          request: { program },
          plan,
        },
      };
    else if (path.endsWith("/result"))
      payload = {
        run_id: "run-test",
        status: polls >= 3 ? "SUCCEEDED" : "RUNNING",
        events: [],
        result:
          polls >= 3
            ? {
                execution_mode: "local_cpu",
                probabilities: { "00": 0.5, "11": 0.5 },
                counts: { "00": 512, "11": 512 },
                metrics: { compute_seconds: 0.01 },
                scientific_status: "not_available",
              }
            : null,
      };
    else if (path.endsWith("/run-test"))
      payload = {
        id: "run-test",
        task_id: task.id,
        status: ++polls >= 3 ? "SUCCEEDED" : "RUNNING",
        progress: polls >= 3 ? 100 : 20,
        events: [],
        request: { program },
        plan,
      };
    await route.fulfill({ json: payload });
  });
});
test("submits current source, polls to completion and restores a run URL", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "编写与配置" })).toBeVisible();
  await expect(page.getByRole("button", { name: /预测：/ })).toBeDisabled();
  await expect(
    page.getByRole("img", { name: "编译后的量子电路" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "提交任务", exact: true }).click();
  await expect(
    page.getByLabel("所选运行的详情").getByText("已完成", { exact: true }),
  ).toBeVisible({
    timeout: 10000,
  });
  await expect(page.getByText("50.00%", { exact: true })).toHaveCount(2);
  await expect(page).toHaveURL(/results\.html\?run=run-test/);
  await page.reload();
  await expect(
    page.getByLabel("所选运行的详情").getByText("已完成", { exact: true }),
  ).toBeVisible();
});
test("ignores a compile result after the source is edited", async ({
  page,
}) => {
  let releaseCompile!: () => void;
  const compileReleased = new Promise<void>((resolve) => {
    releaseCompile = resolve;
  });
  let compileStarted!: () => void;
  const compileRequested = new Promise<void>((resolve) => {
    compileStarted = resolve;
  });
  await page.route("**/api/v1/projects/*/compile", async (route) => {
    compileStarted();
    await compileReleased;
    await route.fulfill({ json: { valid: true, program, circuit, plan } });
  });
  await page.goto("/");
  await compileRequested;
  await page
    .getByRole("textbox", { name: "程序编辑器" })
    .fill(source + "\n# newer edit");
  releaseCompile();
  await expect(page.getByText("代码已变化，请重新编译")).toBeVisible();
  await expect(page.getByRole("img", { name: "编译后的量子电路" })).toHaveCount(
    0,
  );
});
test("persists drafts and supports keyboard source viewer dismissal", async ({
  page,
}) => {
  await page.route("**/api/v1/projects/project-circuit-demo", (route) =>
    route.fulfill({
      json: {
        files: [
          { path: "main.py", content: source },
          { path: "helper.py", content: "# read-only helper" },
        ],
      },
    }),
  );
  await page.goto("/");
  await page
    .getByRole("textbox", { name: "程序编辑器" })
    .fill(source + "\n# local draft");
  await page.reload();
  await expect(page.getByRole("textbox", { name: "程序编辑器" })).toContainText(
    "# local draft",
  );
  await page.getByRole("button", { name: "helper.py", exact: true }).click();
  await page.getByRole("button", { name: "展开查看源码" }).click();
  await expect(
    page.getByRole("dialog", { name: "源码查看 helper.py" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
test("plays only recorded trajectory frames and retains coordinates without WebGL", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      ...args: Parameters<typeof original>
    ) {
      if (String(args[0]).includes("webgl")) return null;
      return original.apply(this, args);
    } as typeof original;
  });
  const frames = [
    {
      step: 0,
      time_fs: 0,
      positions: [
        [0, 0, 0],
        [0.75, 0.58, 0],
        [-0.75, 0.58, 0],
      ],
    },
    {
      step: 5,
      time_fs: 0.05,
      positions: [
        [0, 0, 0],
        [0.76, 0.58, 0],
        [-0.74, 0.58, 0],
      ],
    },
    {
      step: 11,
      time_fs: 0.11,
      positions: [
        [0, 0, 0],
        [0.77, 0.59, 0],
        [-0.73, 0.57, 0],
      ],
    },
  ];
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    let payload: unknown;
    if (url.pathname.endsWith("/task-types"))
      payload = { items: [{ ...task, id: "h2o-hybrid-aimd" }] };
    else if (url.pathname.endsWith("/projects"))
      payload = { items: [{ id: "project-h2o", task_id: "h2o-hybrid-aimd" }] };
    else if (url.pathname.endsWith("/examples"))
      payload = { items: [{ task_id: "h2o-hybrid-aimd", code: "steps = 20" }] };
    else if (url.pathname.endsWith("/run-trajectory"))
      payload = {
        id: "run-trajectory",
        task_id: "h2o-hybrid-aimd",
        status: "SUCCEEDED",
        progress: 100,
        events: [],
        plan: { ...plan, normalized_inputs: { steps: 20 } },
      };
    else if (url.pathname.endsWith("/run-trajectory/result"))
      payload = {
        status: "SUCCEEDED",
        events: [],
        result: {
          execution_mode: "local_cpu",
          artifacts: [],
          summary: { completed_steps: 11 },
          scientific_status: "not_available",
          calculation_checks: [{
            id: "total_energy_drift_within_limit",
            label: "总能量漂移",
            passed: true,
            criterion: "绝对值 ≤ 0.03 eV",
            observed: "0.02 eV",
          }],
        },
      };
    else if (url.pathname.endsWith("/series"))
      payload = {
        items: frames.map((frame, i) => ({
          step: frame.step,
          time_fs: frame.time_fs,
          total_energy_eV: -76 + i * 0.001,
        })),
      };
    else if (url.pathname.endsWith("/trajectory"))
      payload = {
        symbols: ["O", "H", "H"],
        frames,
        total: 3,
        start: 0,
        limit: 500,
        complete: false,
      };
    else return route.fallback();
    await route.fulfill({ json: payload });
  });
  await page.goto("/results.html?run=run-trajectory");
  await page.getByText("计算检查项目与判定标准", { exact: true }).click();
  await expect(page.getByText("总能量漂移：通过", { exact: true })).toBeVisible();
  await expect(page.getByText(/绝对值 ≤ 0.03 eV.*记录值：0.02 eV/)).toBeVisible();
  await expect(page.getByText("当前浏览器无法显示三维视图")).toBeVisible();
  await expect(page.getByText("不完整", { exact: true })).toBeVisible();
  await page.getByRole("slider", { name: "轨迹帧" }).focus();
  await page.keyboard.press("End");
  await expect(page.getByText("第 11 步 / 0.110 fs", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "0.7700", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: /总能量随时间变化/ }),
  ).toBeVisible();
});
