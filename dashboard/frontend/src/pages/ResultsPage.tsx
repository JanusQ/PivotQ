import { useState } from "react";
import type { Prediction, Run, Series } from "../api/types";
import { statusLabel } from "../api/client";
import Results from "../components/Results";
import s from "./Pages.module.css";

export default function ResultsPage({
  runs,
  run,
  runId,
  series,
  syncError,
  prediction,
  onSelect,
  onDelete,
  onCancel,
  cancelling,
}: {
  runs: Run[];
  run: Run | null;
  runId: string | null;
  series: Series;
  syncError: string;
  prediction: Prediction | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => Promise<void>;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const [tab, setTab] = useState("result");
  const [pendingDelete, setPendingDelete] = useState<Run | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const confirmDelete = async () => {
    if (!pendingDelete || deleteBusy) return;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await onDelete(pendingDelete.id);
      setPendingDelete(null);
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "删除失败，请稍后重试");
    } finally {
      setDeleteBusy(false);
    }
  };
  return (
    <div className={s.page}>
      <header className={s.hero}>
        <p className={s.eyebrow}>RESULTS · RUN HISTORY</p>
        <h1>运行记录与结果</h1>
        <p>选择一次运行，查看执行状态、实际设备、完成步数、计算结果和输出文件。</p>
      </header>
      <div className={s.resultsLayout}>
        <aside className={`${s.card} ${s.history}`}>
          <h2>运行记录</h2>
          <p className={s.historyHint}>按最近提交时间排列，运行中的任务会自动更新。</p>
          <div className={s.runs}>
            {runs.length ? runs.map((item) => {
              const removable = ["SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"].includes(item.status);
              return (
                <div key={item.id} className={`${s.run} ${runId === item.id ? s.runSelected : ""}`}>
                  <button className={s.runSelect} onClick={() => onSelect(item.id)}>
                    <span className={s.runTop}><strong>{item.task_id === "quantum-circuit" ? "量子电路" : "水分子动力学模拟（H₂O AIMD）"}</strong><span>{statusLabel(item.status)}</span></span>
                    <code>{item.id}</code>
                    <progress max={100} value={item.progress || 0} />
                  </button>
                  <button
                    type="button"
                    className={s.runDelete}
                    aria-label={`删除任务记录 ${item.id}`}
                    title={removable ? "删除任务记录" : "运行中的任务请先取消"}
                    disabled={!removable}
                    onClick={() => {
                      setDeleteError("");
                      setPendingDelete(item);
                    }}
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" />
                    </svg>
                  </button>
                </div>
              );
            }) : <p className={s.muted}>还没有运行记录。</p>}
          </div>
        </aside>
        <section className={`${s.card} ${s.result}`}>
          <div className={s.resultHeader}><div><h2>所选运行的详情</h2><p>{run ? `运行 ${run.id}` : "选择左侧任务查看详情"}</p></div>{run && <span className={s.muted}>{statusLabel(run.status)}</span>}</div>
          <div className={s.resultBody}>
            <Results run={run} series={series} syncError={syncError} prediction={prediction} tab={tab} onTab={setTab} onCancel={onCancel} cancelling={cancelling} />
          </div>
        </section>
      </div>
      {pendingDelete && (
        <div className={s.deleteBackdrop} onClick={() => !deleteBusy && setPendingDelete(null)}>
          <section
            className={s.deleteDialog}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-run-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className={s.deleteDialogIcon} aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" />
              </svg>
            </div>
            <div className={s.deleteDialogCopy}>
              <h2 id="delete-run-title">删除任务记录？</h2>
              <p>将删除这条 {pendingDelete.task_id === "quantum-circuit" ? "量子电路" : "水分子动力学模拟（H₂O AIMD）"} 记录及其结果入口。此操作不可恢复。</p>
              <code>{pendingDelete.id}</code>
              {deleteError && <div className={s.deleteError}>{deleteError}</div>}
            </div>
            <div className={s.deleteDialogActions}>
              <button type="button" className={s.deleteCancel} disabled={deleteBusy} onClick={() => setPendingDelete(null)}>取消</button>
              <button type="button" className={s.deleteConfirm} disabled={deleteBusy} onClick={() => void confirmDelete()}>
                {deleteBusy ? "删除中…" : "删除记录"}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
