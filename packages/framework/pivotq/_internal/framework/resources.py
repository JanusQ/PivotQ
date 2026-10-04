"""Pure translation from framework resources to Ray public API options."""

from __future__ import annotations

from typing import TypeAlias

from .models import ResourceRequest


RayResourceOptions: TypeAlias = dict[str, float | dict[str, float]]


def resource_request_to_ray_options(
    request: ResourceRequest,
) -> RayResourceOptions:
    """Return a fresh options mapping accepted by Ray Task/Actor ``options``.

    This function intentionally does not import Ray.  Keeping the translation
    pure lets resource semantics be validated in ordinary unit tests without
    starting or installing a Ray runtime.
    """

    if not isinstance(request, ResourceRequest):
        raise TypeError("request must be a ResourceRequest")

    options: RayResourceOptions = {
        "num_cpus": request.num_cpus,
        "num_gpus": request.num_gpus,
    }
    custom_resources = request.custom_resources_dict()
    if custom_resources:
        options["resources"] = custom_resources
    return options


__all__ = [
    "RayResourceOptions",
    "resource_request_to_ray_options",
]
