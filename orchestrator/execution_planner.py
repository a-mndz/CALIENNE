"""Rule-based ExecutionPlanner for Step 5.

Converts a StrategicPlan or deterministic template into a validated TaskGraph.
"""

from __future__ import annotations

from typing import Any

from core.schemas import PipelineBudget, StrategicPlan, TaskGraph, TaskNode, TaskProfile
from orchestrator.contracts import FailureContract, InputContract, OutputContract
from orchestrator.planner_command import DispatchNode, FanOut, SkipNode, apply_skip_node
from orchestrator.routing import get_template, validate_or_fallback
from orchestrator.skills import KNOWN_SKILL_NAMES, SkillComposer, SkillComposition

_KNOWN_SKILLS = frozenset(KNOWN_SKILL_NAMES)


def _input_contract(*required_fields: str) -> InputContract:
    return InputContract(required_fields=list(required_fields), allowed_types=["dict"], validation_rules={})


def _output_contract(*produced_fields: str) -> OutputContract:
    return OutputContract(
        produced_fields=list(produced_fields),
        types={field: "string" for field in produced_fields},
    )


def _failure_contract() -> FailureContract:
    return FailureContract(
        failure_modes=["timeout", "validation_error", "provider_down", "rate_limited"],
        response_shape="repair_request",
    )


class ExecutionPlanner:
    """Convert planning inputs into a validated TaskGraph."""

    version = "execution-planner-v1"

    def __init__(self, skill_composer: SkillComposer | None = None) -> None:
        self._skill_composer = skill_composer or SkillComposer()
        self._last_skill_plan: dict[str, SkillComposition] = {}
        self._last_graph_valid: bool = True
        self._last_fallback_used: bool = False

    @property
    def last_skill_plan(self) -> dict[str, SkillComposition]:
        return {
            node_id: composition.model_copy(deep=True)
            for node_id, composition in self._last_skill_plan.items()
        }

    @property
    def last_planner_telemetry(self) -> dict[str, Any]:
        """``planner.output.*`` / ``planner.template.fallback`` (RFC-005 §4.1)."""
        return {
            "planner.output.valid": self._last_graph_valid,
            "planner.output.invalid": not self._last_graph_valid,
            "planner.template.fallback": self._last_fallback_used,
        }

    def create_graph(
        self,
        task_profile: TaskProfile,
        *,
        strategic_plan: StrategicPlan | None = None,
        budget: PipelineBudget | None = None,
        enable_skill_composition: bool = False,
        force_skills: list[str] | None = None,
        block_skills: list[str] | None = None,
    ) -> TaskGraph:
        if strategic_plan is None:
            graph, used_fallback, _errors = validate_or_fallback(
                get_template(task_profile),
                route=task_profile.task_type,
                complexity=task_profile.complexity,
            )
            self._last_fallback_used = used_fallback
            self._last_graph_valid = not used_fallback
            graph.planner_version = self.version
            return self._apply_skill_composition(
                graph,
                task_profile,
                strategic_plan=None,
                enabled=enable_skill_composition,
                force_skills=force_skills,
                block_skills=block_skills,
            )

        graph = self._build_graph_from_strategic_plan(task_profile, strategic_plan, budget or PipelineBudget())  # noqa: E501
        validated_graph, used_fallback, _errors = validate_or_fallback(
            graph,
            route=task_profile.task_type,
            complexity=task_profile.complexity,
        )
        self._last_fallback_used = used_fallback
        self._last_graph_valid = not used_fallback
        validated_graph.planner_version = self.version
        return self._apply_skill_composition(
            validated_graph,
            task_profile,
            strategic_plan=strategic_plan,
            enabled=enable_skill_composition,
            force_skills=force_skills,
            block_skills=block_skills,
        )

    def _apply_skill_composition(
        self,
        graph: TaskGraph,
        task_profile: TaskProfile,
        *,
        strategic_plan: StrategicPlan | None,
        enabled: bool,
        force_skills: list[str] | None,
        block_skills: list[str] | None,
    ) -> TaskGraph:
        if not enabled:
            self._last_skill_plan = {}
            return graph
        graph, skill_plan = self._skill_composer.apply_to_graph(
            graph,
            task_profile,
            strategic_plan=strategic_plan,
            force_skills=force_skills,
            block_skills=block_skills,
        )
        self._last_skill_plan = skill_plan
        return graph

    def _build_graph_from_strategic_plan(
        self,
        task_profile: TaskProfile,
        strategic_plan: StrategicPlan,
        budget: PipelineBudget,
    ) -> TaskGraph:
        if strategic_plan.commands:
            has_dispatch_or_fanout = any(
                isinstance(cmd, (DispatchNode, FanOut)) for cmd in strategic_plan.commands
            )
            if has_dispatch_or_fanout:
                nodes: list[TaskNode] = []
                seen_ids: set[str] = set()

                for cmd in strategic_plan.commands:
                    if isinstance(cmd, DispatchNode):
                        task_id = cmd.task_id or cmd.worker
                        if task_id in seen_ids:
                            count = sum(1 for sid in seen_ids if sid.startswith(task_id)) + 1
                            task_id = f"{task_id}_{count}"
                        seen_ids.add(task_id)

                        objective = cmd.payload.get("objective") or f"Execute {cmd.worker} task"
                        skills = [
                            s
                            for s in (
                                [cmd.worker]
                                if cmd.worker in _KNOWN_SKILLS
                                else (strategic_plan.required_skills or [])
                            )
                            if s in _KNOWN_SKILLS
                        ]
                        if not skills:
                            skills = ["explainer"]
                        tier = cmd.payload.get("tier", self._choose_tier(task_profile))
                        priority = cmd.payload.get("priority", "normal")
                        deps = list(cmd.depends_on)
                        can_parallel = cmd.payload.get("can_run_parallel", not bool(deps))

                        nodes.append(
                            self._make_node(
                                task_id,
                                objective,
                                depends_on=deps,
                                skills=skills,
                                tier=tier,
                                priority=priority,
                                input_fields=tuple(cmd.payload.get("input_fields", ("request",))),
                                output_fields=tuple(
                                    cmd.payload.get("output_fields", (f"{task_id}_output",))
                                ),
                                can_run_parallel=can_parallel,
                                expected_tokens=cmd.payload.get(
                                    "expected_tokens", max(100, int(budget.total_tokens * 0.05))
                                ),
                                expected_latency_ms=cmd.payload.get("expected_latency_ms", 30),
                            )
                        )
                    elif isinstance(cmd, FanOut):
                        prefix = cmd.task_prefix or cmd.worker
                        deps = list(cmd.depends_on)
                        skills = [
                            s
                            for s in (
                                [cmd.worker]
                                if cmd.worker in _KNOWN_SKILLS
                                else (strategic_plan.required_skills or [])
                            )
                            if s in _KNOWN_SKILLS
                        ]
                        if not skills:
                            skills = ["explainer"]

                        for idx, payload in enumerate(cmd.payloads, start=1):
                            task_id = f"{prefix}_{idx}"
                            seen_ids.add(task_id)
                            objective = payload.get("objective") or f"Execute {cmd.worker} shard {idx}"
                            tier = payload.get("tier", self._choose_tier(task_profile))
                            priority = payload.get("priority", "normal")

                            nodes.append(
                                self._make_node(
                                    task_id,
                                    objective,
                                    depends_on=list(deps),
                                    skills=skills,
                                    tier=tier,
                                    priority=priority,
                                    input_fields=tuple(payload.get("input_fields", ("request",))),
                                    output_fields=tuple(
                                        payload.get("output_fields", (f"{task_id}_output",))
                                    ),
                                    can_run_parallel=True,
                                    expected_tokens=payload.get(
                                        "expected_tokens", max(100, int(budget.total_tokens * 0.05))
                                    ),
                                    expected_latency_ms=payload.get("expected_latency_ms", 30),
                                )
                            )

                for cmd in strategic_plan.commands:
                    if isinstance(cmd, SkipNode):
                        nodes = apply_skip_node(nodes, cmd.stage)

                root_id = nodes[0].task_id if nodes else ""
                final_id = nodes[-1].task_id if nodes else ""
                for n in nodes:
                    if n.task_id == "classify":
                        root_id = "classify"
                    if n.task_id == "final":
                        final_id = "final"

                return TaskGraph(
                    nodes=nodes,
                    root_task_id=root_id,
                    final_task_id=final_id,
                    planner_version=self.version,
                )

        nodes: list[TaskNode] = [
            self._make_node(
                "classify",
                "Carry forward the request classification",
                skills=["caveman"],
                tier="fast",
                priority="normal",
                output_fields=("task_profile",),
                expected_tokens=max(50, int(budget.total_tokens * 0.01)),
                expected_latency_ms=10,
            ),
            self._make_node(
                "plan",
                "Materialize the strategic plan into graph-ready tasks",
                depends_on=["classify"],
                skills=strategic_plan.required_skills or ["explainer"],
                tier="default",
                priority="high" if task_profile.complexity in {"high", "critical"} else "normal",
                input_fields=("request", "task_profile"),
                output_fields=("strategic_plan",),
                expected_tokens=max(100, int(budget.total_tokens * 0.05)),
                expected_latency_ms=25,
            ),
        ]

        dependency_anchor = "plan"
        work_node_ids: list[str] = []
        parallel_budget = max(1, min(3, len(strategic_plan.sub_problems)))
        for index, sub_problem in enumerate(strategic_plan.sub_problems, start=1):
            task_id = f"work_{index}"
            depends_on = [dependency_anchor]
            can_parallel = index <= parallel_budget
            if not can_parallel and work_node_ids:
                depends_on = [work_node_ids[-1]]
            work_node_ids.append(task_id)
            nodes.append(
                self._make_node(
                    task_id,
                    sub_problem,
                    depends_on=depends_on,
                    skills=strategic_plan.required_skills or ["explainer"],
                    tier=self._choose_tier(task_profile),
                    priority="high",
                    input_fields=("strategic_plan",),
                    output_fields=(f"sub_result_{index}",),
                    can_run_parallel=can_parallel,
                    expected_tokens=max(150, int(budget.total_tokens * 0.12)),
                    expected_latency_ms=75,
                )
            )

        aggregate_deps = work_node_ids or [dependency_anchor]
        nodes.append(
            self._make_node(
                "final",
                "Assemble the final response from completed work",
                depends_on=aggregate_deps,
                skills=["precision"],
                tier="default",
                priority="high",
                input_fields=tuple(f"sub_result_{index}" for index in range(1, len(work_node_ids) + 1)) or ("strategic_plan",),  # noqa: E501
                output_fields=("final_response",),
                can_run_parallel=False,
                expected_tokens=max(100, int(budget.total_tokens * 0.05)),
                expected_latency_ms=30,
            )
        )

        if strategic_plan.commands:
            for cmd in strategic_plan.commands:
                if isinstance(cmd, SkipNode):
                    nodes = apply_skip_node(nodes, cmd.stage)

        has_classify = any(n.task_id == "classify" for n in nodes)
        root_id = "classify" if has_classify else (nodes[0].task_id if nodes else "")
        has_final = any(n.task_id == "final" for n in nodes)
        final_id = "final" if has_final else (nodes[-1].task_id if nodes else "")

        return TaskGraph(
            nodes=nodes,
            root_task_id=root_id,
            final_task_id=final_id,
            planner_version=self.version,
        )

    def _make_node(
        self,
        task_id: str,
        objective: str,
        *,
        depends_on: list[str] | None = None,
        skills: list[str] | None = None,
        tier: str,
        priority: str,
        input_fields: tuple[str, ...] = ("request",),
        output_fields: tuple[str, ...] = ("result",),
        can_run_parallel: bool | None = None,
        expected_tokens: int | None = None,
        expected_latency_ms: int | None = None,
    ) -> TaskNode:
        deps = depends_on or []
        return TaskNode(
            task_id=task_id,
            objective=objective,
            skills_required=skills or [],
            model_tier=tier,
            depends_on=deps,
            can_run_parallel=(not deps if can_run_parallel is None else can_run_parallel),
            priority=priority,
            input_contract=_input_contract(*input_fields),
            output_contract=_output_contract(*output_fields),
            failure_contract=_failure_contract(),
            expected_tokens=expected_tokens,
            expected_latency_ms=expected_latency_ms,
        )

    @staticmethod
    def _choose_tier(task_profile: TaskProfile) -> str:
        if task_profile.complexity == "critical":
            return "critical"
        if task_profile.complexity == "high":
            return "powerful"
        if task_profile.complexity == "low":
            return "cheap"
        return "default"
