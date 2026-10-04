from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pivotq._internal.performance.common import ROOT
from pivotq._internal.performance.runner import PredictionRunner
from pivotq.errors import PivotQError


class QPerfSimUnavailable(RuntimeError):
    pass


class QPerfSimClient:
    """Dashboard models using the same isolated engine as pivotq.performance."""

    def __init__(self, root: str | Path | None = None) -> None:
        configured = root or os.environ.get("QPERFSIM_ROOT")
        self.root = Path(configured).expanduser() if configured else ROOT
        configured_library = os.environ.get("QPERFSIM_LIBRARY")
        candidates = [Path(configured_library).expanduser()] if configured_library else [
            self.root / relative for relative in (
                "lib/libfusion.so", "libfusion.so", "native/linux-x86_64/libfusion.so", "fusion_dist/libfusion.so")]
        self.library = next((path for path in candidates if path.is_file()), candidates[0])
        self._runner = PredictionRunner(library=self.library)

    def availability(self) -> dict[str, Any]:
        status = self._runner.probe()
        return {"version": "0.1.0", "interface": "c_api", "executable": None, **status}

    def validate(self, scenario_path: Path) -> None:
        try:
            self._runner.validate(scenario_path)
        except (PivotQError, OSError, ValueError) as error:
            raise QPerfSimUnavailable(str(error)) from error

    @staticmethod
    def prediction_reason(plan) -> str | None:
        """Report model coverage independently of the machine doing the calculation."""
        stages = {stage.id: stage for stage in plan.stages}
        quantum = stages.get("quantum_features") or stages.get("circuit_execution")
        fake = quantum and (getattr(quantum, "target_snapshot", None) or {}).get("id") == "fake-sc-36"
        if fake:
            if plan.task_id == "quantum-circuit":
                return None
            if plan.task_id == "h2o-hybrid-aimd" and stages["classical_predict"].device in {"cpu", "gpu"}:
                steps = plan.normalized_inputs.get("steps", 10)
                return None if type(steps) is int and 1 <= steps <= 1000 else "H₂O 性能预测支持 1 至 1000 步"
        if (plan.task_id == "h2o-hybrid-aimd" and quantum and quantum.device in {"gpu", "qpu"}
                and stages["classical_predict"].device == "gpu"):
            steps = plan.normalized_inputs.get("steps", 10)
            return None if type(steps) is int and 1 <= steps <= 1000 else "H₂O 性能预测支持 1 至 1000 步"
        return "所选目标暂无匹配的性能模型；可选择 Fake SC-36，单水任务也支持 GPU 量子与 GPU 经典参考路径"

    def predict(self, plan, output_dir: Path, *, preview: bool = False, program=None) -> dict[str, Any]:
        reason = self.prediction_reason(plan)
        if reason:
            raise QPerfSimUnavailable(reason)
        fake = any((getattr(stage, "target_snapshot", None) or {}).get("id") == "fake-sc-36"
                   for stage in plan.stages)
        if not fake:
            return self.predict_h2o(plan, output_dir, preview=preview)
        from .qperfsim_virtual_worker import predict
        return self._predict(predict, {"plan": plan.as_dict(), "program": program}, output_dir, preview)

    def predict_h2o(self, plan, output_dir: Path, *, preview: bool = False) -> dict[str, Any]:
        quantum = next(stage.device for stage in plan.stages if stage.id == "quantum_features")
        classical = next(stage.device for stage in plan.stages if stage.id == "classical_predict")
        if plan.task_id != "h2o-hybrid-aimd" or quantum not in {"gpu", "qpu"} or classical != "gpu":
            raise QPerfSimUnavailable("已标定的 H₂O 模板仅支持 GPU/QPU 量子路径和 GPU 经典推理")
        steps = plan.normalized_inputs.get("steps", 10)
        if type(steps) is not int or not 1 <= steps <= 1000:
            raise QPerfSimUnavailable("新版 H₂O 性能预测支持 1 至 1000 步")
        from .qperfsim_h2o_worker import predict
        return self._predict(predict, plan.as_dict(), output_dir, preview)

    def _predict(self, adapter, request, output_dir, preview):
        if not preview:
            status = self.availability()
            if not status["available"]:
                raise QPerfSimUnavailable(status["reason"])
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        request_file = output_dir / "platform_request.json"
        request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        args = SimpleNamespace(root=self.root.resolve(), request=request_file,
                               out=output_dir / "prediction", library=self.library.resolve(), preview=preview)
        try:
            result = adapter(args)
        except (PivotQError, OSError, ValueError, KeyError) as error:
            (output_dir / "adapter.log").write_text(str(error), encoding="utf-8")
            raise QPerfSimUnavailable(str(error)) from error
        (output_dir / "adapter.log").write_text("Prediction adapter completed; native logs are in prediction/.\n", encoding="utf-8")
        return result

    def run(self, scenario_path: Path, output_dir: Path, *, seed: int | None = None) -> dict[str, Any]:
        # The delivered C API takes the seed from the scenario, as before.
        try:
            return self._runner.run_raw(scenario_path, output_dir)
        except (PivotQError, OSError, ValueError) as error:
            raise QPerfSimUnavailable(str(error)) from error
