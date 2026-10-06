import { phaseNames } from "../api/labels";
import { lazy, Suspense, useEffect, useState } from "react";
import { api, duration, terminal, statusLabel } from "../api/client";
import { actualDevice } from "../api/hardware";
import type { Frame, Prediction, Run, Series, Trajectory } from "../api/types";
import { EnergyChart, Probabilities } from "./Charts";
import TargetAssignments from "./TargetAssignments";
import s from "../App.module.css";
const Molecule = lazy(() => import("./Molecule"));
const scientific = (value: unknown) =>
  value === "passed"
    ? "通过"
    : value === "failed" || value === "failed_validation"
      ? "未通过"
      : value === "not_available" || !value
        ? "未提供"
        : String(value);
export default function Results({
  run,
  series,
  syncError,
  prediction,
  tab,
  onTab,
  onCancel,
  cancelling,
}: {
  run: Run | null;
  series: Series;
  syncError: string;
  prediction: Prediction | null;
  tab: string;
  onTab: (tab: string) => void;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const [trajectory, setTrajectory] = useState<Trajectory | null>(null),
    [trajectoryError, setTrajectoryError] = useState(""),
    [loadingFrames, setLoadingFrames] = useState(false),
    [frameIndex, setFrameIndex] = useState(0),
    [retry, setRetry] = useState(0);
  const finished = run ? terminal(run.status) : false;
  useEffect(() => {
    setTrajectory(null);
    setFrameIndex(0);
    setTrajectoryError("");
    setLoadingFrames(false);
    if (!run || !terminal(run.status) || run.task_id !== "h2o-hybrid-aimd")
      return;
    const controller = new AbortController();
    let disposed = false;
    setLoadingFrames(true);
    async function load() {
      let next = 0;
      let frames: Frame[] = [];
      let total = 0;
      do {
        const page = await api<Trajectory>(
          `/runs/${encodeURIComponent(run!.id)}/trajectory?start=${next}&limit=500`,
          undefined,
          controller.signal,
        );
        if (disposed) return;
        frames = [...frames, ...page.frames];
        total = page.total;
        setTrajectory({ ...page, frames });
        next += page.frames.length;
        if (!page.frames.length) break;
      } while (next < total);
    }
    void load()
      .catch((e) => {
        if (!disposed)
          setTrajectoryError(e instanceof Error ? e.message : "轨迹读取失败");
      })
      .finally(() => {
        if (!disposed) setLoadingFrames(false);
      });
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [run?.id, finished, retry]);
  const result = run?.result,
    progressEvent = [...(run?.events || [])]
      .reverse()
      .find((e) => e.type === "progress"),
    completed =
      progressEvent?.completed_steps ?? result?.summary?.completed_steps,
    total = progressEvent?.total_steps ?? run?.plan.normalized_inputs.steps,
    metrics = result?.metrics || {},
    summary = result?.summary || {},
    elapsed =
      metrics.compute_seconds ??
      metrics.aimd_elapsed_seconds ??
      metrics.gpu_seconds ??
      metrics.worker_elapsed_seconds ??
      summary.compute_seconds ??
      summary.aimd_elapsed_seconds,
    actual = actualDevice(result),
    mode = result?.execution_mode || "",
    demo = mode === "dry_run" || mode === "demo";
  const predictionData = prediction?.result?.prediction;
  return (
    <section className={s.resultPanel} aria-label="所选运行的详情">
      <div className={s.resultHeader}>
        <div className={s.resultIdentity}>
          <h3>运行状态</h3>
          {run ? (
            <>
              <span
                className={`${s.status} ${run.status === "FAILED" ? s.failed : run.status === "SUCCEEDED" ? s.success : ""}`}
              >
                {statusLabel(run.status)}
              </span>
              <code>{run.id}</code>
              {demo && <span className={s.incomplete}>演示结果</span>}
            </>
          ) : (
            <span className={s.muted}>尚未运行</span>
          )}
        </div>
        {run && !finished && (
          <button onClick={onCancel} disabled={cancelling}>
            {cancelling ? "正在取消…" : "取消运行"}
          </button>
        )}
      </div>
      {syncError && (
        <p role="status" className={s.syncError}>
          {syncError} · 自动重试中
        </p>
      )}
      {run && !finished && (
        <div className={s.liveProgress}>
          <div>
            <span>{progressEvent?.phase || statusLabel(run.status)}</span>
            <span>
              {typeof completed === "number" && total
                ? `${completed} / ${total} 步`
                : `${run.progress || 0}%`}
            </span>
          </div>
          <progress max="100" value={run.progress || 0} />
        </div>
      )}
      <div className={s.tabs} role="tablist" aria-label="结果视图">
        {[
          ["result", "计算输出"],
          ["performance", "耗时预测"],
          ["logs", "执行日志"],
          ["files", "输出文件"],
        ].map(([key, label]) => (
          <button
            key={key}
            role="tab"
            id={`tab-${key}`}
            aria-selected={tab === key}
            aria-controls={`panel-${key}`}
            onClick={() => onTab(key)}
            className={tab === key ? s.activeTab : ""}
          >
            {label}
            {key === "files" && !!result?.artifacts?.length && (
              <small>{result.artifacts.length}</small>
            )}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id={`panel-${tab}`}
        aria-labelledby={`tab-${tab}`}
        className={s.resultContent}
      >
        {tab === "result" && (
          <>
            {run && (
              <div className={s.metricStrip}>
                <div>
                  <span>实际执行</span>
                  <strong>
                    {demo
                      ? "演示"
                      : actual.toLowerCase() === "cpu" && mode === "local_cpu"
                        ? "CPU 数值模拟"
                        : actual.toUpperCase() || "待执行记录确认"}
                  </strong>
                </div>
                <div>
                  <span>
                    {actual.toLowerCase() === "cpu"
                      ? "CPU 实测用时"
                      : "实测计算耗时"}
                  </span>
                  <strong>{duration(elapsed)}</strong>
                </div>
                <div>
                  <span>
                    {run.task_id === "quantum-circuit"
                      ? "采样次数"
                      : "完成时间步"}
                  </span>
                  <strong>
                    {run.task_id === "quantum-circuit"
                      ? String(run.plan.normalized_inputs.shots)
                      : typeof completed === "number"
                        ? `${completed} / ${total}`
                        : "—"}
                  </strong>
                </div>
                <div>
                  <span>计算检查</span>
                  <strong>
                    {scientific(
                      result?.scientific_status ??
                        summary.scientific_status ??
                        summary["科学验收"],
                    )}
                  </strong>
                </div>
              </div>
            )}
            {run && <details className={s.snapshot}>
              <summary>计算检查项目与判定标准</summary>
              <p>检查针对本次轨迹与数值稳定性；通过不等于已经验证科学精度。阈值按本次保存的配置或实现中的固定检查标准展示；缺失的历史阈值不会补写。</p>
              {result?.calculation_checks?.length ? <ul>{result.calculation_checks.map(check => <li key={check.id}>
                <strong>{check.label}：{check.passed ? "通过" : "未通过"}</strong> — {check.criterion}
                {check.observed && <span>；记录值：{check.observed}</span>}
              </li>)}</ul> : <p>此记录未提供检查明细，不能单凭摘要中的状态判断精度。请在输出文件中核对 metrics.json、run_summary.json 及原始运行配置。</p>}
            </details>}
            {run && <TargetAssignments plan={run.plan} result={result} />}
            {result?.probabilities ? (
              <Probabilities
                values={result.probabilities}
                counts={result.counts}
              />
            ) : run?.task_id === "quantum-circuit" ? (
              <div className={s.emptyResult}>
                <span className={s.emptyGlyph}>ψ</span>
                <h3>{finished ? "未生成测量结果" : "等待电路执行"}</h3>
                <p>
                  {finished ? "查看日志了解执行详情" : "结果会自动显示在这里"}
                </p>
              </div>
            ) : (
              <div className={s.scienceGrid}>
                {trajectory?.frames.length ? (
                  <Suspense
                    fallback={<div className={s.smallEmpty}>加载三维视图…</div>}
                  >
                    <Molecule
                      frames={trajectory.frames}
                      symbols={trajectory.symbols}
                      index={frameIndex}
                      onIndex={setFrameIndex}
                      complete={trajectory.complete}
                    />
                  </Suspense>
                ) : (
                  <div className={s.trajectoryPlaceholder}>
                    <svg viewBox="0 0 190 130" aria-hidden="true">
                      <path
                        d="M94 50L44 94M94 50L150 94"
                        stroke="#C6D3E7"
                        strokeWidth="8"
                        strokeLinecap="round"
                      />
                      <circle
                        cx="94"
                        cy="50"
                        r="24"
                        fill="#F3D9DE"
                        stroke="#E1B8C0"
                      />
                      <circle
                        cx="44"
                        cy="94"
                        r="17"
                        fill="#F7F9FC"
                        stroke="#CDD8E7"
                      />
                      <circle
                        cx="150"
                        cy="94"
                        r="17"
                        fill="#F7F9FC"
                        stroke="#CDD8E7"
                      />
                    </svg>
                    <h3>
                      {loadingFrames
                        ? "读取轨迹…"
                        : trajectoryError
                          ? "轨迹读取失败"
                          : finished
                            ? "无可用轨迹"
                            : "水分子轨迹"}
                    </h3>
                    <p>
                      {trajectoryError ||
                        (finished
                          ? "查看日志与输出文件"
                          : "运行结束后可播放三维轨迹")}
                    </p>
                    {trajectoryError && (
                      <button onClick={() => setRetry((n) => n + 1)}>
                        重试
                      </button>
                    )}
                  </div>
                )}
                <div className={s.energyRegion}>
                  <EnergyChart
                    points={series.items}
                    time={trajectory?.frames[frameIndex]?.time_fs}
                    onTime={
                      trajectory?.frames.length
                        ? (time) => {
                            const nearest = trajectory.frames.reduce(
                              (best, frame, i) =>
                                Math.abs(frame.time_fs - time) <
                                Math.abs(trajectory.frames[best].time_fs - time)
                                  ? i
                                  : best,
                              0,
                            );
                            setFrameIndex(nearest);
                          }
                        : undefined
                    }
                  />
                  <div className={s.energyFooter}>
                    <span>坐标 Å / 时间 fs / 能量 eV</span>
                    {loadingFrames && (
                      <span>已读取 {trajectory?.frames.length ?? 0} 帧</span>
                    )}
                  </div>
                </div>
              </div>
            )}
            {run?.request?.program && (
              <details className={s.snapshot}>
                <summary>
                  程序快照{" "}
                  <code>{run.request.program.source_sha256?.slice(0, 12)}</code>
                </summary>
                <pre>{run.request.program.source}</pre>
                <div className={s.snapshotParams}>
                  {Object.entries(run.plan.normalized_inputs).map(
                    ([name, value]) => (
                      <span key={name}>
                        {name} = {value}
                      </span>
                    ),
                  )}
                </div>
              </details>
            )}
          </>
        )}
        {tab === "performance" &&
          (predictionData ? (
            <div className={s.prediction}>
              <div className={s.predictionHead}>
                <div>
                  <span>目标硬件预测耗时</span>
                  <strong>{duration(predictionData.latency_seconds)}</strong>
                </div>
                <p>
                  {prediction?.plan.stages.some(
                    (stage) => stage.target_snapshot?.id === "fake-sc-36",
                  )
                    ? "QPerfSim · 示例参数估算"
                    : "QPerfSim 参考硬件预测"}
                  <br />
                  与本次实测分开记录
                </p>
              </div>
              {prediction && <TargetAssignments plan={prediction.plan} />}
              {Object.entries(
                predictionData.stage_seconds ||
                  predictionData.phase_seconds ||
                  {},
              ).map(([stage, seconds]) => (
                <div key={stage} className={s.predictionRow}>
                  <span>{phaseNames[stage] || stage.replaceAll("_", " ")}</span>
                  <div>
                    <i
                      style={{
                        width: `${Math.min(100, (seconds / (predictionData.latency_seconds || 1)) * 100)}%`,
                      }}
                    />
                  </div>
                  <strong>{duration(seconds)}</strong>
                </div>
              ))}
              <details>
                <summary>估算条件与适用范围</summary>
                {[
                  ...new Set([
                    ...(prediction?.model_scope?.notes || []),
                    ...(prediction?.request?.scope_notes || []),
                  ]),
                ].map((note, i) => (
                  <p key={i}>{note}</p>
                ))}
                <p>{prediction?.request?.validation_scope}</p>
                <p>不包含外部平台排队时间。</p>
              </details>
            </div>
          ) : (
            <div className={s.emptyResult}>
              <span className={s.emptyGlyph}>t</span>
              <h3>暂无性能预测</h3>
              <p>使用当前阶段的目标硬件配置，独立估算执行耗时</p>
            </div>
          ))}
        {tab === "logs" && (
          <div className={s.logPanel}>
            <details>
              <summary>执行日志</summary>
              <pre>
                {result?.logs?.join("\n") ||
                  run?.events
                    .filter((e) => e.message || e.phase)
                    .map((e) => e.message || e.phase)
                    .join("\n") ||
                  "暂无运行日志"}
              </pre>
            </details>
          </div>
        )}
        {tab === "files" && (
          <div className={s.fileList}>
            {result?.artifacts?.length ? (
              result.artifacts.map((artifact, i) => {
                const id = artifact.id || artifact.artifact_id;
                return (
                  <div key={id || i}>
                    <span className={s.fileIcon}>↳</span>
                    <div>
                      <strong>{artifact.name}</strong>
                      <span>{artifact.type || "输出文件"}</span>
                    </div>
                    {artifact.available && id ? (
                      <a
                        download
                        href={
                          artifact.download_url ||
                          `/api/v1/runs/${encodeURIComponent(run!.id)}/artifacts/${encodeURIComponent(id)}`
                        }
                      >
                        下载
                      </a>
                    ) : (
                      <span className={s.muted}>未生成</span>
                    )}
                  </div>
                );
              })
            ) : (
              <div className={s.smallEmpty}>计算生成的文件会显示在这里</div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
