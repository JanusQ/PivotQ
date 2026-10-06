import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, PointerEvent, ReactElement } from "react";
import {
  api,
  apiDelete,
  ApiError,
  setLocation,
  store,
  stored,
  terminal,
} from "./api/client";
import type {
  Capabilities,
  Compile,
  Diagnostic,
  Example,
  Prediction,
  Project,
  ProjectFile,
  RequestSnapshot,
  Run,
  System,
  Target,
  Task,
  Values,
} from "./api/types";
import { stageLabel, targetLabel } from "./api/labels";
import Editor from "./components/Editor";
import {
  hardwareChoices,
  hardwareProfileDigests,
  repairFixedChoices,
} from "./api/hardware";
import CircuitDiagram from "./components/CircuitDiagram";
import PerformancePage from "./pages/PerformancePage";
import ResultsPage from "./pages/ResultsPage";
import { useRun } from "./hooks/useRun";
import { pollUntil } from "./hooks/poll";
import s from "./App.module.css";
const draftKey = (id: string) => `qhai-dashboard-draft-${id}`;
// The current public workspace exposes the H₂O AIMD example only.  Other task
// adapters remain available through the backend API for later rollout.
const VISIBLE_TASK_ID = "h2o-hybrid-aimd";
const taskTitle = (id: string) =>
  id === "quantum-circuit" ? "量子电路" : "水分子动力学模拟（H₂O AIMD）";
const deviceColor = (kind: string) =>
  kind.startsWith("qpu")
    ? "var(--qpu)"
    : kind === "gpu"
      ? "var(--gpu)"
      : "var(--cpu)";
const pageFromPath = () => {
  const path = window.location.pathname.toLowerCase();
  if (path.endsWith("performance.html")) return "performance" as const;
  if (path.endsWith("results.html")) return "results" as const;
  return "workspace" as const;
};

type FileTreeNode = {
  name: string;
  path: string;
  isFile: boolean;
  children: FileTreeNode[];
};

const buildFileTree = (files: ProjectFile[]): FileTreeNode[] => {
  const roots: FileTreeNode[] = [];
  for (const file of files) {
    const path = file.path.replaceAll("\\", "/").replace(/^\/+|\/+$/g, "");
    if (!path) continue;
    const parts = path.split("/").filter(Boolean);
    let children = roots;
    let parentPath = "";
    parts.forEach((part, index) => {
      const currentPath = parentPath ? `${parentPath}/${part}` : part;
      const isFile = index === parts.length - 1;
      let node = children.find((item) => item.name === part);
      if (!node) {
        node = { name: part, path: currentPath, isFile, children: [] };
        children.push(node);
      }
      if (!isFile) {
        children = node.children;
      }
      parentPath = currentPath;
    });
  }
  const sort = (nodes: FileTreeNode[]) => {
    nodes.sort(
      (left, right) =>
        Number(right.isFile) - Number(left.isFile) ||
        left.name.localeCompare(right.name, "en", { sensitivity: "base" }),
    );
    nodes.forEach((node) => sort(node.children));
  };
  sort(roots);
  // Keep the entry point at the top so the visible source and execution
  // entry remain easy to find, while grouping all other files by directory.
  roots.sort((left, right) => {
    if (left.path === "main.py") return -1;
    if (right.path === "main.py") return 1;
    return 0;
  });
  return roots;
};

function FileTree({
  files,
  activePath,
  onSelect,
}: {
  files: ProjectFile[];
  activePath: string;
  onSelect: (path: string) => void;
}) {
  const nodes = buildFileTree(files);
  const [currentPath, setCurrentPath] = useState("");
  const findNode = (
    items: FileTreeNode[],
    path: string,
  ): FileTreeNode | null => {
    for (const item of items) {
      if (item.path === path) return item;
      if (!item.isFile) {
        const match = findNode(item.children, path);
        if (match) return match;
      }
    }
    return null;
  };
  const currentNode = currentPath ? findNode(nodes, currentPath) : null;
  const visibleNodes = currentNode?.children || nodes;
  const parentPath = currentPath.includes("/")
    ? currentPath.slice(0, currentPath.lastIndexOf("/"))
    : "";

  useEffect(() => {
    if (currentPath && !findNode(nodes, currentPath)) setCurrentPath("");
  }, [files]);

  const renderNode = (node: FileTreeNode): ReactElement => {
    if (!node.isFile) {
      return (
        <div className={s.fileFolder} key={node.path}>
          <button
            type="button"
            className={s.folderItem}
            style={{ paddingLeft: "8px" }}
            aria-label={`打开文件夹 ${node.name}`}
            onClick={() => setCurrentPath(node.path)}
            title={node.path}
          >
            <span className={s.folderChevron} aria-hidden="true">›</span>
            <span className={s.folderIcon} aria-hidden="true" />
            <span className={s.folderName}>{node.name}</span>
          </button>
        </div>
      );
    }
    const fileName = node.name;
    const extension = fileName.includes(".")
      ? fileName.split(".").pop()?.toLowerCase() || ""
      : "";
    return (
      <button
        key={node.path}
        type="button"
        className={`${s.fileItem} ${activePath === node.path ? s.fileItemActive : ""}`}
        style={{ paddingLeft: "20px" }}
        onClick={() => onSelect(node.path)}
        title={node.path}
        aria-current={activePath === node.path ? "page" : undefined}
      >
        <span className={`${s.fileIcon} ${extension === "py" ? s.pythonFile : ""}`} aria-hidden="true">
          {extension === "py" ? "Py" : extension ? extension.slice(0, 2).toUpperCase() : "·"}
        </span>
        <span className={s.fileName}><span>{fileName}</span></span>
      </button>
    );
  };

  return (
    <>
      <div className={s.fileSidebarHeader}>
        <span>项目文件</span>
        {currentPath && (
          <button
            type="button"
            className={s.backButton}
            onClick={() => setCurrentPath(parentPath)}
            aria-label={`返回上一级${parentPath ? ` ${parentPath}` : ""}`}
            title="返回上一级"
          >
            <span aria-hidden="true">←</span>
            <span>上一级</span>
          </button>
        )}
      </div>
      <nav className={s.fileTree} aria-label={`${currentPath || "根目录"}源文件列表`}>
        {visibleNodes.map((node) => renderNode(node))}
      </nav>
    </>
  );
}

export default function App() {
  const page = pageFromPath();
  const [tasks, setTasks] = useState<Task[]>([]),
    [projects, setProjects] = useState<Project[]>([]),
    [examples, setExamples] = useState<Example[]>([]),
    [targets, setTargets] = useState<Target[]>([]),
    [system, setSystem] = useState<System | null>(null),
    [taskId, setTaskId] = useState(""),
    [source, setSource] = useState(""),
    [projectFiles, setProjectFiles] = useState<ProjectFile[]>([]),
    [activeFilePath, setActiveFilePath] = useState("main.py"),
    [inputs, setInputs] = useState<Values>({}),
    [hardware, setHardware] = useState<Record<string, string>>({}),
    [initialError, setInitialError] = useState(""),
    [initKey, setInitKey] = useState(0);
  const [compiled, setCompiled] = useState<Compile | null>(null),
    [compiledKey, setCompiledKey] = useState(""),
    [diagnostics, setDiagnostics] = useState<Diagnostic[]>([]),
    [busy, setBusy] = useState(""),
    [feedback, setFeedback] = useState<{
      kind: "compile" | "run" | "performance";
      status: "success" | "error";
    } | null>(null),
    [notice, setNotice] = useState(""),
    [noticeError, setNoticeError] = useState(false),
    [historyRuns, setHistoryRuns] = useState<Run[]>([]),
    [runId, setRunId] = useState<string | null>(
      new URLSearchParams(location.search).get("run"),
    ),
    [prediction, setPrediction] = useState<Prediction | null>(null),
    [tab, setTab] = useState(
      new URLSearchParams(location.search).has("prediction")
        ? "performance"
        : "result",
    ),
    [cancelling, setCancelling] = useState(false),
    [split, setSplit] = useState(44),
    [codeViewerOpen, setCodeViewerOpen] = useState(false);
  const task = tasks.find((t) => t.id === taskId),
    workspace = useRef<HTMLDivElement>(null),
    busyRef = useRef(false),
    autoCompileStarted = useRef(false),
    revision = useRef(""),
    actionGeneration = useRef(0);
  const { run, series, error: syncError } = useRun(runId);
  useEffect(() => {
    if (!codeViewerOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setCodeViewerOpen(false);
    };
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [codeViewerOpen]);
  const selectTask = useCallback(
    (
      id: string,
      availableTasks: Task[] = tasks,
      availableExamples: Example[] = examples,
      availableTargets: Target[] = targets,
    ) => {
      const chosen =
        availableTasks.find((t) => t.id === id) || availableTasks[0];
      if (!chosen) return;
      const draft =
        stored<RequestSnapshot>(draftKey(chosen.id)) ||
        stored<RequestSnapshot>(`qhai-program-v2-${chosen.id}`);
      setTaskId(chosen.id);
      setActiveFilePath("main.py");
      setProjectFiles([]);
      setSource(
        draft?.source ??
          availableExamples.find((e) => e.task_id === chosen.id)?.code ??
          "",
      );
      setInputs(
        Object.fromEntries(
          Object.entries(chosen.input_schema.properties).map(
            ([key, definition]) => [
              key,
              draft?.inputs?.[key] ?? definition.default,
            ],
          ),
        ),
      );
      setHardware(
        hardwareChoices(chosen.stages, availableTargets, draft?.hardware),
      );
      setCompiled(null);
      setCompiledKey("");
      setDiagnostics([]);
      setNotice("");
      setNoticeError(false);
      store("qhai-dashboard-task", chosen.id);
    },
    [tasks, examples, targets],
  );
  useEffect(() => {
    const controller = new AbortController();
    setInitialError("");
    void Promise.all([
      api<{ items: Task[] }>("/task-types", undefined, controller.signal),
      api<{ items: Project[] }>("/projects", undefined, controller.signal),
      api<{ items: Example[] }>("/examples", undefined, controller.signal),
      api<{ items: Target[] }>(
        "/hardware-targets",
        undefined,
        controller.signal,
      ).catch(() => ({ items: [] })),
      api<System>("/system/status", undefined, controller.signal),
    ])
      .then(([t, p, e, h, sys]) => {
        if (controller.signal.aborted) return;
        const h2oTasks = t.items.filter((item) => item.id === VISIBLE_TASK_ID);
        const h2oProjects = p.items.filter(
          (item) => item.task_id === VISIBLE_TASK_ID,
        );
        const h2oExamples = e.items.filter(
          (item) => item.task_id === VISIBLE_TASK_ID,
        );
        // A legacy or test backend may expose only one non-H₂O task. Keep it
        // usable in that case; the current backend always supplies H₂O, so
        // production never presents the hidden quantum-circuit task.
        const visibleTasks = h2oTasks.length ? h2oTasks : t.items;
        const visibleProjects = h2oTasks.length ? h2oProjects : p.items;
        const visibleExamples = h2oTasks.length ? h2oExamples : e.items;
        setTasks(visibleTasks);
        setProjects(visibleProjects);
        setExamples(visibleExamples);
        setTargets(h.items);
        const currentTask = tasks.find((item) => item.id === taskId);
        if (currentTask)
          setHardware((previous) =>
            repairFixedChoices(currentTask.stages, h.items, previous),
          );
        setSystem(sys);
        selectTask(
          stored<string>("qhai-dashboard-task") || VISIBLE_TASK_ID,
          visibleTasks,
          visibleExamples,
          h.items,
        );
      })
      .catch((error) => {
        if (!controller.signal.aborted) setInitialError(error.message);
      });
    return () => controller.abort();
  }, [initKey]);
  useEffect(() => {
    if (!tasks.length) return;
    return pollUntil(
      async (signal) => {
        const [h, sys] = await Promise.all([
          api<{ items: Target[] }>("/hardware-targets", undefined, signal),
          api<System>("/system/status", undefined, signal),
        ]);
        return { h, sys };
      },
      ({ h, sys }) => {
        setTargets(h.items);
        const currentTask = tasks.find((item) => item.id === taskId);
        if (currentTask)
          setHardware((previous) =>
            repairFixedChoices(currentTask.stages, h.items, previous),
          );
        setSystem(sys);
      },
      () => undefined,
      () => false,
      10000,
    );
  }, [tasks, taskId]);
  useEffect(() => {
    const project = projects.find((item) => item.task_id === taskId);
    if (!project) {
      setProjectFiles([]);
      return;
    }
    const controller = new AbortController();
    void api<{ files?: ProjectFile[] }>(
      `/projects/${encodeURIComponent(project.id)}`,
      undefined,
      controller.signal,
    )
      .then((detail) => {
        if (controller.signal.aborted) return;
        const files = (detail.files || [])
          .filter((file) => typeof file?.path === "string" && file.path.trim())
          .map((file) => ({
            path: file.path.replaceAll("\\", "/"),
            content: typeof file.content === "string" ? file.content : "",
          }));
        setProjectFiles(
          files.length ? files : [{ path: "main.py", content: source }],
        );
        setActiveFilePath((current) =>
          files.some((file) => file.path === current) ? current : "main.py",
        );
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setProjectFiles([{ path: "main.py", content: source }]);
      });
    return () => controller.abort();
  }, [projects, taskId]);
  const snapshot: RequestSnapshot = {
    task_id: taskId,
    task_version: task?.version || "1.0",
    source,
    inputs: taskId === "h2o-hybrid-aimd" ? {} : inputs,
    hardware,
    hardware_profile_digests: hardwareProfileDigests(hardware, targets),
  };
  const requestKey = JSON.stringify(snapshot);
  revision.current = requestKey;
  const stale = !!compiled && compiledKey !== requestKey;
  useEffect(() => {
    if (taskId) store(draftKey(taskId), snapshot);
    setDiagnostics([]);
  }, [requestKey]);
  const flashFeedback = (
    kind: "compile" | "run" | "performance",
    status: "success" | "error",
  ) => {
    setFeedback({ kind, status });
    window.setTimeout(
      () =>
        setFeedback((current) =>
          current?.kind === kind ? null : current,
        ),
      1800,
    );
  };
  useEffect(() => {
    const id = new URLSearchParams(location.search).get("prediction");
    if (!id) return;
    const controller = new AbortController();
    void api<Prediction>(
      `/performance/runs/${encodeURIComponent(id)}`,
      undefined,
      controller.signal,
    )
      .then(setPrediction)
      .catch((error) => {
        if (!controller.signal.aborted) {
          setNotice(error.message);
          setNoticeError(true);
        }
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const handler = () => {
      const url = new URLSearchParams(location.search);
      setRunId(url.get("run"));
    };
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
  }, []);
  useEffect(() => {
    if (page !== "results") return;
    return pollUntil(
      (signal) => api<{ items: Run[] }>("/runs", undefined, signal),
      (data) =>
        setHistoryRuns(
          data.items
            .filter((item) => item.task_id === VISIBLE_TASK_ID)
            .reverse(),
        ),
      () => undefined,
      () => false,
      5000,
    );
  }, [page]);
  useEffect(() => {
    if (run && terminal(run.status)) setCancelling(false);
  }, [run?.status]);
  const capabilities: Capabilities = {
    ...system?.capabilities,
    ...system?.capabilities?.tasks?.[taskId],
    ...system?.tasks?.[taskId],
  };
  const unavailable = task?.stages.some(
    (stage) =>
      !targets.some(
        (target) =>
          target.id === hardware[stage.id] &&
          target.available &&
          stage.allowed_devices.includes(target.kind),
      ),
  );
  const selectedQuantum = targets.find(
      (t) =>
        t.id ===
        hardware[
          taskId === "quantum-circuit"
            ? "circuit_execution"
            : "quantum_features"
        ],
    ),
    selectedClassical = targets.find(
      (target) => target.id === hardware.classical_predict,
    ),
    performanceReason = unavailable
      ? "请选择可用的目标硬件"
      : capabilities.performance?.available === false
        ? capabilities.performance.reason || "性能预测不可用"
        : system?.qperfsim?.available === false
          ? system.qperfsim.reason || "性能模拟器未就绪"
          : selectedQuantum?.kind === "cpu" ||
              (taskId === "quantum-circuit" &&
                selectedQuantum?.id !== "fake-sc-36")
            ? "所选量子目标暂无预测模型，请选择 Fake SC-36"
            : taskId === "h2o-hybrid-aimd" &&
                selectedQuantum?.id !== "fake-sc-36" &&
                selectedClassical?.kind !== "gpu"
              ? "当前量子目标的预测需要 GPU 经典目标，或选择 Fake SC-36"
              : "";
  const runReason =
    capabilities.run?.available === false
      ? capabilities.run.reason || "运行依赖未就绪"
      : unavailable
        ? "请选择可用的计算设备"
        : "";
  async function action(kind: "compile" | "run" | "performance") {
    if (!task || busyRef.current) return;
    if (
      (kind === "run" && runReason) ||
      (kind === "performance" && performanceReason)
    )
      return;
    const project = projects.find((p) => p.task_id === taskId);
    if (!project) {
      setNotice("示例项目未加载");
      setNoticeError(true);
      return;
    }
    const sentKey = requestKey,
      generation = ++actionGeneration.current;
    busyRef.current = true;
    setBusy(kind);
    setFeedback(null);
    setNotice("");
    setNoticeError(false);
    setDiagnostics([]);
    try {
      if (kind === "performance") {
        const data = await api<Prediction>("/performance/run", snapshot);
        setPrediction(data);
        const id = data.id || data.prediction_id;
        if (id) {
          const url = new URL("/performance.html", window.location.origin);
          url.searchParams.set("prediction", id);
          window.location.assign(url.toString());
        } else {
          setTab("performance");
          setNotice(
            revision.current === sentKey
              ? "预测已保存"
              : "预测已保存；编辑器内容已变化",
          );
          flashFeedback(kind, "success");
        }
      } else {
        const data = await api<Compile>(
          `/projects/${encodeURIComponent(project.id)}/${kind}`,
          snapshot,
        );
        if (generation !== actionGeneration.current) return;
        if (revision.current === sentKey) {
          setCompiled(data);
          setCompiledKey(sentKey);
          setDiagnostics([]);
          setNotice(kind === "compile" ? "编译通过" : "任务已提交");
          flashFeedback(kind, "success");
        } else
          setNotice(
            kind === "run"
              ? "任务已提交，使用提交时的代码"
              : "代码已变化，请重新编译",
          );
        if (data.run) {
          setRunId(data.run.id);
          setLocation("run", data.run.id);
          setCancelling(false);
          const url = new URL("/results.html", window.location.origin);
          url.searchParams.set("run", data.run.id);
          window.location.assign(url.toString());
        }
      }
    } catch (error) {
      if (generation !== actionGeneration.current) return;
      setNotice(error instanceof Error ? error.message : "操作失败");
      setNoticeError(true);
      flashFeedback(kind, "error");
      if (revision.current === sentKey) {
        setCompiled(null);
        if (error instanceof ApiError) setDiagnostics(error.diagnostics);
      }
    } finally {
      if (generation === actionGeneration.current) {
        busyRef.current = false;
        setBusy("");
      }
    }
  }
  async function cancel() {
    if (!run || cancelling) return;
    setCancelling(true);
    try {
      await api(`/runs/${encodeURIComponent(run.id)}/cancel`, {});
      setNotice("已请求取消，等待计算进程退出");
      setNoticeError(false);
    } catch (error) {
      setCancelling(false);
      setNotice(error instanceof Error ? error.message : "取消失败");
      setNoticeError(true);
    }
  }
  async function deleteRun(id: string) {
    await apiDelete(`/runs/${encodeURIComponent(id)}`);
    const next = historyRuns.find((item) => item.id !== id) || null;
    setHistoryRuns((current) => current.filter((item) => item.id !== id));
    if (runId === id) {
      setRunId(next?.id || null);
      setCancelling(false);
      const url = new URL(window.location.href);
      if (next) url.searchParams.set("run", next.id);
      else url.searchParams.delete("run");
      history.replaceState(null, "", url);
    }
  }
  useEffect(() => {
    if (
      page !== "workspace" ||
      autoCompileStarted.current ||
      !system ||
      !task ||
      !source ||
      !projects.some((project) => project.task_id === taskId) ||
      !targets.length ||
      compiled ||
      busyRef.current ||
      capabilities.compile?.available === false
    )
      return;
    autoCompileStarted.current = true;
    void action("compile");
  }, [page, system, task, source, projects, taskId, targets.length, compiled]);
  function resize(event: PointerEvent<HTMLDivElement>) {
    event.currentTarget.setPointerCapture(event.pointerId);
    const handler = (e: globalThis.PointerEvent) => {
      const rect = workspace.current?.getBoundingClientRect();
      if (rect)
        setSplit(
          Math.max(
            36,
            Math.min(68, ((e.clientX - rect.left) / rect.width) * 100),
          ),
        );
    };
    const stop = () => {
      window.removeEventListener("pointermove", handler);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", handler);
    window.addEventListener("pointerup", stop);
  }
  const activeStage =
    !stale &&
    run &&
    run.task_id === taskId &&
    run.request?.program?.source === source &&
    !terminal(run.status)
      ? [...run.events]
          .reverse()
          .find((event) => typeof event.stage_id === "string")?.stage_id
      : undefined;
  const visibleFiles: ProjectFile[] = projectFiles.length
      ? projectFiles
      : task
        ? [{ path: "main.py", content: source }]
        : [],
    selectedFile =
      visibleFiles.find((file) => file.path === activeFilePath) ||
      visibleFiles[0],
    selectedFileIsMain = selectedFile?.path === "main.py",
    selectedFileSource = selectedFileIsMain
      ? source
      : selectedFile?.content || "";
  return (
    <div className={s.app}>
      <header className={s.topbar}>
        <a className={s.brand} href="/" aria-label="PivotQ 可视化操作界面">
          <svg viewBox="0 0 40 40" aria-hidden="true">
            <rect
              x="8"
              y="7"
              width="17"
              height="17"
              rx="3"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
            />
            <path
              d="M25 16h7v17H16v-9"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
            />
            <circle cx="8" cy="7" r="3" fill="currentColor" />
          </svg>
          <span>PivotQ</span>
        </a>
        <nav className={s.nav}>
          <a href="/" className={page === "workspace" ? s.activeNav : ""}><span>工作台</span><small>编写与配置</small></a>
          <a href="/performance.html" className={page === "performance" ? s.activeNav : ""}><span>性能预测</span><small>预计耗时</small></a>
          <a href="/results.html" className={page === "results" ? s.activeNav : ""}><span>结果中心</span><small>运行记录与结果</small></a>
        </nav>
      </header>
      <main className={s.main}>
        {page === "performance" ? (
          <PerformancePage prediction={prediction} />
        ) : page === "results" ? (
          <ResultsPage
            runs={historyRuns}
            run={run}
            runId={runId}
            series={series}
            syncError={syncError}
            prediction={prediction}
            onSelect={(id) => {
              setRunId(id);
              setLocation("run", id);
              setCancelling(false);
            }}
            onDelete={(id) => deleteRun(id)}
            onCancel={() => void cancel()}
            cancelling={cancelling}
          />
        ) : (
        <>
        <div className={s.workspaceHeading}>
          <div>
            <span className={s.workspaceMark} />
            <h1>编写与配置</h1>
          </div>
          <div className={s.workspaceTools}>
            <div className={s.workspaceActions} aria-label="工作台操作">
              <button
                className={`${s.secondaryAction} ${busy === "compile" ? s.loadingAction : ""} ${feedback?.kind === "compile" ? feedback.status === "success" ? s.successAction : s.errorAction : ""}`}
                onClick={() => void action("compile")}
                disabled={!task || !!busy || capabilities.compile?.available === false}
                title={capabilities.compile?.reason}
              >
                {busy === "compile" ? "编译中…" : feedback?.kind === "compile" && feedback.status === "success" ? "已编译 ✓" : "编译"}
              </button>
              <span title={performanceReason}>
                <button
                  className={`${s.secondaryAction} ${busy === "performance" ? s.loadingAction : ""} ${feedback?.kind === "performance" ? feedback.status === "success" ? s.successAction : s.errorAction : ""}`}
                  onClick={() => void action("performance")}
                  disabled={!task || !!busy || !!performanceReason}
                  aria-label={performanceReason ? `预测：${performanceReason}` : "性能预测"}
                >
                  {busy === "performance" ? "预测中…" : "性能预测"}
                </button>
              </span>
              <span title={runReason}>
                <button
                  className={`${s.primary} ${busy === "run" ? s.loadingAction : ""} ${feedback?.kind === "run" ? feedback.status === "success" ? s.successAction : s.errorAction : ""}`}
                  onClick={() => void action("run")}
                  disabled={!task || !!busy || !!runReason}
                  aria-label={runReason ? `提交任务：${runReason}` : "提交任务"}
                >
                  <span className={s.playIcon}>▶</span>
                  {busy === "run" ? "提交中…" : "提交任务"}
                </button>
              </span>
            </div>
          </div>
        </div>
        {initialError ? (
          <section className={s.loadError}>
            <h2>工作台连接失败</h2>
            <p>{initialError}</p>
            <button onClick={() => setInitKey((n) => n + 1)}>重新连接</button>
          </section>
        ) : (
          <>
            <div
              className={s.workspace}
              ref={workspace}
              style={{ "--editor-width": `${split}%` } as CSSProperties}
            >
              <section className={s.editorPanel}>
                <div className={s.panelHeader}>
                  <div className={s.fileTitle}>
                    <span className={s.taskLabel}>当前应用</span>
                    <select
                      className={s.taskSelect}
                      aria-label="选择应用"
                      value={taskId}
                      disabled={!tasks.length}
                      onChange={(e) => selectTask(e.target.value)}
                    >
                      {tasks.map((t) => (
                        <option key={t.id} value={t.id}>
                          {taskTitle(t.id)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <button
                    className={s.textButton}
                    onClick={() => {
                      setSource(
                        examples.find((e) => e.task_id === taskId)?.code || "",
                      );
                      setNotice("已恢复示例程序");
                      setNoticeError(false);
                    }}
                    disabled={!task}
                  >
                    <svg
                      className={s.restartIcon}
                      viewBox="0 0 24 24"
                      aria-hidden="true"
                    >
                      <path d="M4 4v5h5" />
                      <path d="M4.9 9A8 8 0 1 1 6.3 17.4" />
                    </svg>
                    <span>恢复示例</span>
                  </button>
                </div>
                <div className={s.editorBody}>
                  {task ? (
                    <>
                      <aside className={s.fileSidebar} aria-label="项目文件">
                        <FileTree
                          files={visibleFiles}
                          activePath={selectedFile?.path || "main.py"}
                          onSelect={setActiveFilePath}
                        />
                      </aside>
                      <div className={s.editorSurface}>
                        <div className={s.editorFileBar}>
                          <span className={s.editorFilePath}>{selectedFile?.path || "main.py"}</span>
                          <span className={s.editorFileMode}>
                            {!selectedFileIsMain && (
                              <>
                                <button
                                  type="button"
                                  className={s.codeExpandButton}
                                  aria-label="展开查看源码"
                                  title="展开查看源码"
                                  onClick={() => setCodeViewerOpen(true)}
                                >
                                  <svg
                                    className={s.codeExpandIcon}
                                    viewBox="0 0 24 24"
                                    aria-hidden="true"
                                  >
                                    <path d="M9 4H4v5M4 4l7 7M15 20h5v-5M20 20l-7-7" />
                                  </svg>
                                </button>
                              </>
                            )}
                          </span>
                        </div>
                        <div className={s.editorCode}>
                          <Editor
                            key={selectedFile?.path || "main.py"}
                            value={selectedFileSource}
                            onChange={selectedFileIsMain ? setSource : undefined}
                            diagnostics={selectedFileIsMain ? diagnostics : []}
                            onRun={() => void action("run")}
                            readOnly={!selectedFileIsMain}
                          />
                        </div>
                      </div>
                    </>
                  ) : (
                    <div className={s.smallEmpty}>加载工作台…</div>
                  )}
                </div>
              </section>
              <div
                className={s.resizeHandle}
                role="separator"
                tabIndex={0}
                aria-label="调整编辑器宽度"
                aria-orientation="vertical"
                aria-valuenow={Math.round(split)}
                aria-valuemin={36}
                aria-valuemax={68}
                onPointerDown={resize}
                onKeyDown={(e) => {
                  if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
                    e.preventDefault();
                    setSplit((v) =>
                      Math.max(
                        36,
                        Math.min(68, v + (e.key === "ArrowLeft" ? -2 : 2)),
                      ),
                    );
                  }
                }}
              />
              <aside className={s.executionPanel}>
                <section className={s.workflow}>
                  <div className={s.panelHeader}>
                    <h2>计算步骤与目标设备</h2>
                  </div>
                  <p className={s.copyHint}>目标配置用于描述计算分工与性能预测；实际执行设备在运行结果中单独显示。</p>
                  {taskId === "h2o-hybrid-aimd" && <p className={s.copyHint}>第 2–4 步随时间步重复；求力时还会多次调用量子电路与经典模型，计算扰动构型的势能。</p>}
                  <div className={s.stages}>
                    {task?.stages.map((stage, index) => {
                          const selected = targets.find(
                              (target) => target.id === hardware[stage.id],
                            ),
                            options = targets.filter((target) =>
                              stage.allowed_devices.includes(target.kind),
                            );
                          return (
                            <div
                              key={stage.id}
                              className={`${s.stage} ${activeStage === stage.id ? s.activeStage : ""}`}
                              style={
                                {
                                  "--device-color": deviceColor(
                                    selected?.kind || stage.default_device,
                                  ),
                                } as CSSProperties
                              }
                            >
                              <div className={s.stageNumber} aria-hidden="true">
                                {String(index + 1).padStart(2, "0")}
                              </div>
                              <div className={s.stageMain}>
                                <div className={s.stageSelection}>
                                  <strong>{stageLabel(stage.id, stage.title)}</strong>
                                  {stage.fixed_device ? (
                                    <span className={s.fixedDevice}>
                                      {targetLabel(selected, "未连接计算资源")}
                                    </span>
                                  ) : (
                                    <select
                                      aria-label={`${stageLabel(stage.id, stage.title)}硬件`}
                                      value={selected?.id || ""}
                                      onChange={(e) =>
                                        setHardware((old) => ({
                                          ...old,
                                          [stage.id]: e.target.value,
                                        }))
                                      }
                                    >
                                      <option value="" disabled>
                                        选择计算设备
                                      </option>
                                      {options.map((target) => (
                                        <option
                                          key={target.id}
                                          value={target.id}
                                          disabled={!target.available}
                                        >
                                          {targetLabel(target)}
                                          {target.available
                                            ? ""
                                            : ` · ${target.status === "busy" ? "忙碌" : "不可用"}`}
                                        </option>
                                      ))}
                                    </select>
                                  )}
                                </div>
                              </div>
                            </div>
                          );
                    })}
                  </div>
                </section>
                <section className={s.circuit}>
                  <div className={s.subHeader}>
                    <h3>参数与电路预览</h3>
                  </div>
                  <p className={s.copyHint}>编译后显示解析出的应用参数和量子电路，供提交前检查；修改后需重新编译。</p>
                  <section className={s.compileParameters}>
                    {taskId === "quantum-circuit" && (
                      <div className={s.subHeader}>
                        <h3>采样设置</h3>
                      </div>
                    )}
                    {taskId === "quantum-circuit" ? (
                      <div className={s.inputGrid}>
                        {Object.entries(task?.input_schema.properties || {}).map(
                          ([key, schema]) => (
                            <label key={key}>
                              {schema.title}
                              <input
                                aria-label={schema.title}
                                type="number"
                                value={inputs[key] ?? schema.default}
                                min={schema.minimum}
                                max={schema.maximum}
                                onChange={(e) =>
                                  setInputs((old) => ({
                                    ...old,
                                    [key]:
                                      e.target.value === ""
                                        ? ""
                                        : Number(e.target.value),
                                  }))
                                }
                              />
                            </label>
                          ),
                        )}
                      </div>
                    ) : (
                      <div
                        className={`${s.parameterList} ${stale ? s.stale : ""}`}
                      >
                        {compiled ? (
                          Object.entries(
                            (compiled.plan || compiled.run?.plan)
                              ?.normalized_inputs || {},
                          )
                            .filter(([key]) =>
                              ["steps", "temperature_K", "time_step_fs"].includes(
                                key,
                              ),
                            )
                            .map(([key, value]) => (
                              <div key={key}>
                                <span>
                                  {task?.input_schema.properties[key]?.title ||
                                    key}
                                </span>
                                <strong>{String(value)}</strong>
                              </div>
                            ))
                        ) : null}
                      </div>
                    )}
                  </section>
                  <div className={s.circuitResult}>
                    <CircuitDiagram
                      circuit={compiled?.circuit}
                      stale={stale}
                      compiling={busy === "compile"}
                    />
                  </div>
                </section>
              </aside>
            </div>
            <div
              className={s.visuallyHidden}
              role={noticeError ? "alert" : "status"}
              aria-live="polite"
            >
              {notice}
            </div>
          </>
        )}
        </>
        )}
        {codeViewerOpen && selectedFile && !selectedFileIsMain && (
          <div
            className={s.codeViewerBackdrop}
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) setCodeViewerOpen(false);
            }}
            onClick={() => setCodeViewerOpen(false)}
          >
            <section
              className={s.codeViewer}
              role="dialog"
              aria-modal="true"
              aria-label={`源码查看 ${selectedFile.path}`}
              onMouseDown={(event) => event.stopPropagation()}
              onClick={(event) => event.stopPropagation()}
            >
              <header className={s.codeViewerHeader}>
                <div className={s.codeViewerTitle}>
                  <span>源码查看</span>
                  <strong title={selectedFile.path}>{selectedFile.path}</strong>
                </div>
                <button
                  type="button"
                  className={s.codeViewerClose}
                  aria-label="关闭源码查看"
                  title="关闭"
                  onClick={() => setCodeViewerOpen(false)}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M6 6l12 12M18 6L6 18" />
                  </svg>
                </button>
              </header>
              <div className={s.codeViewerBody}>
                <Editor
                  key={`viewer-${selectedFile.path}`}
                  value={selectedFileSource}
                  diagnostics={[]}
                  onRun={() => undefined}
                  readOnly
                />
              </div>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
