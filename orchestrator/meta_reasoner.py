"""Adaptive early-exit evaluation and bounded graph optimization."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import Field

from core.base import CalienneBaseModel
from core.schemas import PipelineBudget, StageAssessment, TaskGraph, TaskNode, TaskProfile

LOGGER = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ROUTING_DEFAULTS_PATH = _REPO_ROOT / "config" / "capabilities" / "routing_defaults.json"
_COMPLEXITY_ORDER: tuple[str, ...] = ("low", "medium", "high", "critical")
_PRIORITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "normal": 2,
    "background": 3,
}
_REASONING_ORDER: dict[str, int] = {
    "weak": 0,
    "adequate": 1,
    "strong": 2,
}


class EarlyExitDecision(CalienneBaseModel):
    """Decision from adaptive early-exit evaluation."""

    can_exit_early: bool = False
    reason: str = ""
    thresholds_passed: list[str] = Field(default_factory=list)
    thresholds_failed: list[str] = Field(default_factory=list)
    triggered_by_contradiction: bool = False
    recommended_judge_count: int = 0
    escalate_complexity_to: str | None = None


class MutationRecord(CalienneBaseModel):
    """Recorded graph mutation or bounded optimization event."""

    mutation_type: str
    node_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class MetaReasonerResult(CalienneBaseModel):
    """Graph plus audit trail after bounded optimization."""

    graph: TaskGraph
    mutation_audit_trail: list[MutationRecord] = Field(default_factory=list)
    mutations_applied: int = 0


def load_routing_defaults(*, config_path: str | Path | None = None) -> dict[str, Any]:
    """Load routing defaults from config, ignoring metadata keys."""

    path = Path(config_path) if config_path is not None else _DEFAULT_ROUTING_DEFAULTS_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Failed to load routing defaults from %s: %s", path, exc)
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        key: value
        for key, value in payload.items()
        if not key.startswith("_")
    }


class MetaReasoner:
    """Evaluate early exit and apply bounded graph mutations."""

    def __init__(self, *, config_path: str | Path | None = None) -> None:
        self._config = load_routing_defaults(config_path=config_path)
        self._early_exit_config = self._config.get("early_exit", {})
        self._judge_allocation = self._config.get("judge_allocation", {})
        self._meta_config = self._config.get("meta_reasoner", {})
        self._max_mutations = int(self._meta_config.get("max_mutations_per_run", 3))
        allowed = self._meta_config.get("allowed_mutations", [])
        self._allowed_mutations = set(allowed if isinstance(allowed, list) else [])

    def evaluate_early_exit(
        self,
        assessment: StageAssessment,
        *,
        route: str,
        complexity: str,
    ) -> EarlyExitDecision:
        """Apply routing-default thresholds to decide whether to skip critique/judge."""

        thresholds_passed: list[str] = []
        thresholds_failed: list[str] = []
        route_minimums = self._early_exit_config.get("route_minimums", {}).get(route, {})

        def _check(name: str, condition: bool) -> None:
            if condition:
                thresholds_passed.append(name)
            else:
                thresholds_failed.append(name)

        contradiction_max = float(self._early_exit_config.get("contradiction_score_max", 0.05))
        unsupported_max = int(self._early_exit_config.get("unsupported_claim_count_max", 0))
        if (
            assessment.contradiction_score > contradiction_max
            or assessment.unsupported_claim_count > unsupported_max
        ):
            escalated = self._next_complexity(complexity)
            return EarlyExitDecision(
                can_exit_early=False,
                reason="contradictions detected; escalate complexity and add judges or repair",
                thresholds_passed=thresholds_passed,
                thresholds_failed=[
                    f"contradiction_score <= {contradiction_max}",
                    f"unsupported_claim_count <= {unsupported_max}",
                ],
                triggered_by_contradiction=True,
                recommended_judge_count=self._judge_count_for_complexity(escalated),
                escalate_complexity_to=escalated,
            )

        _check(
            f"confidence >= {self._early_exit_config.get('confidence_min', 0.95)}",
            assessment.confidence >= float(self._early_exit_config.get("confidence_min", 0.95)),
        )
        _check(
            f"calibration >= {self._early_exit_config.get('calibration_min', 0.85)}",
            (assessment.calibration or 0.0) >= float(self._early_exit_config.get("calibration_min", 0.85)),
        )
        reasoning_floor = str(self._early_exit_config.get("reasoning_quality_min", "strong"))
        _check(
            f"reasoning_quality >= {reasoning_floor}",
            _REASONING_ORDER.get((assessment.reasoning_quality or "").lower(), -1)
            >= _REASONING_ORDER.get(reasoning_floor.lower(), 2),
        )
        _check(
            f"evidence_strength >= {route_minimums.get('evidence_strength', 0.0)}",
            (assessment.evidence_strength or 0.0) >= float(route_minimums.get("evidence_strength", 0.0)),
        )
        _check(
            f"agreement >= {route_minimums.get('agreement', 0.0)}",
            (assessment.agreement or 0.0) >= float(route_minimums.get("agreement", 0.0)),
        )
        _check(
            f"stability >= {route_minimums.get('stability', 0.0)}",
            (assessment.stability or 0.0) >= float(route_minimums.get("stability", 0.0)),
        )
        _check(
            f"evidence_count >= {route_minimums.get('evidence_count', 0)}",
            assessment.evidence_count >= int(route_minimums.get("evidence_count", 0)),
        )
        _check(
            f"contradiction_score <= {contradiction_max}",
            assessment.contradiction_score <= contradiction_max,
        )
        _check(
            f"unsupported_claim_count <= {unsupported_max}",
            assessment.unsupported_claim_count <= unsupported_max,
        )

        if not thresholds_failed:
            return EarlyExitDecision(
                can_exit_early=True,
                reason="all early-exit thresholds passed; skip critique / judge",
                thresholds_passed=thresholds_passed,
                recommended_judge_count=0,
            )

        return EarlyExitDecision(
            can_exit_early=False,
            reason="thresholds not met; keep the validation path active",
            thresholds_passed=thresholds_passed,
            thresholds_failed=thresholds_failed,
            recommended_judge_count=self._judge_count_for_complexity(complexity),
        )

    def optimize_graph(
        self,
        graph: TaskGraph,
        *,
        task_profile: TaskProfile,
        budget: PipelineBudget | None = None,
        early_exit: EarlyExitDecision | None = None,
    ) -> MetaReasonerResult:
        """Apply bounded graph mutations and record an audit trail."""

        working_graph = graph.model_copy(deep=True)
        mutation_audit_trail: list[MutationRecord] = []

        def record(record: MutationRecord) -> None:
            if len(mutation_audit_trail) < self._max_mutations:
                mutation_audit_trail.append(record)

        if early_exit is not None and early_exit.can_exit_early:
            for node_id in self._skippable_nodes(working_graph, task_profile):
                if len(mutation_audit_trail) >= self._max_mutations:
                    break
                if "skip_stage" not in self._allowed_mutations and self._allowed_mutations:
                    break
                if self._skip_stage(working_graph, node_id):
                    record(
                        MutationRecord(
                            mutation_type="skip_stage",
                            node_ids=[node_id],
                            reason="early exit thresholds passed",
                        )
                    )

        if self._budget_pressure(budget) in {"critical", "exhausted"}:
            for node in working_graph.nodes:
                if len(mutation_audit_trail) >= self._max_mutations:
                    break
                if node.task_id == working_graph.final_task_id:
                    continue
                if "downgrade_tier" not in self._allowed_mutations and self._allowed_mutations:
                    break
                downgraded = self._downgrade_tier(node.model_tier)
                if downgraded != node.model_tier:
                    before = node.model_tier
                    node.model_tier = downgraded
                    record(
                        MutationRecord(
                            mutation_type="downgrade_tier",
                            node_ids=[node.task_id],
                            reason=f"budget pressure {self._budget_pressure(budget)}",
                            details={"before": before, "after": downgraded},
                        )
                    )

        if len(mutation_audit_trail) < self._max_mutations and (
            "merge_nodes" in self._allowed_mutations or not self._allowed_mutations
        ):
            merged = self._merge_redundant_nodes(working_graph)
            if merged is not None:
                record(merged)

        if len(mutation_audit_trail) < self._max_mutations and (
            "reorder" in self._allowed_mutations or not self._allowed_mutations
        ):
            reordered = self._reorder_nodes(working_graph)
            if reordered is not None:
                record(reordered)

        return MetaReasonerResult(
            graph=working_graph,
            mutation_audit_trail=mutation_audit_trail,
            mutations_applied=len(mutation_audit_trail),
        )

    def node_completed_recheck(
        self,
        node: TaskNode,
        *,
        prior_results: dict[str, Any],
    ) -> MutationRecord | None:
        """Cheap post-completion re-check hook for audit visibility."""

        if not prior_results:
            return None
        return MutationRecord(
            mutation_type="recheck",
            node_ids=[node.task_id],
            reason="cheap post-completion check",
            details={"available_inputs": sorted(prior_results.keys())},
        )

    def _judge_count_for_complexity(self, complexity: str) -> int:
        entry = self._judge_allocation.get(complexity, {})
        return int(entry.get("judge_count", 1))

    @staticmethod
    def _next_complexity(complexity: str) -> str:
        try:
            index = _COMPLEXITY_ORDER.index(complexity)
        except ValueError:
            return "high"
        return _COMPLEXITY_ORDER[min(index + 1, len(_COMPLEXITY_ORDER) - 1)]

    @staticmethod
    def _budget_pressure(budget: PipelineBudget | None) -> str:
        return budget.pressure if budget is not None else "normal"

    @staticmethod
    def _skippable_nodes(graph: TaskGraph, task_profile: TaskProfile) -> list[str]:
        route_specific = {
            "coding": ["verify"],
            "research": ["evidence_check"],
            "math": ["contradiction_check"],
            "creative": ["critique"],
            "general": [],
        }
        candidates = set(route_specific.get(task_profile.task_type, []))
        candidates.update({"judge", "consensus"})
        return [node.task_id for node in graph.nodes if node.task_id in candidates]

    @staticmethod
    def _skip_stage(graph: TaskGraph, task_id: str) -> bool:
        if task_id in {graph.root_task_id, graph.final_task_id}:
            return False
        nodes_by_id = {node.task_id: node for node in graph.nodes}
        target = nodes_by_id.get(task_id)
        if target is None:
            return False
        for node in graph.nodes:
            if task_id not in node.depends_on:
                continue
            new_deps: list[str] = []
            for dep in node.depends_on:
                if dep == task_id:
                    for replacement in target.depends_on:
                        if replacement not in new_deps:
                            new_deps.append(replacement)
                elif dep not in new_deps:
                    new_deps.append(dep)
            node.depends_on = new_deps
        graph.nodes = [node for node in graph.nodes if node.task_id != task_id]
        return True

    @staticmethod
    def _downgrade_tier(current_tier: str) -> str:
        order = ["critical", "powerful", "default", "cheap", "fast"]
        if current_tier not in order:
            return current_tier
        index = order.index(current_tier)
        return order[min(index + 1, len(order) - 1)]

    def _merge_redundant_nodes(self, graph: TaskGraph) -> MutationRecord | None:
        for node in graph.nodes:
            if node.task_id in {graph.root_task_id, graph.final_task_id}:
                continue
            for candidate in graph.nodes:
                if candidate.task_id == node.task_id:
                    continue
                if candidate.task_id in {graph.root_task_id, graph.final_task_id}:
                    continue
                if candidate.depends_on != [node.task_id]:
                    continue
                if candidate.skills_required != node.skills_required:
                    continue
                if candidate.model_tier != node.model_tier:
                    continue
                original_objective = node.objective
                node.objective = f"{node.objective} Then: {candidate.objective}"
                node.expected_tokens = (node.expected_tokens or 0) + (candidate.expected_tokens or 0) or None
                node.expected_latency_ms = (node.expected_latency_ms or 0) + (candidate.expected_latency_ms or 0) or None  # noqa: E501
                if node.output_contract is not None and candidate.output_contract is not None:
                    produced = list(node.output_contract.produced_fields)
                    for field in candidate.output_contract.produced_fields:
                        if field not in produced:
                            produced.append(field)
                    node.output_contract.produced_fields = produced
                    node.output_contract.types.update(candidate.output_contract.types)
                for dependent in graph.nodes:
                    if candidate.task_id in dependent.depends_on:
                        dependent.depends_on = [
                            node.task_id if dep == candidate.task_id else dep
                            for dep in dependent.depends_on
                        ]
                graph.nodes = [item for item in graph.nodes if item.task_id != candidate.task_id]
                return MutationRecord(
                    mutation_type="merge_nodes",
                    node_ids=[node.task_id, candidate.task_id],
                    reason="redundant adjacent nodes detected",
                    details={"primary_objective_before": original_objective},
                )
        return None

    def _reorder_nodes(self, graph: TaskGraph) -> MutationRecord | None:
        nodes_by_id = {node.task_id: node for node in graph.nodes}
        dependency_counts = {node.task_id: len(node.depends_on) for node in graph.nodes}
        dependents: dict[str, list[str]] = {node.task_id: [] for node in graph.nodes}
        for node in graph.nodes:
            for dep in node.depends_on:
                if dep in dependents:
                    dependents[dep].append(node.task_id)

        ordered_ids: list[str] = []
        ready = [node.task_id for node in graph.nodes if dependency_counts[node.task_id] == 0]
        while ready:
            ready.sort(
                key=lambda task_id: (
                    _PRIORITY_ORDER.get(nodes_by_id[task_id].priority, 2),
                    task_id,
                )
            )
            current = ready.pop(0)
            ordered_ids.append(current)
            for dependent_id in dependents.get(current, []):
                dependency_counts[dependent_id] -= 1
                if dependency_counts[dependent_id] == 0:
                    ready.append(dependent_id)

        if len(ordered_ids) != len(graph.nodes):
            return None

        if ordered_ids == [node.task_id for node in graph.nodes]:
            return None

        graph.nodes = [nodes_by_id[task_id] for task_id in ordered_ids]
        return MutationRecord(
            mutation_type="reorder",
            node_ids=ordered_ids,
            reason="reordered ready-set by priority to reduce starvation and overkill",
        )
