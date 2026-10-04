"""Register the server-side QPU client without opening a network connection."""

from __future__ import annotations

import json
import os

from pivotq._internal.framework import FusionFramework
from .component import register_qpu_client


def register_components(framework: FusionFramework) -> None:
    component_id = os.environ.get("QPU_COMPONENT_ID", "qpu-circuits")
    text = os.environ.get("QPU_CUSTOM_RESOURCES_JSON", "").strip()
    custom_resources = json.loads(text) if text else {}
    if not isinstance(custom_resources, dict):
        raise ValueError("QPU_CUSTOM_RESOURCES_JSON must be a JSON object")
    register_qpu_client(
        framework,
        component_id=component_id,
        custom_resources={str(key): float(value) for key, value in custom_resources.items()},
    )


__all__ = ["register_components"]
