"""按 config_deployment.yaml 把项目组件注册到 pivotq._internal FusionFramework。"""

from __future__ import annotations

from copy import deepcopy
from functools import partial
import json
import os
from typing import Any, Callable, Mapping

from ...api.quantum import QuantumFeatureAPI
from ...configuration import load_config, validate_config
from .components import (
    ClassicalPredictSessionsComponent,
    QPUQuantumFeaturesComponent,
    StatevectorQuantumFeaturesComponent,
)
from .fusion_client import FusionComponentIds


AIMD_CONFIG_PATH_ENV = "AIMD_CONFIG_PATH"
AIMD_CONFIG_OVERRIDES_ENV = "AIMD_CONFIG_OVERRIDES_JSON"


def register_fusion_components(
    framework: Any,
    config: dict[str, Any],
    *,
    component_ids: FusionComponentIds | None = None,
    qpu_backend_factory: Callable[[], QuantumFeatureAPI] | None = None,
    qpu_resource_request: Any | None = None,
    register_cpu_fallback: bool = True,
) -> FusionComponentIds:
    """注册 CPU/GPU 量子 TASK、经典 GPU Actor，以及可选真实 QPU TASK。

    pivotq._internal 尚未作为本项目依赖发布，因此只在实际调用本函数时导入。
    QPU 自定义资源的字段在对方 INTERFACE.md 中未定义，由调用方传入框架原生
    ResourceRequest，避免本项目猜测资源名。
    """

    try:
        from pivotq._internal.framework import ComponentSpec, ExecutionMode
        from pivotq._internal.framework import ResourceRequest as FrameworkResourceRequest
    except ImportError as error:
        raise RuntimeError(
            "pivotq._internal is not installed. Install the fusion framework library before registration."
        ) from error

    ids = component_ids or FusionComponentIds()
    scheduling = dict(config["scheduling"])
    gpu_schedule = dict(dict(scheduling["quantum_targets"])["gpu"])
    gpu_resources = dict(gpu_schedule["resources"])
    actor_schedule = dict(scheduling["classical_actor"])
    actor_resources = dict(actor_schedule["resources"])

    if register_cpu_fallback:
        framework.register(
            ComponentSpec(
                component_id=ids.quantum_cpu,
                execution=ExecutionMode.TASK,
                resources=FrameworkResourceRequest(num_cpus=1.0),
                allowed_methods=("execute",),
                timeout_seconds=float(gpu_schedule.get("timeout_seconds", 60.0)),
            ),
            StatevectorQuantumFeaturesComponent,
        )

    framework.register(
        ComponentSpec(
            component_id=ids.quantum_gpu,
            execution=ExecutionMode.TASK,
            resources=FrameworkResourceRequest(
                num_cpus=float(gpu_resources.get("cpu", 1.0)),
                num_gpus=float(gpu_resources.get("gpu", 1.0)),
            ),
            allowed_methods=("execute",),
            timeout_seconds=float(gpu_schedule.get("timeout_seconds", 60.0)),
        ),
        StatevectorQuantumFeaturesComponent,
    )

    framework.register(
        ComponentSpec(
            component_id=ids.classical_actor,
            execution=ExecutionMode.ACTOR,
            resources=FrameworkResourceRequest(
                num_cpus=float(actor_resources.get("cpu", 0.25)),
                num_gpus=float(actor_resources.get("gpu", 1.0)),
            ),
            allowed_methods=("create", "call", "terminate"),
            timeout_seconds=float(actor_schedule.get("startup_timeout_seconds", 300.0)),
            stateful=True,
            max_concurrency=1,
        ),
        ClassicalPredictSessionsComponent,
    )

    if qpu_backend_factory is not None:
        if qpu_resource_request is None:
            raise ValueError(
                "qpu_resource_request is required because INTERFACE.md does not define custom QPU syntax."
            )
        qpu_schedule = dict(dict(scheduling["quantum_targets"])["qpu"])
        framework.register(
            ComponentSpec(
                component_id=ids.quantum_qpu,
                execution=ExecutionMode.TASK,
                resources=qpu_resource_request,
                allowed_methods=("execute",),
                timeout_seconds=float(qpu_schedule.get("timeout_seconds", 3600.0)),
            ),
            partial(QPUQuantumFeaturesComponent, qpu_backend_factory),
        )

    return ids


def register_components(framework: Any) -> None:
    """Ray Job Driver entrypoint with the exact public framework signature."""

    register_fusion_components(framework, _load_job_config_from_environment())
    if os.environ.get("AIMD_QUANTUM_TARGET", "gpu") == "qpu":
        try:
            from pivotq._internal.qpu_integration.registration import (
                register_components as register_qpu_components,
            )
        except ImportError as error:
            raise RuntimeError(
                "quantum_target='qpu' 需要融合框架提供 qpu_integration 注册入口。"
            ) from error
        # Driver 只接受一个 registration target，因此应用注册入口组合调用框架官方
        # QPU 注册函数；runner 本身仍不注册或关闭 qpu-circuits Actor。
        register_qpu_components(framework)


def _load_job_config_from_environment() -> dict[str, Any]:
    config_path = os.environ.get(AIMD_CONFIG_PATH_ENV)
    if not config_path:
        raise RuntimeError(
            f"{AIMD_CONFIG_PATH_ENV} is required for fusion component registration."
        )
    config = load_config(config_path)
    overrides_text = os.environ.get(AIMD_CONFIG_OVERRIDES_ENV, "").strip()
    if overrides_text:
        overrides = json.loads(overrides_text)
        if not isinstance(overrides, Mapping):
            raise ValueError(f"{AIMD_CONFIG_OVERRIDES_ENV} must contain a JSON object.")
        _merge_mapping(config, overrides)
        validate_config(config)
    return config


def _merge_mapping(target: dict[str, Any], overrides: Mapping[str, Any]) -> None:
    for key, value in overrides.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _merge_mapping(target[key], value)
        else:
            target[key] = deepcopy(value)


__all__ = [
    "AIMD_CONFIG_OVERRIDES_ENV",
    "AIMD_CONFIG_PATH_ENV",
    "register_components",
    "register_fusion_components",
]
