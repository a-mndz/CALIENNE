"""Request entry point for the DAG runtime.

When DAG execution is disabled, this manager falls back to the legacy
``run_micro_mode`` path unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from api_gateway.client import get_last_provider_usage
from core.passport import ExecutionPassport
from core.runtime import RuntimeContract
from core.schemas import PipelineBudget, StrategicPlan, TaskGraph, TaskProfile
from orchestrator import versioning
from orchestrator.budget import TokenBudgetManager
from orchestrator.claims import ClaimManager
from orchestrator.context_manager import ContextManager
from orchestrator.contracts import validate_inputs, validate_outputs
from orchestrator.execution_manifest import ExecutionManifest, build_execution_manifest
from orchestrator.execution_planner import ExecutionPlanner
from orchestrator.execution_replay import (
    ReplayRecorder,
    ReplayStore,
    prompt_fingerprint,
)
from orchestrator.feature_flags import FeatureFlags, load_flags
from orchestrator.memory_hierarchy import MemoryEntry, MemoryHierarchy
from orchestrator.memory_manager import MemoryManager
from orchestrator.meta_reasoner import EarlyExitDecision, MetaReasoner
from orchestrator.pipelines import MicroModeResult, run_micro_mode
from orchestrator.prediction import PredictionLayer
from orchestrator.resource_manager import ResourceManager
from orchestrator.retrieval import RetrievalService, load_route_gating, load_routing_weights
from orchestrator.routing import IntentAnalyzer
from orchestrator.scheduler import Scheduler
from orchestrator.skills import load_prompt_versions
from orchestrator.strategic_planner import StrategicPlanner
from orchestrator.uncertainty import UncertaintyDecision, UncertaintyEngine
from orchestrator.validation_layer import ValidationLayer
from telemetry.observer import estimate_cost_usd

LOGGER = logging.getLogger(__name__)

# RFC-005 §4.1 namespace template — every example key is always present in
# ``dashboard_metrics``; unsourced fields stay None until later steps (Step 18
# ResourceManager, Step 19 ExecutionManifest/fingerprinting/HostPrimitives).
_DASHBOARD_METRIC_TEMPLATE: dict[str, Any] = {
    # execution.* (Scheduler + repair loop)
    "execution.node.started": None,
    "execution.node.completed": None,
    "execution.node.failed": None,
    "execution.retries": None,
    "execution.repairs": None,
    # quality.* (StageAssessment / firewall / consensus)
    "quality.confidence": None,
    "quality.calibration": None,
    "quality.evidence_strength": None,
    "quality.contradiction_score": None,
    "quality.unsupported_claim_count": None,
    # resources.* (BudgetSnapshot / ResourceManager stub)
    "resources.tokens.consumed": None,
    "resources.tokens.remaining": None,
    "resources.concurrency.active": None,
    "resources.concurrency.cap": None,
    "resources.rate_limit.headroom": None,
    "resources.gpu": None,
    "resources.cpu": None,
    "resources.memory": None,
    "resources.connection_pool.size": None,
    # prediction.* (PredictionLayer.record_actuals)
    "prediction.cost.predicted": None,
    "prediction.cost.actual": None,
    "prediction.latency.predicted": None,
    "prediction.latency.actual": None,
    "prediction.calibration_confidence": None,
    "prediction.repair.likelihood": None,
    # learning.* (MetaReasoner mutation_audit_trail / memory hierarchy)
    "learning.graph.fingerprint": None,
    "learning.planner.quality": None,
    "learning.mutation.audit": None,
    "learning.user_satisfaction": None,
    # environment.* (versioning.capture_environment_snapshot)
    "environment.os": None,
    "environment.python_version": None,
    "environment.cuda_version": None,
    "environment.container": None,
    # manifest.* (versioning.manifest_metrics)
    "manifest.architecture_version": None,
    "manifest.graph_version": None,
    "manifest.graph_fingerprint": None,
    "manifest.git_commit": None,
    # scheduler.* (Scheduler.telemetry)
    "scheduler.node.queued": None,
    "scheduler.node.released": None,
    "scheduler.priority_band": None,
    "scheduler.starvation_promoted": None,
    # planner.* (ExecutionPlanner.last_planner_telemetry)
    "planner.invocation": None,
    "planner.output.valid": None,
    "planner.output.invalid": None,
    "planner.template.fallback": None,
    "planner.fingerprint.hash": None,
}


def populate_contract_fields(raw: Any, normalized: str, fields: list[str]) -> dict[str, Any]:
    """Honest population of a node's declared output fields (research Tier 0.2).

    Single-field contracts: the normalized response IS the field.
    Multi-field contracts: populate only fields the model actually produced
    in a structured response. Declared-but-absent fields stay missing so
    ``validate_outputs`` reports them — the previous behaviour (every
    declared field receiving the same response string) was a contract layer
    certifying fabricated content, which is strictly worse than no contract
    layer at all.
    """
    if len(fields) <= 1:
        return {fields[0]: normalized}
    parsed: Any = None
    if isinstance(raw, dict):
        parsed = raw
    elif isinstance(raw, str):
        try:
            candidate = json.loads(raw)
        except json.JSONDecodeError:
            candidate = None
        if isinstance(candidate, dict):
            parsed = candidate
    if not parsed:
        # No structured response to draw from: emit only the normalized text
        # under the first field; the contract checker reports the rest missing.
        return {fields[0]: normalized}
    produced = {field: parsed[field] for field in fields if field in parsed}
    if not produced:
        # Structured but none of the declared keys (e.g. a generic
        # {"answer": ...} against contract-specific names): the model did
        # produce an answer — map it to the first declared field and let any
        # remaining declared fields surface as violations rather than
        # certifying copies.
        return {fields[0]: normalized}
    return produced


class ExecutionManager:
    """Owns the DAG runtime entrypoint while preserving legacy fallback."""

    def __init__(
        self,
        *,
        flags: FeatureFlags | None = None,
        intent_analyzer: type[IntentAnalyzer] = IntentAnalyzer,
        strategic_planner: StrategicPlanner | None = None,
        execution_planner: ExecutionPlanner | None = None,
        resource_manager: Any | None = None,
        runtime_contract: RuntimeContract | None = None,
        memory_manager: MemoryManager | None = None,
        memory_hierarchy: MemoryHierarchy | None = None,
        budget_manager: TokenBudgetManager | None = None,
        prediction_layer: PredictionLayer | None = None,
        context_manager: ContextManager | None = None,
        meta_reasoner: MetaReasoner | None = None,
        uncertainty_engine: UncertaintyEngine | None = None,
        claim_manager: ClaimManager | None = None,
        retrieval_service: RetrievalService | None = None,
        replay_store: ReplayStore | None = None,
        runtime_engine: Any | None = None,
    ) -> None:
        self._flags = flags or load_flags()
        self._intent_analyzer = intent_analyzer
        self._strategic_planner = strategic_planner or StrategicPlanner()
        self._execution_planner = execution_planner or ExecutionPlanner()
        self._resource_manager = resource_manager or ResourceManager()
        self._runtime_contract = runtime_contract
        self._memory_manager = memory_manager or MemoryManager()
        self._memory_hierarchy = memory_hierarchy
        self._budget_manager = budget_manager or TokenBudgetManager(
            memory_manager=self._memory_manager,
            runtime_contract=self._runtime_contract,
        )
        self._prediction_layer = prediction_layer or PredictionLayer()
        self._retrieval_service = retrieval_service
        if self._retrieval_service is None and self._flags.rag:
            self._retrieval_service = RetrievalService(
                weights=load_routing_weights(),
                route_gating=load_route_gating(),
            )
        self._context_manager = context_manager or ContextManager(
            memory_manager=self._memory_manager,
            retrieval_service=self._retrieval_service,
            memory_hierarchy=self._memory_hierarchy if self._flags.context else None,
        )
        self._meta_reasoner = meta_reasoner or MetaReasoner()
        self._claim_manager = claim_manager or ClaimManager()
        self._validation_layer = ValidationLayer(self._claim_manager)
        self._uncertainty_engine = uncertainty_engine or UncertaintyEngine(
            validation_layer=self._validation_layer
        )
        self._replay_store = replay_store
        self._runtime_engine = runtime_engine
        if self._replay_store is None and self._flags.replay:
            self._replay_store = ReplayStore()
        self._prompt_versions = {
            name: prompt.version
            for name, prompt in load_prompt_versions().items()
        }

    async def execute(
        self,
        *,
        user_query: str,
        gateway: Any,
        strategy: Any,
        pool: Any,
        history: list[dict[str, str]] | None = None,
        passport: ExecutionPassport | None = None,
        decision_engine: Any | None = None,
        reasoning_graph: Any | None = None,
        claim_manager: Any | None = None,
        streaming_manager: Any | None = None,
        conversation_director: Any | None = None,
        session_id: str | None = None,
        force_skills: list[str] | None = None,
        block_skills: list[str] | None = None,
        user_id: str | None = None,
    ) -> MicroModeResult | dict[str, Any]:
        if not self._flags.dag:
            return await run_micro_mode(
                user_query=user_query,
                gateway=gateway,
                strategy=strategy,
                pool=pool,
                history=history,
                passport=passport,
                decision_engine=decision_engine,
                reasoning_graph=reasoning_graph,
                claim_manager=claim_manager,
                streaming_manager=streaming_manager,
                conversation_director=conversation_director,
                session_id=session_id,
                flags=self._flags,
                user_id=user_id,
            )

        execution_manifest = build_execution_manifest(
            flags=self._flags,
            prompt_versions=self._prompt_versions,
        )
        if passport is not None:
            passport.set_execution_manifest(execution_manifest)
        start_time = time.monotonic()
        recorder: ReplayRecorder | None = None
        request_fingerprint = prompt_fingerprint(user_query)
        if self._flags.replay:
            recorder = ReplayRecorder(
                trace_id=uuid.uuid4().hex,
                passport_id=getattr(passport, "request_id", None) if passport is not None else None,
            )
        budget = self._budget_manager.create_budget()
        history_budget = self._budget_manager.maybe_compress_history(
            history,
            budget=budget,
            reserved_tokens=max(1, len(user_query.split())),
        )
        budget_snapshot = self._budget_manager.snapshot(
            budget=budget,
            used_tokens=max(1, len(user_query.split())),
            messages=history_budget.messages,
        )
        self._emit(
            recorder,
            "budget_pressure_changed",
            payload={"pressure": getattr(budget_snapshot, "pressure", None)},
        )
        task_profile = self._intent_analyzer.classify(user_query)
        await self._seed_memory_hierarchy(
            user_query=user_query,
            history=history_budget.messages,
        )
        memory_telemetry: dict[str, Any]
        if self._flags.context and self._memory_hierarchy is not None:
            snapshot = self._memory_hierarchy.snapshot()
            snapshot["status"] = "ok"
            memory_telemetry = snapshot
        else:
            memory_telemetry = {"status": "disabled"}
        strategic_plan = await self._maybe_plan(task_profile, user_query)
        execution_manifest = execution_manifest.model_copy(
            update={"planner_version": getattr(self._execution_planner, "version", None)}
        )
        if passport is not None:
            passport.set_execution_manifest(execution_manifest)
        graph = self._execution_planner.create_graph(
            task_profile,
            strategic_plan=strategic_plan,
            budget=budget,
            enable_skill_composition=self._flags.skills,
            force_skills=force_skills,
            block_skills=block_skills,
        )
        initial_stage_assessment = self._validation_layer.assess(task_profile)
        early_exit_decision = self._meta_reasoner.evaluate_early_exit(
            initial_stage_assessment,
            route=task_profile.task_type,
            complexity=task_profile.complexity,
        )
        if getattr(early_exit_decision, "can_exit_early", False):
            self._emit(
                recorder,
                "early_exit",
                payload={"reason": getattr(early_exit_decision, "reason", None)},
            )
        meta_result = self._meta_reasoner.optimize_graph(
            graph,
            task_profile=task_profile,
            budget=budget_snapshot.budget,
            early_exit=early_exit_decision,
        )
        graph = meta_result.graph
        versioning.stamp_graph(
            graph,
            planner_version=getattr(self._execution_planner, "version", graph.planner_version),
            strategy_version=getattr(strategy, "version", None),
        )
        graph.execution_manifest = execution_manifest
        graph.version_stamp = versioning.build_version_stamp(
            graph,
            prompt_versions=execution_manifest.prompt_versions,
            prediction_model_version=(
                getattr(self._prediction_layer, "version", None)
                if self._flags.prediction
                else None
            ),
        )
        skill_plan = self._execution_planner.last_skill_plan if self._flags.skills else None
        if skill_plan is not None:
            current_node_ids = {node.task_id for node in graph.nodes}
            skill_plan = {
                node_id: composition
                for node_id, composition in skill_plan.items()
                if node_id in current_node_ids
            }
        prediction = None
        if self._flags.prediction:
            prediction = self._prediction_layer.predict(
                task_profile,
                graph=graph,
                budget=budget,
            )
        uncertainty_decision = self._uncertainty_engine.evaluate(
            user_query=user_query,
            task_profile=task_profile,
            stage_assessment=initial_stage_assessment,
            prediction=prediction,
            available_context_keys=["task_profile", "strategic_plan"] if strategic_plan is not None else ["task_profile"],  # noqa: E501
        )
        uncertainty_triggered_retrieval = (
            uncertainty_decision.outcome == "run_retrieval"
        )
        concurrency_limit = self._resource_manager.scheduler_concurrency_limit(graph)
        if self._resource_manager.recompute_plan(graph, prediction) == "reject":
            raise RuntimeError("DAG execution rejected by resource limits")
        resource_state = self._resource_manager.snapshot()
        resource_metrics = {
            "resources.tokens.consumed": budget_snapshot.used_tokens,
            "resources.tokens.remaining": budget_snapshot.remaining_tokens,
            "resources.concurrency.cap": concurrency_limit,
            "resources.concurrency.active": resource_state.concurrency_active,
            "resources.rate_limit.headroom": resource_state.rate_limit_remaining,
            "resources.gpu": execution_manifest.host.cuda_version,
            "resources.cpu": resource_state.cpu_parallel_ceiling,
            "resources.memory": None,
            "resources.connection_pool.size": resource_state.connection_pool_size,
        }
        manifest_metrics = versioning.manifest_metrics(graph=graph)
        environment_metrics = versioning.environment_snapshot
        planner_metrics = {
            **getattr(self._execution_planner, "last_planner_telemetry", {}),
            "planner.invocation": strategic_plan is not None,
            "planner.fingerprint.hash": graph.graph_fingerprint,
        }
        quality_metrics_initial = {
            "quality.confidence": initial_stage_assessment.confidence,
            "quality.calibration": initial_stage_assessment.calibration,
            "quality.evidence_strength": initial_stage_assessment.evidence_strength,
            "quality.contradiction_score": initial_stage_assessment.contradiction_score,
            "quality.unsupported_claim_count": initial_stage_assessment.unsupported_claim_count,
        }
        if uncertainty_decision.outcome == "ask_user_clarification":
            if passport is not None:
                passport.update_stage("needs_clarification")
            self._emit(recorder, "node_cancelled", payload={"reason": "needs_clarification"})
            clarification_trace_id = self._finalize_replay(
                recorder,
                graph=graph,
                prompt_fingerprint_value=request_fingerprint,
                task_profile=task_profile,
                strategic_plan=strategic_plan,
                resource_snapshot=resource_metrics,
                prediction_actual=None,
                final_outcome={"status": "needs_clarification"},
                manifest=execution_manifest,
            )
            return {
                "status": "needs_clarification",
                "task_profile": task_profile,
                "strategic_plan": strategic_plan,
                "graph": graph,
                "execution_manifest": execution_manifest,
                "version_stamp": graph.version_stamp,
                "budget": budget,
                "budget_snapshot": budget_snapshot,
                "history_summary": history_budget.summary,
                "history_compressed": history_budget.applied,
                "history_pressure": history_budget.pressure,
                "early_exit_decision": early_exit_decision,
                "mutation_audit_trail": meta_result.mutation_audit_trail,
                "prediction": prediction,
                "prediction_telemetry": None,
                "skill_plan": skill_plan,
                "uncertainty_decision": uncertainty_decision,
                "clarification_request": uncertainty_decision.clarification_request,
                "rag_telemetry": None,
                "memory_telemetry": memory_telemetry,
                "replay_trace_id": clarification_trace_id,
                "dashboard_metrics": self._assemble_dashboard_metrics(
                    resource_metrics,
                    manifest_metrics,
                    environment_metrics,
                    planner_metrics,
                    quality_metrics_initial,
                ),
                "results": {},
                "passport": passport.to_dict() if passport is not None else None,
            }
        scheduler = Scheduler(
            executor=self._make_node_executor(
                passport=passport,
                context_manager=self._context_manager,
                context_enabled=self._flags.context,
                user_query=user_query,
                task_profile=task_profile,
                strategic_plan=strategic_plan,
                history=history_budget.messages,
                history_summary=history_budget.summary,
                budget=budget,
                meta_reasoner=self._meta_reasoner,
                mutation_audit_trail=meta_result.mutation_audit_trail,
                rag_enabled=self._flags.rag,
                uncertainty_triggered_retrieval=uncertainty_triggered_retrieval,
                gateway=gateway,
                strategy=strategy,
                pool=pool,
                resource_manager=self._resource_manager,
                initial_used_tokens=budget_snapshot.used_tokens,
                runtime_engine=self._runtime_engine,
            ),
            concurrency_limit=concurrency_limit,
        )
        if passport is not None:
            passport.update_stage("scheduler_running")
        for node in graph.nodes:
            self._emit(recorder, "node_queued", node_id=node.task_id)
        results = await scheduler.run(graph)
        for node_id, result in results.items():
            self._emit(recorder, "node_started", node_id=node_id)
            deps = result.get("depends_on", []) if isinstance(result, dict) else []
            for dep in deps:
                self._emit(recorder, "dependency_released", node_id=dep)
            self._emit(recorder, "node_completed", node_id=node_id)
        repair_result = None
        if self._flags.repair:
            LOGGER.warning("DAG repair is unavailable until a real defect-driven repair dispatcher is wired")
        consensus_result = None
        if self._flags.consensus:
            LOGGER.warning("DAG consensus is unavailable until independent judge dispatch is wired")
        final_output, firewall_result = self._validation_layer.validate_dag_output(
            user_query=user_query,
            history=history_budget.messages,
            task_profile=task_profile,
            strategic_plan=strategic_plan,
            results=results,
            final_node_id=graph.final_task_id,
        )
        actual_tokens = budget_snapshot.used_tokens + sum(
            int(result.get("actual_tokens", 0))
            for result in results.values()
            if isinstance(result, dict)
        )
        budget_snapshot = self._budget_manager.snapshot(
            budget=budget,
            used_tokens=actual_tokens,
        )
        if passport is not None:
            passport.update_stage("completed")
        prediction_telemetry = None
        if prediction is not None:
            # Stage 2: actuals are measured, not derived from the prediction
            # itself (the old token-ratio scaling invented agreement), and
            # confidence comes from the firewall-derived validation score
            # instead of a hardcoded 0.8.
            measured_cost = sum(
                float(result.get("measured_cost_usd", 0.0) or 0.0)
                for result in results.values()
                if isinstance(result, dict)
            )
            prediction_telemetry = self._prediction_layer.record_actuals(
                prediction,
                actual_cost=round(measured_cost, 6),
                actual_latency_ms=(time.monotonic() - start_time) * 1000,
                actual_tokens=actual_tokens,
                actual_confidence=max(
                    0.0, min(1.0, final_output.validation_score / 10.0)
                ),
            )
        rag_telemetry = self._aggregate_rag_telemetry(
            results=results,
            uncertainty_triggered=uncertainty_triggered_retrieval,
        )
        quality_metrics = dict(quality_metrics_initial)
        quality_metrics["quality.unsupported_claim_count"] = len(
            firewall_result.get("unsupported_claims", [])
        )
        if consensus_result is not None:
            quality_metrics["quality.contradiction_score"] = consensus_result.contradiction_score
        learning_metrics = {
            "learning.mutation.audit": [
                record.model_dump() for record in meta_result.mutation_audit_trail
            ],
            "learning.graph.fingerprint": graph.graph_fingerprint,
            "learning.planner.quality": None,  # ponytail: no scoring model yet
            "learning.user_satisfaction": None,  # ponytail: no feedback loop yet
        }
        execution_metrics = {
            **scheduler.telemetry,
            "execution.repairs": repair_result.repair_count if repair_result is not None else None,
            "execution.retries": None,  # ponytail: scheduler has no retry mechanism yet
        }
        dashboard_metrics = self._assemble_dashboard_metrics(
            resource_metrics,
            manifest_metrics,
            environment_metrics,
            planner_metrics,
            quality_metrics,
            learning_metrics,
            execution_metrics,
            prediction_telemetry,
        )
        success_trace_id = self._finalize_replay(
            recorder,
            graph=graph,
            prompt_fingerprint_value=request_fingerprint,
            task_profile=task_profile,
            strategic_plan=strategic_plan,
            resource_snapshot=resource_metrics,
            prediction_actual=prediction_telemetry,
            final_outcome={"status": "success"},
            manifest=execution_manifest,
        )
        return {
            "status": "success",
            "winning_answer": final_output.final_answer,
            "validation_score": final_output.validation_score,
            "confidence_delta": 0.0,
            "judge_decision": None,
            "logician_output": None,
            "creative_output": None,
            "task_profile": task_profile,
            "strategic_plan": strategic_plan,
            "graph": graph,
            "execution_manifest": execution_manifest,
            "version_stamp": graph.version_stamp,
            "budget": budget,
            "budget_snapshot": budget_snapshot,
            "history_summary": history_budget.summary,
            "history_compressed": history_budget.applied,
            "history_pressure": history_budget.pressure,
            "early_exit_decision": early_exit_decision,
            "mutation_audit_trail": meta_result.mutation_audit_trail,
            "prediction": prediction,
            "prediction_telemetry": prediction_telemetry,
            "skill_plan": skill_plan,
            "uncertainty_decision": uncertainty_decision,
            "clarification_request": None,
            "repair_result": repair_result,
            "consensus_result": consensus_result,
            "firewall_result": firewall_result,
            "rag_telemetry": rag_telemetry,
            "memory_telemetry": memory_telemetry,
            "dashboard_metrics": dashboard_metrics,
            "final_output": final_output,
            "results": results,
            "replay_trace_id": success_trace_id,
            "passport": passport.to_dict() if passport is not None else None,
        }

    async def _maybe_plan(self, task_profile: TaskProfile, user_query: str) -> StrategicPlan | None:
        if not self._flags.planner:
            return None
        return await self._strategic_planner.create_plan(task_profile, user_query)

    async def _seed_memory_hierarchy(
        self,
        *,
        user_query: str,
        history: list[dict[str, str]] | None,
    ) -> None:
        """Seed the Step 16 memory hierarchy with the current request.

        Only fires when ``AETHERIS_ENABLE_CONTEXT`` is on and a hierarchy
        is wired. Failures are logged and swallowed (ADR-007).
        """

        if not self._flags.context or self._memory_hierarchy is None:
            return

        try:
            query_key = MemoryHierarchy.build_key("request", user_query)
            await self._memory_hierarchy.write(
                MemoryEntry(
                    key=query_key,
                    content=user_query,
                    layer="short_term",
                    tags=["request"],
                    source="user_query",
                )
            )
        except Exception as exc:  # ponytail: ADR-007
            LOGGER.warning(
                "memory hierarchy seed failed: %s", exc, exc_info=False
            )

        if not history:
            return
        try:
            for message in history[-4:]:
                content = str(message.get("content", ""))
                if not content:
                    continue
                role = str(message.get("role", "user"))
                key = MemoryHierarchy.build_key("turn", role, content[:128])
                await self._memory_hierarchy.write(
                    MemoryEntry(
                        key=key,
                        content=content,
                        layer="short_term",
                        tags=[role, "history"],
                        source="conversation_history",
                    )
                )
        except Exception as exc:  # ponytail: ADR-007
            LOGGER.warning(
                "memory hierarchy history seed failed: %s", exc, exc_info=False
            )

    @staticmethod
    def _make_node_executor(
        *,
        passport: ExecutionPassport | None,
        context_manager: ContextManager,
        context_enabled: bool,
        user_query: str,
        task_profile: TaskProfile,
        strategic_plan: StrategicPlan | None,
        history: list[dict[str, str]] | None,
        history_summary: str | None,
        budget: PipelineBudget,
        meta_reasoner: MetaReasoner,
        mutation_audit_trail: list[Any],
        rag_enabled: bool = False,
        uncertainty_triggered_retrieval: bool = False,
        gateway: Any,
        strategy: Any,
        pool: Any,
        resource_manager: ResourceManager,
        initial_used_tokens: int,
        runtime_engine: Any | None,
    ):
        budget_lock = asyncio.Lock()
        reserved_tokens = initial_used_tokens

        def _normalize_response(raw: Any) -> str:
            if not isinstance(raw, str):
                return str(raw)
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return raw
            if isinstance(parsed, dict):
                for key in ("final_answer", "answer", "result", "content"):
                    if parsed.get(key) is not None:
                        return str(parsed[key])
            return raw

        async def execute_node(node, prior_results: dict[str, Any]) -> dict[str, Any]:
            if passport is not None:
                passport.update_stage(f"node:{node.task_id}")
                passport.add_checkpoint(node.task_id)
            retrieval_result = None
            if context_enabled and rag_enabled:
                context_window = await context_manager.assemble_window(
                    node,
                    user_query=user_query,
                    task_profile=task_profile,
                    strategic_plan=strategic_plan,
                    history=history,
                    history_summary=history_summary,
                    prior_results=prior_results,
                    budget=budget,
                    uncertainty_triggered_retrieval=uncertainty_triggered_retrieval,
                )
                retrieval_result = context_window.retrieval_result
            elif context_enabled:
                context_window = await context_manager.assemble_window(
                    node,
                    user_query=user_query,
                    task_profile=task_profile,
                    strategic_plan=strategic_plan,
                    history=history,
                    history_summary=history_summary,
                    prior_results=prior_results,
                    budget=budget,
                )
            else:
                context_window = context_manager.minimal_window(
                    node,
                    user_query=user_query,
                    task_profile=task_profile,
                    strategic_plan=strategic_plan,
                    history=history,
                    prior_results=prior_results,
                )
            # Step 22: contract validation makes nodes interchangeable (RFC-003 §3.4).
            # Aggregate upstream produced_outputs into the incoming field set.
            incoming: dict[str, Any] = {}
            for prior in prior_results.values():
                if isinstance(prior, dict):
                    incoming.update(prior.get("produced_outputs", {}))
            input_violations = validate_inputs(node, incoming)
            if input_violations:
                fields = ", ".join(violation.field for violation in input_violations)
                raise ValueError(f"Node {node.task_id} missing required inputs: {fields}")

            expected_tokens = max(1, node.expected_tokens or 256)
            nonlocal reserved_tokens
            async with budget_lock:
                if reserved_tokens + expected_tokens > budget.total_tokens:
                    raise RuntimeError(f"Node {node.task_id} exceeds token budget")
                reserved_tokens += expected_tokens

            reservation = await resource_manager.acquire(node)
            if not reservation.granted:
                async with budget_lock:
                    reserved_tokens -= expected_tokens
                raise RuntimeError(
                    f"Node {node.task_id} rejected by resource manager: {reservation.reason}"
                )
            try:
                if node.task_id == "classify" and node.output_contract is not None:
                    raw_response = task_profile.model_dump_json()
                    response_text = task_profile.model_dump_json()
                else:
                    upstream = {
                        key: value
                        for key, value in incoming.items()
                        if key not in {"task_profile", "strategic_plan"}
                    }
                    prompt = (
                        f"User request:\n{user_query}\n\n"
                        f"Current task:\n{node.objective}\n\n"
                        f"Upstream results:\n{json.dumps(upstream, default=str)}"
                    )
                    role = "judge" if node.task_id == "final" else "generation"
                    # Ask for exactly the declared contract keys so a merged
                    # node (MetaReasoner union contracts) is satisfiable by an
                    # instruction-following model — the contract layer checks
                    # the same keys it requests.
                    output_keys = (
                        ", ".join(node.output_contract.produced_fields)
                        if node.output_contract is not None
                        else "result, answer, or final_answer"
                    )
                    call_kwargs = {
                        "prompt": prompt,
                        "role": role,
                        "strategy": strategy,
                        "pool": pool,
                        "system_prompt": (
                            "Execute only the current DAG task. Use supplied upstream results. "
                            f"Return a JSON object with exactly these keys: {output_keys}."
                        ),
                        "history": history,
                        "passport": passport,
                    }
                    if runtime_engine is not None and passport is not None:
                        raw_response = await runtime_engine.execute_with_contracts(
                            prompt=prompt,
                            system_prompt=call_kwargs["system_prompt"],
                            role=role,
                            passport=passport,
                            gateway=gateway,
                            strategy=strategy,
                            pool=pool,
                            history=history,
                        )
                    else:
                        raw_response = await gateway.execute_with_fallback(**call_kwargs)
                    response_text = _normalize_response(raw_response)
            finally:
                await resource_manager.release(reservation)

            # Stage 2: token accounting uses the provider-reported usage for
            # this call when available; the len//4 estimate is a labelled
            # fallback for providers that return no usage block.
            usage = get_last_provider_usage()
            node_measured_cost = 0.0
            if usage and not usage.get("estimated"):
                actual_tokens = max(
                    1,
                    int(usage.get("prompt_tokens", 0))
                    + int(usage.get("completion_tokens", 0)),
                )
                node_measured_cost = estimate_cost_usd(
                    str(usage.get("model", "")),
                    int(usage.get("prompt_tokens", 0)),
                    int(usage.get("completion_tokens", 0)),
                )
            else:
                actual_tokens = max(1, len(response_text) // 4)
            async with budget_lock:
                reserved_tokens += actual_tokens - expected_tokens
                if reserved_tokens > budget.total_tokens:
                    raise RuntimeError(f"Node {node.task_id} exhausted token budget")

            fields = node.output_contract.produced_fields if node.output_contract else ["result"]
            produced_outputs = populate_contract_fields(raw_response, response_text, fields)
            output_violations = validate_outputs(node, produced_outputs)
            if output_violations:
                fields = ", ".join(violation.field for violation in output_violations)
                raise ValueError(f"Node {node.task_id} produced invalid outputs: {fields}")

            recheck = meta_reasoner.node_completed_recheck(
                node,
                prior_results=prior_results,
            )
            if recheck is not None:
                mutation_audit_trail.append(recheck)
            await asyncio.sleep(0)
            return {
                "task_id": node.task_id,
                "objective": node.objective,
                "depends_on": list(node.depends_on),
                "inputs_seen": sorted(prior_results.keys()),
                "context_window": context_window,
                "retrieval_result": retrieval_result,
                "produced_outputs": produced_outputs,
                "contract_violations": [],
                "actual_tokens": actual_tokens,
                "measured_cost_usd": round(node_measured_cost, 6),
                **produced_outputs,
            }

        return execute_node

    @staticmethod
    def _emit(recorder: ReplayRecorder | None, event_type: str, **kwargs: Any) -> None:
        """Emit a replay event, best-effort. Never raises into the request
        path (ADR-007) — a recorder failure logs and is swallowed."""
        if recorder is None:
            return
        try:
            recorder.emit(event_type, **kwargs)
        except Exception as exc:  # ponytail: ADR-007
            LOGGER.warning("replay emit failed for %s: %s", event_type, exc, exc_info=False)

    def _finalize_replay(
        self,
        recorder: ReplayRecorder | None,
        *,
        graph: Any,
        prompt_fingerprint_value: str,
        task_profile: Any,
        strategic_plan: Any,
        resource_snapshot: dict[str, Any] | None,
        prediction_actual: dict[str, Any] | None,
        final_outcome: dict[str, Any] | None,
        manifest: Any,
    ) -> str | None:
        """Finalize + persist a trace. Returns the ``trace_id`` or ``None``.

        Best-effort: any failure logs and degrades to no trace (ADR-007).
        """
        if recorder is None or self._replay_store is None:
            return None
        try:
            trace = recorder.finalize(
                graph_version=getattr(graph, "graph_version", None),
                prompt_fingerprint_value=prompt_fingerprint_value,
                task_profile=task_profile.model_dump(mode="json") if task_profile is not None else None,
                strategic_plan=strategic_plan.model_dump(mode="json") if strategic_plan is not None else None,
                task_graph=graph.model_dump(mode="json") if hasattr(graph, "model_dump") else None,
                resource_snapshot_at_start=resource_snapshot,
                prediction_actual=prediction_actual,
                final_outcome=final_outcome,
                manifest=manifest.model_dump(mode="json") if hasattr(manifest, "model_dump") else None,
                retention_days=self._replay_store.retention_days,
            )
            self._replay_store.record(trace)
            return trace.trace_id
        except Exception as exc:  # ponytail: ADR-007
            LOGGER.warning("replay finalize failed: %s", exc, exc_info=False)
            return None

    @staticmethod
    def _assemble_dashboard_metrics(*sources: dict[str, Any] | None) -> dict[str, Any]:
        """Merge per-namespace metric dicts onto the RFC-005 §4.1 template so
        every example key is present (None = not sourced yet), never silently
        omitted.
        """
        merged = dict(_DASHBOARD_METRIC_TEMPLATE)
        for source in sources:
            if source:
                merged.update(source)
        return merged

    @staticmethod
    def _aggregate_rag_telemetry(
        *,
        results: dict[str, Any],
        uncertainty_triggered: bool,
    ) -> dict[str, Any]:
        """Aggregate per-node retrieval results into a single telemetry block.

        Step 15 contract: emit RAG telemetry in the ``execution.*`` /
        ``planner.*`` namespaces (RFC-005 §4). When the flag is off or no
        node ran a retrieval call, return a ``status="disabled"`` block —
        never fabricated evidence.
        """

        per_node: list[dict[str, Any]] = []
        attempted = 0
        skipped = 0
        selected_total = 0
        evidence_bump_total = 0
        weights_summary: dict[str, float] | None = None
        for node_id, result in results.items():
            retrieval_result = result.get("retrieval_result") if isinstance(result, dict) else None
            if retrieval_result is None:
                skipped += 1
                continue
            attempted += 1
            selected_total += getattr(retrieval_result, "selected_count", 0)
            evidence_bump_total += getattr(retrieval_result, "evidence_bump", 0)
            if weights_summary is None:
                weights_candidate = getattr(retrieval_result, "weights", None)
                if isinstance(weights_candidate, dict) and weights_candidate:
                    weights_summary = dict(weights_candidate)
            per_node.append(
                {
                    "node_id": node_id,
                    "retrieval_attempted": bool(getattr(retrieval_result, "retrieval_attempted", False)),
                    "selected_count": int(getattr(retrieval_result, "selected_count", 0)),
                    "route_gating": getattr(retrieval_result, "route_gating", "off"),
                    "skipped_reason": getattr(retrieval_result, "retrieval_skipped_reason", None),
                    "evidence_bump": int(getattr(retrieval_result, "evidence_bump", 0)),
                }
            )
        status = "ok" if attempted else "disabled"
        if not results:
            status = "disabled"
        return {
            "status": status,
            "uncertainty_triggered": bool(uncertainty_triggered),
            "nodes_attempted": attempted,
            "nodes_skipped": skipped,
            "selected_total": selected_total,
            "evidence_bump_total": evidence_bump_total,
            "weights": weights_summary,
            "per_node": per_node,
        }
