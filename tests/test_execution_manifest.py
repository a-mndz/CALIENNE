from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.execution_manifest import (
    MANIFEST_SCHEMA_VERSION,
    ExecutionManifest,
    build_execution_manifest,
    capture_host_primitives,
    host_primitives,
)
from orchestrator.feature_flags import FeatureFlags
from orchestrator.versioning import architecture_version, git_commit


def test_manifest_is_frozen_and_forbids_extra_fields() -> None:
    manifest = build_execution_manifest(flags=FeatureFlags(dag=True))

    with pytest.raises(ValidationError):
        manifest.architecture_version = "9.9.9"

    with pytest.raises(ValidationError):
        ExecutionManifest.model_validate(
            {**manifest.model_dump(), "unexpected": True}
        )


def test_manifest_snapshots_every_feature_flag_explicitly() -> None:
    flags = FeatureFlags(dag=True, planner=True, repair=True)
    manifest = build_execution_manifest(
        flags=flags,
        planner_version="execution-planner-v1",
        prompt_versions={"coder": "7"},
    )

    assert manifest.manifest_schema_version == MANIFEST_SCHEMA_VERSION == "1.0"
    assert manifest.manifest_schema_version != architecture_version
    assert manifest.architecture_version == architecture_version
    assert manifest.git_commit == git_commit
    assert manifest.feature_flags == flags.as_env_map()
    assert set(manifest.feature_flags) == set(FeatureFlags().as_env_map())
    assert manifest.feature_flags["CALIENNE_ENABLE_DAG"] is True
    assert manifest.feature_flags["CALIENNE_ENABLE_RAG"] is False
    assert manifest.prompt_versions == {"coder": "7"}


def test_host_primitives_are_captured_once_and_cuda_absence_is_none(monkeypatch) -> None:
    assert host_primitives is host_primitives
    assert host_primitives.os
    assert isinstance(host_primitives.container, bool)

    import sys

    monkeypatch.setitem(sys.modules, "torch", None)
    captured = capture_host_primitives()
    assert captured.cuda_version is None
