import { phaseNames, forecastShare, stageLabel, targetLabel } from "../api/labels";
import { duration } from "../api/client";
import type { CSSProperties } from "react";
import type { Prediction } from "../api/types";
import TargetAssignments from "../components/TargetAssignments";
import s from "./Pages.module.css";


export default function PerformancePage({ prediction }: { prediction: Prediction | null }) {
  const value = prediction?.result?.prediction;
  const stages = Object.entries(value?.stage_seconds || value?.phase_seconds || {});
  const total = value?.latency_seconds || 0;
  const resources = prediction?.plan.stages || [];

  return (
    <div className={s.page}>
      <header className={s.hero}>
        <p className={s.eyebrow}>PERFORMANCE FORECAST</p>
        <h1>性能预测</h1>
        <p>以下估算使用本次性能预测保存的任务参数和目标设备配置。总耗时和各项耗时均为模型预测值。</p>
      </header>
      {!prediction || !value ? (
        <section className={`${s.card} ${s.empty}`}>
          <h2>暂无性能预测</h2>
          <p>返回工作台，选择硬件后点击“性能预测”。</p>
          <a className={s.button} href="/">返回工作台</a>
        </section>
      ) : (
        <>
          <section className={s.overview} aria-label="预测摘要">
            <div className={`${s.card} ${s.stat}`}><span>预计总耗时</span><strong>{duration(total)}</strong></div>
            <div className={`${s.card} ${s.stat}`}><span>耗时分类</span><strong>{stages.length} 项</strong></div>
            <div className={`${s.card} ${s.stat}`}><span>主要瓶颈</span><strong>{value.main_bottleneck ? phaseNames[value.main_bottleneck] || value.main_bottleneck : "—"}</strong></div>
            <div className={`${s.card} ${s.stat}`}><span>预测工具</span><strong>QPerfSim 性能模拟器</strong></div>
          </section>
          <section className={`${s.card} ${s.section}`}>
            <div className={s.sectionHeader}><h2>各环节累计预计耗时</h2><span className={s.muted}>总计 {duration(total)}</span></div>
            <p className={s.muted}>同名环节可能在多个时间步或预检查中重复，卡片显示累计值。计算步骤及依赖请回到工作台查看；主要瓶颈表示关键路径中主导总耗时的处理环节。</p>
            <div className={s.pipeline}>
              {stages.map(([name, seconds]) => {
                const amount = typeof seconds === "number" ? seconds : Number(seconds);
                return <div key={name} className={s.stage} style={{ "--stage-progress": `${Math.min(1, amount / (total || 1))}` } as CSSProperties}>
                  <span>{phaseNames[name] || name.replaceAll("_", " ")}</span>
                  <strong>{duration(amount)}</strong>
                  <small title={`累计 ${amount} s；预计总耗时 ${total} s`}>{forecastShare(amount, total)}</small>
                </div>;
              })}
            </div>
          </section>
          <section className={s.twoColumns}>
            <div className={`${s.card} ${s.section}`}>
              <div className={s.sectionHeader}><h2>本次预测的设备配置</h2></div>
              <div className={s.resourceList}>
                {resources.map((stage) => <div key={stage.id} className={s.resource}><div><strong>{stageLabel(stage.id, stage.title)}</strong></div><span>{targetLabel(stage.target_snapshot, stage.target_id || stage.device)}</span></div>)}
              </div>
              <details><summary>技术信息</summary><p>应用标识：{prediction.plan.task_id}</p>{resources.map(stage => <p key={stage.id}>{stageLabel(stage.id, stage.title)}：<code>{stage.id}</code></p>)}</details>
              <TargetAssignments plan={prediction.plan} />
            </div>
            <div className={`${s.card} ${s.section}`}>
              <div className={s.sectionHeader}><h2>估算条件与适用范围</h2></div>
              {[...(prediction.model_scope?.notes || []), ...(prediction.request?.scope_notes || []), prediction.request?.validation_scope || "不包含外部平台排队时间。"].filter(Boolean).map((note, index) => <p key={index} className={s.muted} style={{ marginBottom: 10 }}>{note}</p>)}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
