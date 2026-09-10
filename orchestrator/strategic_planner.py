"""Bounded strategic planning for complex requests.

The Step 5 implementation stays deterministic by default but preserves the
LLM-assisted seam through an injectable planner callable.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from core.schemas import StrategicPlan, TaskProfile

PlannerCallable = Callable[[TaskProfile, str], Awaitable[StrategicPlan | dict[str, Any]]]

_EXECUTION_STEP_PATTERNS: tuple[str, ...] = (
    r"^\s*(?:run|execute|call|invoke|deploy|apply|commit|push)\b",
    r"^\s*(?:python|pytest|npm|pnpm|uvicorn|git)\b",
)

_ROUTE_SKILLS: dict[str, list[str]] = {
    "coding": ["coder", "precision"],
    "research": ["researcher", "academic"],
    "math": ["precision"],
    "creative": ["explainer", "devils_advocate"],
    "general": ["explainer"],
}


def _looks_like_execution_step(text: str) -> bool:
    lowered = text.strip().lower()
    return any(re.search(pattern, lowered) for pattern in _EXECUTION_STEP_PATTERNS)


def _split_problem_space(user_query: str) -> list[str]:
    parts = re.split(r"\b(?:and then|then| and |;|\n)\b", user_query)
    cleaned = [part.strip(" ,.-") for part in parts if part.strip(" ,.-")]
    if not cleaned:
        return [user_query.strip() or "Handle the request"]
    return cleaned[:4]


class StrategicPlanner:
    """Build a bounded plan only when decomposition is warranted."""

    version = "strategic-planner-v1"

    def __init__(self, planner_callable: PlannerCallable | None = None) -> None:
        self._planner_callable = planner_callable

    async def create_plan(self, task_profile: TaskProfile, user_query: str) -> StrategicPlan | None:
        if not task_profile.needs_decomposition:
            return None

        if self._planner_callable is not None:
            planned = await self._planner_callable(task_profile, user_query)
            strategic_plan = planned if isinstance(planned, StrategicPlan) else StrategicPlan(**planned)
            self._validate_plan(strategic_plan)
            return strategic_plan

        strategic_plan = StrategicPlan(
            goal=user_query.strip(),
            sub_problems=_split_problem_space(user_query),
            constraints=self._derive_constraints(task_profile, user_query),
            success_criteria=self._derive_success_criteria(task_profile),
            required_skills=_ROUTE_SKILLS.get(task_profile.task_type, ["explainer"]),
            risk_notes=self._derive_risk_notes(task_profile),
            commands=[],
        )
        self._validate_plan(strategic_plan)
        return strategic_plan

    def _validate_plan(self, strategic_plan: StrategicPlan) -> None:
        for sub_problem in strategic_plan.sub_problems:
            if _looks_like_execution_step(sub_problem):
                raise ValueError("StrategicPlanner rejected raw execution steps in sub_problems")

    @staticmethod
    def _derive_constraints(task_profile: TaskProfile, user_query: str) -> list[str]:
        constraints: list[str] = []
        if task_profile.task_type == "coding":
            constraints.append("Preserve existing behavior unless the request changes it")
        if task_profile.task_type == "research":
            constraints.append("Prefer attributable claims and cite supporting evidence")
        if "without" in user_query.lower():
            constraints.append("Respect explicit exclusions in the request")
        return constraints

    @staticmethod
    def _derive_success_criteria(task_profile: TaskProfile) -> list[str]:
        criteria = ["Produce a valid final response"]
        if task_profile.requires_code_context:
            criteria.append("Account for relevant repository context")
        if task_profile.requires_rag:
            criteria.append("Ground conclusions in retrieved evidence")
        if task_profile.requires_math_check:
            criteria.append("Verify the result independently")
        return criteria

    @staticmethod
    def _derive_risk_notes(task_profile: TaskProfile) -> list[str]:
        if task_profile.complexity == "critical":
            return ["Use the strongest validation path and avoid optimistic assumptions"]
        if task_profile.complexity == "high":
            return ["Multiple dependent steps increase coordination risk"]
        return []
