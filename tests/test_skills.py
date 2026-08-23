from __future__ import annotations

import logging
from pathlib import Path

import pytest

from core.schemas import StrategicPlan, TaskProfile
from orchestrator.execution_planner import ExecutionPlanner
from orchestrator.routing import get_template
from orchestrator.skills import (
    BUILTIN_PROMPT_VERSIONS,
    KNOWN_SKILL_NAMES,
    SkillComposer,
    load_prompt_versions,
)


def test_skill_registry_loads_all_nine_initial_skills() -> None:
    composer = SkillComposer()

    assert set(composer.prompt_versions) == set(KNOWN_SKILL_NAMES)
    assert len(KNOWN_SKILL_NAMES) == 9


def test_prompt_versions_resolution_prefers_env_override(tmp_path: Path) -> None:
    default_path = tmp_path / "default_prompt_versions.json"
    default_path.write_text(
        '{"skills": {"coder": {"version": "2", "template": "coder_v2"}}}',
        encoding="utf-8",
    )
    env_path = tmp_path / "env_prompt_versions.json"
    env_path.write_text(
        '{"skills": {"coder": {"version": "7", "template": "coder_v7"}, "security": {"version": "5", "template": "security_v5"}}}',  # noqa: E501
        encoding="utf-8",
    )

    versions = load_prompt_versions(
        {"CALIENNE_PROMPT_VERSIONS_PATH": str(env_path)},
        config_path=default_path,
    )

    assert versions["coder"].version == "7"
    assert versions["coder"].template == "coder_v7"
    assert versions["security"].version == "5"


def test_prompt_versions_fall_back_to_built_in_defaults_with_warning(caplog, tmp_path: Path) -> None:
    missing_path = tmp_path / "missing_prompt_versions.json"

    with caplog.at_level(logging.WARNING):
        versions = load_prompt_versions(config_path=missing_path)

    assert versions["coder"].version == BUILTIN_PROMPT_VERSIONS["coder"].version
    assert "using built-in defaults from skills.py" in caplog.text


def test_skill_composition_rejects_incompatible_forced_skills() -> None:
    composer = SkillComposer()
    profile = TaskProfile(task_type="general", complexity="medium")
    graph = get_template("general")
    final_node = next(node for node in graph.nodes if node.task_id == "final")

    with pytest.raises(ValueError, match="Incompatible forced skills"):
        composer.compose_for_node(
            final_node,
            profile,
            force_skills=["caveman", "academic"],
        )


def test_execution_planner_applies_skill_bundles_when_enabled() -> None:
    planner = ExecutionPlanner()
    profile = TaskProfile(task_type="research", complexity="high", needs_decomposition=True, requires_rag=True)  # noqa: E501
    strategic_plan = StrategicPlan(
        goal="Research the issue",
        sub_problems=["Gather evidence", "Compare tradeoffs"],
        required_skills=["researcher"],
    )

    graph = planner.create_graph(
        profile,
        strategic_plan=strategic_plan,
        enable_skill_composition=True,
    )

    final_node = next(node for node in graph.nodes if node.task_id == "final")
    assert "researcher" in final_node.skills_required
    assert "academic" in final_node.skills_required
    assert "precision" in final_node.skills_required
    assert planner.last_skill_plan["final"].prompt_versions["researcher"] == "1"


def test_execution_planner_honors_blocked_skills() -> None:
    planner = ExecutionPlanner()
    profile = TaskProfile(task_type="coding", complexity="high", needs_decomposition=True, requires_code_context=True)  # noqa: E501
    strategic_plan = StrategicPlan(
        goal="Implement the fix",
        sub_problems=["Patch the bug"],
        required_skills=["coder"],
    )

    graph = planner.create_graph(
        profile,
        strategic_plan=strategic_plan,
        enable_skill_composition=True,
        block_skills=["precision"],
    )

    implement_node = next(node for node in graph.nodes if node.task_id == "work_1")
    assert "coder" in implement_node.skills_required
    assert "precision" not in implement_node.skills_required
