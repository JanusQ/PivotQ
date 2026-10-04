from __future__ import annotations

from typing import Any
import math

from ..models import StageDefinition, StagePlan, TaskDefinition, WorkflowPlan
from ..stage_hardware import stage_policy


H2O_STAGES = (
    StageDefinition(
        id="initialization",
        title="初始化与轨迹控制",
        description="准备分子结构并控制 AIMD 时间步循环。",
        default_device="cpu",
        allowed_devices=("cpu",),
        fixed_device=True,
    ),
    StageDefinition(
        id="quantum_features",
        title="量子特征计算",
        description="计算量子特征，可选择 GPU 模拟器或 QPU Provider。",
        default_device="gpu",
        allowed_devices=("gpu", "qpu", "qpu_simulator"),
        depends_on=("initialization",),
    ),
    StageDefinition(
        id="classical_predict",
        title="经典能量预测",
        description="使用经典模型预测能量。",
        default_device="gpu",
        allowed_devices=("cpu", "gpu"),
        depends_on=("quantum_features",),
    ),
    StageDefinition(
        id="force_and_integration",
        title="求力与轨迹积分",
        description="根据能量评估求力并推进下一时间步。",
        default_device="cpu",
        allowed_devices=("cpu",),
        depends_on=("classical_predict",),
        fixed_device=True,
    ),
    StageDefinition(
        id="trajectory_analysis",
        title="轨迹分析",
        description="汇总能量、力和轨迹结果。",
        default_device="cpu",
        allowed_devices=("cpu", "gpu"),
        depends_on=("force_and_integration",),
    ),
)


TASK = TaskDefinition(
    id="h2o-hybrid-aimd",
    version="1.0",
    title="H₂O 量子—经典混合 AIMD",
    description="首个可配置硬件的混合程序示例。",
    input_schema={
        "type": "object",
        "required": ["steps", "temperature_K", "time_step_fs"],
        "properties": {
            "steps": {"type": "integer", "title": "时间步数", "minimum": 1, "maximum": 100000, "default": 10},
            "temperature_K": {"type": "number", "title": "温度 (K)", "minimum": 0.0, "default": 300.0},
            "time_step_fs": {"type": "number", "title": "时间步长 (fs)", "exclusiveMinimum": 0.0, "default": 0.1},
            "checkpoint_id": {"type": "string", "title": "模型 checkpoint", "default": "hybrid_model.pt"},
            "seed": {"type": "integer", "title": "随机种子", "default": 20260919, "minimum": 0, "maximum": 4294967295},
        },
    },
    stages=H2O_STAGES,
)


def task_definition() -> TaskDefinition:
    return TASK


def _resources(device: str) -> dict[str, Any]:
    if device == "gpu":
        return {"gpu": 1}
    if device in {"qpu", "qpu_simulator"}:
        return {"qpu": 1}
    return {"cpu": 1}


def build_plan(request: dict[str, Any], *, prediction=False) -> WorkflowPlan:
    inputs = dict(request.get("inputs") or {})
    normalized: dict[str, Any] = {}
    for name, definition in TASK.input_schema["properties"].items():
        value = inputs.get(name, definition.get("default"))
        if value is not None:
            normalized[name] = value

    hardware = dict(request.get("hardware") or {})
    hardware_targets = dict(request.get("hardware_targets") or {})
    plans: list[StagePlan] = []
    for stage in H2O_STAGES:
        device = hardware.get(stage.id, stage_policy(stage, prediction=prediction)[0])
        plans.append(StagePlan(
            stage.id,
            stage.title,
            device,
            stage.depends_on,
            _resources(device),
            hardware_targets.get(stage.id),
            request.get('target_snapshots', {}).get(stage.id),
        ))
    return WorkflowPlan(TASK.id, TASK.version, normalized, tuple(plans))


def validate(request: dict[str, Any], *, prediction=False) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    inputs = request.get("inputs") or {}
    if set(inputs) - set(TASK.input_schema['properties']):
        errors.append({'path':'inputs','message':'存在未知参数'})
    for name, definition in TASK.input_schema["properties"].items():
        value = inputs.get(name, definition.get("default"))
        if name in TASK.input_schema["required"] and value is None:
            errors.append({"path": f"inputs.{name}", "message": "该字段为必填项"})
            continue
        if value is None:
            continue
        if definition['type'] == 'string' and (not isinstance(value,str) or not value or '/' in value or '\\' in value or value in ('.','..')):
            errors.append({'path':f'inputs.{name}','message':'必须是有效的模型文件名'})
        if isinstance(value,(int,float)) and (not math.isfinite(value) or ('maximum' in definition and value > definition['maximum'])):
            errors.append({'path':f'inputs.{name}','message':'数值必须有限且不超过上限'})
        if definition["type"] == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            errors.append({"path": f"inputs.{name}", "message": "必须是整数"})
        if definition["type"] == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
            errors.append({"path": f"inputs.{name}", "message": "必须是数字"})
        if "minimum" in definition and isinstance(value, (int, float)) and value < definition["minimum"]:
            errors.append({"path": f"inputs.{name}", "message": f"不能小于 {definition['minimum']}"})
        if "exclusiveMinimum" in definition and isinstance(value, (int, float)) and value <= definition["exclusiveMinimum"]:
            errors.append({"path": f"inputs.{name}", "message": f"必须大于 {definition['exclusiveMinimum']}"})

    hardware = dict(request.get("hardware") or {})
    if set(hardware) - {stage.id for stage in H2O_STAGES}:
        errors.append({'path': 'hardware', 'message': '存在未知执行阶段'})
    for stage in H2O_STAGES:
        default, allowed = stage_policy(stage, prediction=prediction)
        device = hardware.get(stage.id, default)
        if device not in allowed:
            errors.append({"path": f"hardware.{stage.id}", "message": f"{device} 不支持；可选值: {', '.join(allowed)}"})
        if stage.fixed_device and device != stage.default_device:
            errors.append({"path": f"hardware.{stage.id}", "message": f"该阶段当前固定使用 {stage.default_device}"})
    return errors


__all__ = ["TASK", "H2O_STAGES", "build_plan", "task_definition", "validate"]
