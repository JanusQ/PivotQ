from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .models import Run, WorkflowPlan


class DryRunExecutor:
    """可替换的执行器；只模拟生命周期，不宣称使用真实 GPU/QPU。"""

    def start(self, run: Run, on_update: Callable[[Run], None]) -> None:
        thread = threading.Thread(target=self._run, args=(run, on_update), daemon=True)
        thread.start()

    def cancel(self, run: Run) -> bool:
        if run.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return False
        run.status = "CANCELLED"
        run.events.append({"type": "run_cancelled"})
        return True

    def _run(self, run: Run, on_update: Callable[[Run], None]) -> None:
        run.status = "RUNNING"
        for index, stage in enumerate(run.plan.stages, start=1):
            if run.status == "CANCELLED":
                return
            run.events.append({"type": "stage_started", "stage_id": stage.id, "device": stage.device})
            run.progress = int((index - 1) / len(run.plan.stages) * 100)
            on_update(run)
            time.sleep(0.05)
            run.events.append({"type": "stage_completed", "stage_id": stage.id, "device": stage.device})
            run.progress = int(index / len(run.plan.stages) * 100)
            on_update(run)
        run.status = "SUCCEEDED"
        run.result = {
            "execution_mode": "dry_run",
            "is_demo": True,
            "message": "演示执行已完成；结果为流程联通性示例，并非真实物理计算结果。",
            "summary": {"energy_ev": -76.4312, "force_rms_ev_angstrom": 0.0184, "completed_steps": run.plan.normalized_inputs.get("steps", 10), "temperature_K": run.plan.normalized_inputs.get("temperature_K", 300.0), "time_step_fs": run.plan.normalized_inputs.get("time_step_fs", 0.1), "wall_time_s": round(len(run.plan.stages) * 0.05, 3)},
            "metrics": {"quantum_feature_latency_ms": 12.8, "classical_inference_latency_ms": 4.6, "cpu_integration_latency_ms": 1.9},
            "stage_results": [{"stage_id": stage.id, "device": stage.device, "status": "completed"} for stage in run.plan.stages],
            "artifacts": [{"name": "trajectory.xyz", "type": "trajectory", "available": False}, {"name": "metrics.json", "type": "metrics", "available": True}],
            "logs": ["DryRun executor started", "Workflow stages completed", "No real GPU/QPU submission was performed"],
        }
        on_update(run)


class RayExecutionAdapter:
    """生产接入点：将 WorkflowPlan 转换为现有 RayJobSpec。"""

    def build_job_spec(self, plan: WorkflowPlan):
        raise NotImplementedError("请在部署环境中接入现有 pivotq._internal.jobs.RayJobSpec")
