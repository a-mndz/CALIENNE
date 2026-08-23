"""Dynamic skill composition and prompt-version loading."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import Field

from core.base import CalienneBaseModel
from core.schemas import StrategicPlan, TaskGraph, TaskNode, TaskProfile
from orchestrator.contracts import OutputContract

LOGGER = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PROMPT_VERSIONS_PATH = _REPO_ROOT / "config" / "prompt_versions.json"


class PromptVersion(CalienneBaseModel):
    """Resolved version/template pair for a single skill."""

    version: str = "1"
    template: str = ""


class SkillDefinition(CalienneBaseModel):
    """Declarative definition of a composable skill."""

    name: str
    capability_tags: list[str] = Field(default_factory=list)
    prompt_fragment: str = ""
    behavioral_constraints: list[str] = Field(default_factory=list)
    preferred_output_contract: OutputContract | None = None
    incompatible_skills: list[str] = Field(default_factory=list)
    cost_impact: float = 0.0
    verbosity_impact: str = "neutral"
    prompt_version: PromptVersion = Field(default_factory=PromptVersion)


class SkillComposition(CalienneBaseModel):
    """Resolved bundle for a single node."""

    node_id: str
    skills: list[str] = Field(default_factory=list)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    templates: dict[str, str] = Field(default_factory=dict)
    total_cost_impact: float = 0.0
    output_contract_preferences: dict[str, list[str]] = Field(default_factory=dict)


def _preferred_contract(*fields: str) -> OutputContract:
    return OutputContract(
        produced_fields=list(fields),
        types={field: "string" for field in fields},
    )


_BUILTIN_SKILLS: dict[str, SkillDefinition] = {
    "caveman": SkillDefinition(
        name="caveman",
        capability_tags=["brevity", "simplicity"],
        prompt_fragment="Remove unnecessary wording and keep the answer lean.",
        behavioral_constraints=["Avoid decorative language.", "Prefer the fewest words that preserve correctness."],  # noqa: E501
        preferred_output_contract=_preferred_contract("concise_response"),
        incompatible_skills=["academic"],
        cost_impact=-0.1,
        verbosity_impact="lower",
        prompt_version=PromptVersion(version="1", template="caveman_v1"),
    ),
    "precision": SkillDefinition(
        name="precision",
        capability_tags=["verification", "evidence", "accuracy"],
        prompt_fragment="Increase factual accuracy and verify claims before finalizing.",
        behavioral_constraints=["Prefer explicit checks over intuition.", "Surface uncertainty rather than guessing."],  # noqa: E501
        preferred_output_contract=_preferred_contract("validated_result"),
        incompatible_skills=[],
        cost_impact=0.1,
        verbosity_impact="neutral",
        prompt_version=PromptVersion(version="1", template="precision_v1"),
    ),
    "academic": SkillDefinition(
        name="academic",
        capability_tags=["citations", "formal_structure"],
        prompt_fragment="Use formal structure and clearly attribute evidence.",
        behavioral_constraints=["Use disciplined structure.", "Keep claims attributable to evidence when available."],  # noqa: E501
        preferred_output_contract=_preferred_contract("structured_analysis"),
        incompatible_skills=["caveman"],
        cost_impact=0.2,
        verbosity_impact="higher",
        prompt_version=PromptVersion(version="1", template="academic_v1"),
    ),
    "coder": SkillDefinition(
        name="coder",
        capability_tags=["implementation", "verification", "repository_context"],
        prompt_fragment="Focus on implementation details, testing, and behavioral regressions.",
        behavioral_constraints=["Preserve existing behavior unless the task changes it.", "Prefer concrete code-level reasoning."],  # noqa: E501
        preferred_output_contract=_preferred_contract("implementation_result"),
        incompatible_skills=[],
        cost_impact=0.15,
        verbosity_impact="neutral",
        prompt_version=PromptVersion(version="1", template="coder_v1"),
    ),
    "researcher": SkillDefinition(
        name="researcher",
        capability_tags=["retrieval", "synthesis", "sources"],
        prompt_fragment="Retrieve relevant evidence and synthesize the findings carefully.",
        behavioral_constraints=["Distinguish source-backed claims from inference.", "Track provenance for important claims."],  # noqa: E501
        preferred_output_contract=_preferred_contract("evidence_report"),
        incompatible_skills=[],
        cost_impact=0.2,
        verbosity_impact="higher",
        prompt_version=PromptVersion(version="1", template="researcher_v1"),
    ),
    "devils_advocate": SkillDefinition(
        name="devils_advocate",
        capability_tags=["critique", "counterarguments"],
        prompt_fragment="Challenge assumptions and surface credible counterarguments.",
        behavioral_constraints=["Probe weak assumptions.", "Explicitly look for failure modes or blind spots."],  # noqa: E501
        preferred_output_contract=_preferred_contract("critique_report"),
        incompatible_skills=[],
        cost_impact=0.1,
        verbosity_impact="neutral",
        prompt_version=PromptVersion(version="1", template="devils_advocate_v1"),
    ),
    "explainer": SkillDefinition(
        name="explainer",
        capability_tags=["clarity", "teaching"],
        prompt_fragment="Explain the result in a clear, beginner-friendly way.",
        behavioral_constraints=["Prefer concrete language.", "Make the next action obvious when possible."],
        preferred_output_contract=_preferred_contract("explained_response"),
        incompatible_skills=[],
        cost_impact=0.05,
        verbosity_impact="higher",
        prompt_version=PromptVersion(version="1", template="explainer_v1"),
    ),
    "security": SkillDefinition(
        name="security",
        capability_tags=["threat_modeling", "safe_implementation"],
        prompt_fragment="Prioritize safe implementation and identify security risks.",
        behavioral_constraints=["Do not normalize risky shortcuts.", "Call out security-sensitive tradeoffs explicitly."],  # noqa: E501
        preferred_output_contract=_preferred_contract("security_review"),
        incompatible_skills=[],
        cost_impact=0.15,
        verbosity_impact="neutral",
        prompt_version=PromptVersion(version="1", template="security_v1"),
    ),
    "performance": SkillDefinition(
        name="performance",
        capability_tags=["latency", "cost", "resources"],
        prompt_fragment="Optimize for latency, cost, and resource efficiency.",
        behavioral_constraints=["Prefer measurable improvements.", "Avoid premature optimization when it harms correctness."],  # noqa: E501
        preferred_output_contract=_preferred_contract("performance_review"),
        incompatible_skills=[],
        cost_impact=0.1,
        verbosity_impact="neutral",
        prompt_version=PromptVersion(version="1", template="performance_v1"),
    ),
}

KNOWN_SKILL_NAMES: tuple[str, ...] = tuple(_BUILTIN_SKILLS)
BUILTIN_PROMPT_VERSIONS: dict[str, PromptVersion] = {
    name: definition.prompt_version.model_copy(deep=True)
    for name, definition in _BUILTIN_SKILLS.items()
}

_SKILL_PRIORITY: dict[str, int] = {
    "security": 0,
    "performance": 1,
    "precision": 2,
    "researcher": 3,
    "coder": 4,
    "academic": 5,
    "explainer": 6,
    "devils_advocate": 7,
    "caveman": 8,
}


def _normalize_prompt_version_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if "skills" in payload and isinstance(payload["skills"], dict):
        return payload["skills"]
    return {
        key: value
        for key, value in payload.items()
        if not key.startswith("_")
    }


def load_prompt_versions(
    env: dict[str, object] | None = None,
    *,
    config_path: str | Path | None = None,
) -> dict[str, PromptVersion]:
    """Load per-skill prompt versions using env -> config -> built-in precedence."""

    environment = os.environ if env is None else env
    env_override = environment.get("CALIENNE_PROMPT_VERSIONS_PATH")
    resolved_path = (
        Path(str(env_override))
        if env_override
        else Path(config_path) if config_path is not None else _DEFAULT_PROMPT_VERSIONS_PATH
    )

    loaded_versions: dict[str, PromptVersion] = {}
    if resolved_path.is_file():
        try:
            payload = json.loads(resolved_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning(
                "Falling back to built-in prompt versions because %s could not be loaded: %s",
                resolved_path,
                exc,
            )
        else:
            normalized = _normalize_prompt_version_payload(payload if isinstance(payload, dict) else {})
            for name, raw_value in normalized.items():
                if name.startswith("_") or name not in _BUILTIN_SKILLS or not isinstance(raw_value, dict):
                    continue
                loaded_versions[name] = PromptVersion(
                    version=str(raw_value.get("version", BUILTIN_PROMPT_VERSIONS[name].version)),
                    template=str(raw_value.get("template", BUILTIN_PROMPT_VERSIONS[name].template)),
                )
    else:
        LOGGER.warning(
            "Prompt versions file %s missing; using built-in defaults from skills.py",
            resolved_path,
        )

    if not loaded_versions:
        return {
            name: version.model_copy(deep=True)
            for name, version in BUILTIN_PROMPT_VERSIONS.items()
        }

    resolved_versions = {
        name: version.model_copy(deep=True)
        for name, version in BUILTIN_PROMPT_VERSIONS.items()
    }
    resolved_versions.update(loaded_versions)
    return resolved_versions


class SkillComposer:
    """Deterministically compose per-node skill bundles."""

    def __init__(
        self,
        *,
        env: dict[str, object] | None = None,
        prompt_versions_path: str | Path | None = None,
    ) -> None:
        self._env = env
        self._prompt_versions_path = prompt_versions_path
        self._prompt_versions = load_prompt_versions(env, config_path=prompt_versions_path)
        self._registry = self._build_registry()

    @property
    def prompt_versions(self) -> dict[str, PromptVersion]:
        return {
            name: version.model_copy(deep=True)
            for name, version in self._prompt_versions.items()
        }

    def _build_registry(self) -> dict[str, SkillDefinition]:
        registry: dict[str, SkillDefinition] = {}
        for name, definition in _BUILTIN_SKILLS.items():
            resolved = definition.model_copy(deep=True)
            resolved.prompt_version = self._prompt_versions.get(
                name,
                definition.prompt_version.model_copy(deep=True),
            )
            registry[name] = resolved
        return registry

    def apply_to_graph(
        self,
        graph: TaskGraph,
        task_profile: TaskProfile,
        *,
        strategic_plan: StrategicPlan | None = None,
        force_skills: list[str] | None = None,
        block_skills: list[str] | None = None,
    ) -> tuple[TaskGraph, dict[str, SkillComposition]]:
        skill_plan: dict[str, SkillComposition] = {}
        for node in graph.nodes:
            composition = self.compose_for_node(
                node,
                task_profile,
                strategic_plan=strategic_plan,
                force_skills=force_skills,
                block_skills=block_skills,
            )
            node.skills_required = composition.skills
            skill_plan[node.task_id] = composition
        return graph, skill_plan

    def compose_for_node(
        self,
        node: TaskNode,
        task_profile: TaskProfile,
        *,
        strategic_plan: StrategicPlan | None = None,
        force_skills: list[str] | None = None,
        block_skills: list[str] | None = None,
    ) -> SkillComposition:
        forced = self._validate_override_list(force_skills or [], kind="force")
        blocked = self._validate_override_list(block_skills or [], kind="block")
        if forced.intersection(blocked):
            overlap = ", ".join(sorted(forced.intersection(blocked)))
            raise ValueError(f"Cannot force and block the same skill(s): {overlap}")

        selected = self._base_skills_for_node(node, task_profile, strategic_plan=strategic_plan)
        selected.extend(skill for skill in forced if skill not in selected)
        selected = [skill for skill in selected if skill not in blocked]
        selected = self._resolve_conflicts(selected, forced)

        if not selected:
            fallback = "caveman" if node.task_id == "classify" else "explainer"
            if fallback not in blocked:
                selected = [fallback]

        output_preferences: dict[str, list[str]] = {}
        total_cost_impact = 0.0
        prompt_versions: dict[str, str] = {}
        templates: dict[str, str] = {}
        for skill_name in selected:
            definition = self._registry[skill_name]
            total_cost_impact += definition.cost_impact
            prompt_versions[skill_name] = definition.prompt_version.version
            templates[skill_name] = definition.prompt_version.template
            if definition.preferred_output_contract is not None:
                output_preferences[skill_name] = list(
                    definition.preferred_output_contract.produced_fields
                )

        return SkillComposition(
            node_id=node.task_id,
            skills=selected,
            prompt_versions=prompt_versions,
            templates=templates,
            total_cost_impact=round(total_cost_impact, 4),
            output_contract_preferences=output_preferences,
        )

    def _base_skills_for_node(
        self,
        node: TaskNode,
        task_profile: TaskProfile,
        *,
        strategic_plan: StrategicPlan | None,
    ) -> list[str]:
        selected = list(dict.fromkeys(node.skills_required))
        selected.extend(
            skill
            for skill in (strategic_plan.required_skills if strategic_plan is not None else [])
            if skill in self._registry and skill not in selected
        )

        objective = node.objective.lower()
        if node.task_id == "classify":
            return ["caveman"]

        route_defaults = {
            "coding": ["coder", "precision"],
            "research": ["researcher", "academic"],
            "math": ["precision"],
            "creative": ["explainer"],
            "general": ["explainer"],
        }
        for skill in route_defaults.get(task_profile.task_type, ["explainer"]):
            if skill not in selected:
                selected.append(skill)

        if any(token in objective for token in ("verify", "check", "evidence", "judge", "final")):
            if "precision" not in selected:
                selected.append("precision")
        if any(token in objective for token in ("security", "auth", "credential", "threat", "safe")):
            if "security" not in selected:
                selected.append("security")
        if any(token in objective for token in ("performance", "latency", "throughput", "cost", "optimiz")):
            if "performance" not in selected:
                selected.append("performance")
        if any(token in objective for token in ("critique", "challenge", "counter", "tradeoff")):
            if "devils_advocate" not in selected:
                selected.append("devils_advocate")
        if node.task_id == "final" and task_profile.task_type in {"general", "coding", "math"}:
            if "explainer" not in selected:
                selected.append("explainer")
        if task_profile.complexity in {"high", "critical"} and "precision" not in selected:
            selected.append("precision")

        return selected

    def _resolve_conflicts(self, selected: list[str], forced: set[str]) -> list[str]:
        resolved: list[str] = []
        for skill in selected:
            if skill not in self._registry:
                continue
            conflict = next(
                (
                    existing
                    for existing in resolved
                    if skill in self._registry[existing].incompatible_skills
                    or existing in self._registry[skill].incompatible_skills
                ),
                None,
            )
            if conflict is None:
                resolved.append(skill)
                continue
            if skill in forced and conflict in forced:
                raise ValueError(
                    f"Incompatible forced skills: {conflict} and {skill}"
                )
            if skill in forced:
                resolved.remove(conflict)
                resolved.append(skill)
                continue
            if conflict in forced:
                continue
            existing_priority = _SKILL_PRIORITY.get(conflict, 100)
            candidate_priority = _SKILL_PRIORITY.get(skill, 100)
            if candidate_priority < existing_priority:
                resolved.remove(conflict)
                resolved.append(skill)
        return resolved

    def _validate_override_list(self, skills: list[str], *, kind: str) -> set[str]:
        unknown = sorted(skill for skill in skills if skill not in self._registry)
        if unknown:
            joined = ", ".join(unknown)
            raise ValueError(f"Unknown {kind} skill override(s): {joined}")
        return set(skills)
