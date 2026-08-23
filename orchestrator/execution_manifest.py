"""Immutable request execution manifest and process-start host snapshot."""

from __future__ import annotations

import os
import platform
from copy import deepcopy
from pathlib import Path
from typing import Mapping

from pydantic import ConfigDict, Field

from core.base import CalienneBaseModel
from orchestrator.feature_flags import FeatureFlags

MANIFEST_SCHEMA_VERSION = "1.0"


class HostPrimitives(CalienneBaseModel):
    """Host details needed to diagnose replay differences."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    os: str
    os_version: str | None = None
    python_version: str | None = None
    python_implementation: str | None = None
    cuda_version: str | None = None
    platform_machine: str | None = None
    container: bool = False
    container_runtime: str | None = None


def _capture_cuda_version() -> str | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        return getattr(torch.version, "cuda", None)
    except (ImportError, OSError, RuntimeError):
        return None


def _capture_container() -> tuple[bool, str | None]:
    environment = os.environ
    if environment.get("KUBERNETES_SERVICE_HOST"):
        return True, "kubernetes"
    if environment.get("container"):
        return True, str(environment["container"])
    if Path("/.dockerenv").exists():
        return True, "docker"
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8").lower()
    except OSError:
        return False, None
    for runtime in ("docker", "containerd", "podman", "kubepods"):
        if runtime in cgroup:
            return True, "kubernetes" if runtime == "kubepods" else runtime
    return False, None


def capture_host_primitives() -> HostPrimitives:
    container, runtime = _capture_container()
    return HostPrimitives(
        os=platform.system() or "unknown",
        os_version=platform.version() or None,
        python_version=platform.python_version() or None,
        python_implementation=platform.python_implementation() or None,
        cuda_version=_capture_cuda_version(),
        platform_machine=platform.machine() or None,
        container=container,
        container_runtime=runtime,
    )


host_primitives = capture_host_primitives()


class ExecutionManifest(CalienneBaseModel):
    """Frozen critical contract tying one request to its runtime versions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_schema_version: str = MANIFEST_SCHEMA_VERSION
    architecture_version: str
    planner_version: str | None = None
    scheduler_version: str | None = None
    routing_version: str | None = None
    capabilities_version: str | None = None
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    feature_flags: dict[str, bool]
    git_commit: str
    host: HostPrimitives


def build_execution_manifest(
    *,
    flags: FeatureFlags,
    planner_version: str | None = None,
    scheduler_version: str | None = "scheduler-v1",
    routing_version: str | None = "routing-v1",
    capabilities_version: str | None = "1",
    prompt_versions: Mapping[str, str] | None = None,
) -> ExecutionManifest:
    from orchestrator.versioning import architecture_version, git_commit

    return ExecutionManifest(
        architecture_version=architecture_version,
        planner_version=planner_version,
        scheduler_version=scheduler_version,
        routing_version=routing_version,
        capabilities_version=capabilities_version,
        prompt_versions=deepcopy(dict(prompt_versions or {})),
        feature_flags=flags.as_env_map(),
        git_commit=git_commit,
        host=host_primitives,
    )
