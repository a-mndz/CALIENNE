"""
aetheris — Adaptive Multi-Model Reasoning Orchestrator
Pipeline: Micro-Mode execution path.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, TypedDict

from agents.prompt_utils import (
    build_decision_dict,
    complete_conversation_session,
    init_conversation_context,
    record_user_query,
)
from api_gateway.rate_limiter import AsyncAPIGateway, ProviderPool
from api_gateway.strategy import ProviderStrategy
from core.passport import ExecutionPassport
from core.schemas import AgentOutput
from orchestrator.claims import ClaimManager
from orchestrator.feature_flags import FeatureFlags, load_flags
from orchestrator.knowledge_layer import KnowledgeLayer
from orchestrator.memory import epistemic_memory
from orchestrator.reasoning_layer import ReasoningLayer
from orchestrator.retrieval import RetrievalService, load_route_gating, load_routing_weights
from orchestrator.routing import IntentAnalyzer
from orchestrator.validation_layer import ValidationLayer

logger = logging.getLogger(__name__)


# ── Phase 1 Configuration Knobs ─────────────────────────────────────────


_DISABLE_CLAIMS_ENV = "aetheris_DISABLE_CLAIM_EXTRACTION"


def _is_claim_extraction_enabled() -> bool:
    """Emergency bypass for the hallucination firewall.

    Step 14 upgrades claim validation from a placeholder to a deterministic
    evidence checker, so the firewall is enabled by default. Operators may use
    the existing env var as an emergency kill switch if validation itself is
    implicated in an incident.
    """
    raw = os.environ.get(_DISABLE_CLAIMS_ENV, "0").strip().lower()
    return raw not in {"1", "true", "yes", "on"}


# ── Result Types ─────────────────────────────────────────────────────────

class MicroModeResult(TypedDict, total=False):
    status: str
    winning_answer: str
    validation_score: float
    confidence_delta: float
    judge_decision: dict[str, Any] | None
    logician_output: AgentOutput | dict[str, Any] | None
    creative_output: AgentOutput | dict[str, Any] | None
    unverified_claims: list[dict[str, Any]]
    firewall_result: dict[str, Any] | None
    conversation_metadata: dict[str, Any] | None
    passport: dict[str, Any] | None


# ── Conversation FAILED State Helpers (MED-004 / MED-016) ────────────────

def _mark_conversation_failed(
    conversation_director: Any | None,
    session_id: str | None,
) -> dict[str, Any] | None:
    """Transition a session to FAILED and refresh metadata.

    Replaces the nine identical try/except blocks that previously appeared in
    every error/abort path of the pipeline.  Returns the refreshed metadata
    (or ``None`` when unavailable) so callers can swap it in a single line.
    """
    if conversation_director is None or not session_id:
        return None
    try:
        from orchestrator.conversation import ConversationState
        conversation_director.transition_state(session_id, ConversationState.FAILED)
        return conversation_director.get_metadata(session_id)
    except Exception as exc:
        logger.debug("Failed to mark conversation %s as FAILED: %s", session_id, exc)
        return None


# ── Prompt Assembly ──────────────────────────────────────────────────────

# Agent prompts are passed as separate system_prompt + prompt
# to the gateway, which sends them as distinct messages (role=system, role=user).
# This structural boundary reduces prompt-injection risk: the user query is a
# separate message object rather than text interpolated into the system prompt.


# ── Pipeline ─────────────────────────────────────────────────────────────

async def run_micro_mode(
    user_query: str,
    gateway: AsyncAPIGateway,
    strategy: ProviderStrategy,
    pool: ProviderPool,
    history: list[dict[str, str]] | None = None,
    passport: ExecutionPassport | None = None,
    decision_engine: Any | None = None,
    reasoning_graph: Any | None = None,
    claim_manager: Any | None = None,
    streaming_manager: Any | None = None,
    conversation_director: Any | None = None,
    session_id: str | None = None,
    flags: FeatureFlags | None = None,
    user_id: str | None = None,
) -> MicroModeResult:
    """
    Execute the **micro-mode** pipeline.

    When *decision_engine* is provided the pipeline delegates gate and
    generation logic to the :class:`DecisionEngine` instead of running
    inline Breaker/parallel-generation code.  An optional *passport*
    tracks the request lifecycle across all components. *user_id*
    (authenticated user's email, when available) scopes failure-memory
    access so lessons never cross accounts.
    """
    logger.info("Micro-mode pipeline started for query: %.120s", user_query)
    claim_manager = claim_manager or ClaimManager()

    # ── Conversation context (Task 21.5) ────────────────────────────
    stored_history, conversation_metadata = init_conversation_context(
        conversation_director, session_id, logger, owner_email=user_id
    )
    if stored_history:
        history = stored_history
    record_user_query(conversation_director, session_id, user_query, logger)

    # Track start time for passport timeout enforcement
    import time as _time
    _pipeline_start = _time.monotonic()

    # ── Use DecisionEngine when available (Task 21.3) ────────────────
    if decision_engine is not None:
        return await _run_with_decision_engine(
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
            conversation_metadata=conversation_metadata,
            flags=flags,
            user_id=user_id,
        )

    # CRIT-001: the DecisionEngine path is the sole execution path.
    raise RuntimeError(
        "CRIT-001: a decision_engine is required. The DecisionEngine path is "
        "the sole execution entry point; the legacy inline pipeline was removed."
    )


def _build_frontend_payload(result: MicroModeResult) -> dict[str, Any]:
    """Convert a MicroModeResult into the shape the frontend expects.

    Deep-copies before mutating: normalising score_a/score_b in place would
    corrupt the shared judge_decision dict for replay stores and passports
    that hold a reference to the same object.
    """
    import copy
    import re

    serialized: dict[str, Any] = copy.deepcopy(dict(result))
    for key in ("logician_output", "creative_output"):
        val = serialized.get(key)
        if val is not None and hasattr(val, "model_dump"):
            serialized[key] = val.model_dump()

    decision = serialized.get("judge_decision")
    bias_risk = "Unknown"
    if decision:
        if "justification" in decision:
            m = re.search(r"Bias Risk:\s*(.*?)\s*\|", decision["justification"])
            if m:
                bias_risk = m.group(1)
        if "score_a" in decision and decision["score_a"] is not None:
            decision["score_a"] = decision["score_a"] / 10.0
        if "score_b" in decision and decision["score_b"] is not None:
            decision["score_b"] = decision["score_b"] / 10.0

    validation_score = serialized.get("validation_score")
    confidence_score = (validation_score / 10.0) if validation_score is not None else 0.0

    return {
        "status": serialized.get("status"),
        "answer": serialized.get("winning_answer"),
        "confidence_score": confidence_score,
        "bias_risk": bias_risk,
        "decision": decision,
        "agent_outputs": {
            "logician": serialized.get("logician_output"),
            "creative": serialized.get("creative_output"),
        },
        "metrics": serialized.get("passport"),
    }


# ── Private Helpers ──────────────────────────────────────────────────────

def _ensure_agent_output(
    parsed: AgentOutput | dict[str, Any],
    label: str,
) -> AgentOutput:
    if isinstance(parsed, AgentOutput):
        return parsed

    logger.warning(
        "%s agent output was an error dict — constructing minimal AgentOutput.",
        label,
    )
    return AgentOutput(
        reasoning_steps=parsed.get(
            "reasoning_steps",
            [f"PARSE FAILURE for {label} agent."],
        ),
        answer=parsed.get("answer", f"ERROR: {label} agent output unparsable."),
        confidence=parsed.get("confidence", 0.0),
    )


def _calculate_confidence_delta(
    logician_agent: AgentOutput,
    creative_agent: AgentOutput,
) -> float:
    """Return the absolute difference between Logician and Creative confidence scores."""
    return abs(logician_agent.confidence - creative_agent.confidence)


def _claim_dict(claim: Any) -> dict[str, Any]:
    provenance = getattr(claim, "provenance", {}) or {}
    return {
        "claim_id": claim.claim_id,
        "content": claim.content,
        "claim_type": claim.claim_type.value,
        "confidence": claim.confidence,
        "source_agent": claim.source_agent,
        "validation_status": claim.validation_status.value,
        "evidence": provenance.get("evidence", []),
    }


def _process_claims_for_outputs(
    *,
    claim_manager: ClaimManager,
    outputs: list[tuple[str, Any]],
    user_query: str,
    history: list[dict[str, str]] | None,
    reasoning_graph: Any | None,
) -> list[Any]:
    if not _is_claim_extraction_enabled():
        return []

    evidence = claim_manager.build_evidence(
        user_query=user_query,
        history=history,
        agent_outputs={
            agent_name: agent_output
            for agent_name, agent_output in outputs
            if agent_output is not None
        },
    )
    all_claims: list[Any] = []
    timestamp = datetime.now(timezone.utc)

    for agent_name, agent_output in outputs:
        answer_text = ""
        if agent_output is not None:
            if hasattr(agent_output, "answer"):
                answer_text = agent_output.answer
            elif isinstance(agent_output, dict):
                answer_text = agent_output.get("answer", "")
        if not answer_text:
            continue
        extracted = claim_manager.extract_claims(answer_text, agent_name)
        for claim in extracted:
            supporting_evidence = [record for record in evidence if record.source_id != agent_name]
            claim_manager.validate_claim(claim, supporting_evidence)
            if reasoning_graph is not None:
                claim_manager.store_claim(claim, reasoning_graph)
            claim_manager.track_claim_provenance(
                claim,
                source=agent_name,
                timestamp=timestamp,
                validation_method="evidence_checker",
            )
        all_claims.extend(extracted)

    return all_claims


def _apply_output_firewall(
    *,
    claim_manager: ClaimManager,
    final_text: str,
    user_query: str,
    history: list[dict[str, str]] | None,
    agent_outputs: dict[str, Any],
    reasoning_graph: Any | None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    if not _is_claim_extraction_enabled():
        return final_text, [], None

    evidence = claim_manager.build_evidence(
        user_query=user_query,
        history=history,
        agent_outputs=agent_outputs,
    )
    firewall_result = claim_manager.apply_firewall(
        final_text,
        agent_name="judge",
        evidence=[record for record in evidence if record.source_id != "judge"],
    )
    timestamp = datetime.now(timezone.utc)
    for claim in firewall_result.claims:
        if reasoning_graph is not None:
            claim_manager.store_claim(claim, reasoning_graph)
        claim_manager.track_claim_provenance(
            claim,
            source=claim.source_agent,
            timestamp=timestamp,
            validation_method="evidence_checker",
        )

    unsupported = claim_manager.get_unverified_claims(claims=firewall_result.claims)
    result_payload = {
        "original_text": firewall_result.original_text,
        "sanitized_text": firewall_result.sanitized_text,
        "removed_or_qualified_count": firewall_result.removed_or_qualified_count,
        "unsupported_claims": [_claim_dict(claim) for claim in unsupported],
    }
    return firewall_result.sanitized_text, [_claim_dict(claim) for claim in unsupported], result_payload


# ── Decision-Engine Pipeline Path (Task 21.3) ────────────────────────────


async def _run_with_decision_engine(
    *,
    user_query: str,
    gateway: AsyncAPIGateway,
    strategy: ProviderStrategy,
    pool: ProviderPool,
    history: list[dict[str, str]] | None,
    passport: ExecutionPassport | None,
    decision_engine: Any,
    reasoning_graph: Any | None,
    claim_manager: Any | None,
    streaming_manager: Any | None,
    conversation_director: Any | None = None,
    session_id: str | None = None,
    conversation_metadata: dict[str, Any] | None = None,
    flags: FeatureFlags | None = None,
    user_id: str | None = None,
) -> MicroModeResult:
    """Execute the pipeline using the :class:`DecisionEngine` gate architecture.

    This is the Task 21.3 integration path that delegates Breaker,
    generation, and Judge logic to the DecisionEngine while tracking
    state via the ExecutionPassport. *user_id* scopes failure-memory
    writes and reads so one account's lessons never surface for another.
    """
    from orchestrator.streaming import EventType, StreamEvent
    claim_manager = claim_manager or ClaimManager()

    flags = flags or load_flags()
    knowledge = None
    reasoning_layer = None
    validation_layer = None
    layer_history = history
    if flags.knowledge_layer:
        retrieval_service = None
        if flags.rag:
            retrieval_service = RetrievalService(
                weights=load_routing_weights(),
                route_gating=load_route_gating(),
            )
        knowledge = await KnowledgeLayer(retrieval_service).gather(
            query=user_query,
            task_profile=IntentAnalyzer.classify(user_query),
            history=history,
            reasoning_graph=reasoning_graph,
        )
        reasoning_layer = ReasoningLayer(decision_engine)
        validation_layer = ValidationLayer(claim_manager)
        layer_history = knowledge.reasoning_history()

    # ── Step 1: Breaker gate ─────────────────────────────────────────
    logger.info("Step 1/4 — Breaker gate (DecisionEngine, timeout=%dms).",
                decision_engine.BREAKER_TIMEOUT_MS)

    if passport is not None:
        passport.update_stage("breaker")

    if streaming_manager is not None and passport is not None:
        await streaming_manager.emit(
            passport.request_id,
            EventType.AGENT_STARTED,
            {"agent_name": "Breaker", "request_id": passport.request_id},
        )

    if reasoning_layer is not None and knowledge is not None:
        should_continue, breaker_output = await reasoning_layer.run_breaker(
            knowledge=knowledge,
            gateway=gateway,
            strategy=strategy,
            pool=pool,
            passport=passport or _null_passport(),
        )
    else:
        should_continue, breaker_output = await decision_engine.execute_breaker_gate(
            query=user_query,
            gateway=gateway,
            strategy=strategy,
            pool=pool,
            passport=passport or _null_passport(),
            history=history,
        )

    if passport is not None and breaker_output is not None:
        passport.add_agent_output("breaker", breaker_output)

    if streaming_manager is not None and passport is not None:
        await streaming_manager.emit(
            passport.request_id,
            EventType.AGENT_COMPLETED,
            {"agent_name": "Breaker", "request_id": passport.request_id},
        )

    if not should_continue:
        reason = (
            breaker_output.answer
            if breaker_output is not None
            else "Breaker gate failed (timeout or error)"
        )
        logger.warning("Breaker gate ABORTED pipeline: %s", reason)
        if passport is not None:
            passport.update_stage("aborted")
        # Transition conversation state to FAILED on abort
        refreshed = _mark_conversation_failed(conversation_director, session_id)
        if refreshed is not None:
            conversation_metadata = refreshed
        return MicroModeResult(
            status="aborted",
            winning_answer=reason,
            validation_score=0.0,
            confidence_delta=0.0,
            judge_decision=None,
            logician_output=None,
            creative_output=None,
            conversation_metadata=conversation_metadata,
            passport=passport.to_dict() if passport is not None else None,
        )

    logger.info("Breaker gate passed — proceeding to generation.")

    # ── Step 2: Parallel Logician + Creative (30s timeout) ───────────
    logger.info("Step 2/4 — Parallel generation (DecisionEngine, timeout=%ds).",
                decision_engine.PARALLEL_AGENT_TIMEOUT_SEC)

    if passport is not None:
        passport.update_stage("generating")

    if streaming_manager is not None and passport is not None:
        await streaming_manager.emit(
            passport.request_id,
            EventType.AGENT_STARTED,
            {"agent_name": "Logician", "request_id": passport.request_id},
        )
        await streaming_manager.emit(
            passport.request_id,
            EventType.AGENT_STARTED,
            {"agent_name": "Creative", "request_id": passport.request_id},
        )

    if reasoning_layer is not None and knowledge is not None:
        logician_output, creative_output = await reasoning_layer.generate(
            knowledge=knowledge,
            gateway=gateway,
            strategy=strategy,
            pool=pool,
            passport=passport or _null_passport(),
        )
    else:
        logician_output, creative_output = await decision_engine.execute_generation_agents(
            query=user_query,
            gateway=gateway,
            strategy=strategy,
            pool=pool,
            passport=passport or _null_passport(),
            history=history,
        )

    # Track agent outputs in passport
    if passport is not None:
        if logician_output is not None:
            passport.add_agent_output("logician", logician_output)
        if creative_output is not None:
            passport.add_agent_output("creative", creative_output)

    if streaming_manager is not None and passport is not None:
        for agent_name in ("Logician", "Creative"):
            await streaming_manager.emit(
                passport.request_id,
                EventType.AGENT_COMPLETED,
                {"agent_name": agent_name, "request_id": passport.request_id},
            )

    # Both agents failed — abort
    if logician_output is None and creative_output is None:
        logger.error("Both Logician and Creative agents failed.")
        if passport is not None:
            passport.record_error("generation", "Both Logician and Creative agents failed")
            passport.update_stage("failed")
        # Transition conversation state to FAILED
        refreshed = _mark_conversation_failed(conversation_director, session_id)
        if refreshed is not None:
            conversation_metadata = refreshed
        return MicroModeResult(
            status="error",
            winning_answer="Both generation agents failed to produce valid output.",
            validation_score=0.0,
            confidence_delta=0.0,
            judge_decision=None,
            logician_output=None,
            creative_output=None,
            conversation_metadata=conversation_metadata,
            passport=passport.to_dict() if passport is not None else None,
        )

    # ── Step 3: Judge synthesis ──────────────────────────────────────
    logger.info("Step 3/4 — Judge synthesis (DecisionEngine).")

    if passport is not None:
        passport.update_stage("evaluating")

    # Retrieve failure patterns from reasoning graph
    owner = user_id or ""
    lessons = knowledge.lessons if knowledge is not None else ""
    if knowledge is None:
        if reasoning_graph is not None:
            patterns = reasoning_graph.get_failure_patterns(user_query, owner=owner)
            if patterns:
                lesson_parts = [
                    f"Past failure for similar query: {p.get('explanation', '')} "
                    f"(score={p.get('score', 0.0)})"
                    for p in patterns[:3]
                ]
                lessons = "; ".join(lesson_parts)
                logger.info(
                    "Retrieved %d failure pattern(s) from reasoning graph.",
                    len(patterns),
                )
        em_lessons = epistemic_memory.get_lessons_learned(user_query, owner=owner)
        if em_lessons:
            lessons = f"{lessons}; {em_lessons}" if lessons else em_lessons

    if streaming_manager is not None and passport is not None:
        await streaming_manager.emit(
            passport.request_id,
            EventType.AGENT_STARTED,
            {"agent_name": "Judge", "request_id": passport.request_id},
        )

    if validation_layer is not None and knowledge is not None:
        final_output = await validation_layer.judge(
            decision_engine=decision_engine,
            knowledge=knowledge,
            logician_output=logician_output,
            creative_output=creative_output,
            gateway=gateway,
            strategy=strategy,
            pool=pool,
            passport=passport or _null_passport(),
        )
    else:
        final_output = await decision_engine.execute_judge_synthesis(
            query=user_query,
            logician_output=logician_output,
            creative_output=creative_output,
            gateway=gateway,
            strategy=strategy,
            pool=pool,
            passport=passport or _null_passport(),
            lessons=lessons,
            history=history,
        )

    if passport is not None:
        passport.add_agent_output("judge", final_output)

    if streaming_manager is not None and passport is not None:
        await streaming_manager.emit(
            passport.request_id,
            EventType.AGENT_COMPLETED,
            {"agent_name": "Judge", "request_id": passport.request_id},
        )

    # Record failure pattern in reasoning graph for low scores
    if final_output.validation_score < 7.0:
        logger.warning(
            "Low validation score (%f) — recording failure pattern.",
            final_output.validation_score,
        )
        epistemic_memory.record_failure(
            query=user_query,
            explanation=(
                ", ".join(final_output.disagreement_notes)
                or "Low validation score."
            ),
            score=final_output.validation_score,
            owner=owner,
        )
        if reasoning_graph is not None:
            agent_outputs = {}
            if logician_output is not None:
                agent_outputs["logician"] = (
                    logician_output.model_dump()
                    if hasattr(logician_output, "model_dump")
                    else str(logician_output)
                )
            if creative_output is not None:
                agent_outputs["creative"] = (
                    creative_output.model_dump()
                    if hasattr(creative_output, "model_dump")
                    else str(creative_output)
                )
            reasoning_graph.record_failure_pattern(
                query=user_query,
                explanation=(
                    ", ".join(final_output.disagreement_notes)
                    or "Low validation score."
                ),
                score=final_output.validation_score,
                agent_outputs=agent_outputs,
                owner=owner,
            )

    # ── Step 4: Assemble result ──────────────────────────────────────
    logger.info("Step 4/4 — Assembling final micro-mode result.")

    if passport is not None:
        passport.update_stage("completed")

    logician_agent = _ensure_agent_output(
        logician_output, "Logician"
    ) if logician_output is not None else AgentOutput(
        reasoning_steps=[], answer="", confidence=0.0,
    )
    creative_agent = _ensure_agent_output(
        creative_output, "Creative"
    ) if creative_output is not None else AgentOutput(
        reasoning_steps=[], answer="", confidence=0.0,
    )

    decision_dict = build_decision_dict(
        logician_agent.confidence,
        creative_agent.confidence,
        final_output.overall_confidence,
        final_output.overall_bias_risk,
        final_output.disagreement_notes,
    )

    confidence_delta = _calculate_confidence_delta(logician_agent, creative_agent)

    outputs = [
        ("breaker", breaker_output),
        ("logician", logician_output),
        ("creative", creative_output),
        ("judge", final_output),
    ]
    agent_outputs = dict(outputs)
    if validation_layer is not None:
        all_claims = validation_layer.process_claims(
            outputs=outputs,
            user_query=user_query,
            history=layer_history,
            reasoning_graph=reasoning_graph,
            enabled=_is_claim_extraction_enabled(),
        )
        final_answer, unverified_dicts, firewall_result = validation_layer.apply_firewall(
            final_text=final_output.final_answer,
            user_query=user_query,
            history=layer_history,
            agent_outputs=agent_outputs,
            reasoning_graph=reasoning_graph,
            enabled=_is_claim_extraction_enabled(),
        )
    else:
        all_claims = _process_claims_for_outputs(
            claim_manager=claim_manager,
            outputs=outputs,
            user_query=user_query,
            history=history,
            reasoning_graph=reasoning_graph,
        )
        final_answer, unverified_dicts, firewall_result = _apply_output_firewall(
            claim_manager=claim_manager,
            final_text=final_output.final_answer,
            user_query=user_query,
            history=history,
            agent_outputs=agent_outputs,
            reasoning_graph=reasoning_graph,
        )
    final_output.final_answer = final_answer

    unverified = claim_manager.get_unverified_claims(claims=all_claims)
    seen_claim_ids = {entry["claim_id"] for entry in unverified_dicts}
    for claim in unverified:
        if claim.claim_id not in seen_claim_ids:
            unverified_dicts.append(_claim_dict(claim))
            seen_claim_ids.add(claim.claim_id)

    if unverified and passport is not None:
        for c in unverified:
            passport.record_warning(
                f"Unverified claim from {c.source_agent}: {c.content[:100]}"
            )
    if firewall_result is not None and firewall_result["removed_or_qualified_count"] > 0:
        final_output.disagreement_notes.append(
            f"Hallucination firewall qualified {firewall_result['removed_or_qualified_count']} unsupported claim(s)."  # noqa: E501
        )

    # ── Conversation completion (Task 21.5) ─────────────────────────
    conversation_metadata = complete_conversation_session(
        conversation_director, session_id, final_output.final_answer, "completed", logger
    ) or conversation_metadata

    return MicroModeResult(
        status="success",
        winning_answer=final_output.final_answer,
        validation_score=final_output.validation_score,
        confidence_delta=confidence_delta,
        judge_decision=decision_dict,
        logician_output=logician_output,
        creative_output=creative_output,
        unverified_claims=unverified_dicts,
        firewall_result=firewall_result,
        conversation_metadata=conversation_metadata,
        passport=passport.to_dict() if passport is not None else None,
    )


def _null_passport() -> ExecutionPassport:
    """Return a throwaway passport for DecisionEngine calls when none is supplied."""
    return ExecutionPassport()
