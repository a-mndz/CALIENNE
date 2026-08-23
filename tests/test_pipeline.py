"""Phase 1 — Pipeline subsystem regression tests.

These tests verify the legacy/decision-engine boundary, claim-extraction
toggle, and fire-and-forget task safety added during Phase 1.
Phase 1 implementation files MUST be present for these to pass.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

from orchestrator.decisions import DecisionEngine, DecisionStrategy
from orchestrator.pipelines import run_micro_mode

pytestmark = pytest.mark.unit


def test_legacy_decision_engine_helper_available() -> None:
    """Run-with-decision-engine helper exists and exposes the new safety hook."""
    from orchestrator import pipelines
    assert hasattr(pipelines, "_is_claim_extraction_enabled")
    assert callable(pipelines._is_claim_extraction_enabled)


def test_decision_engine_exposes_safe_task_helper() -> None:
    from orchestrator import decisions
    assert hasattr(decisions, "safe_create_task_broadcast")
    assert callable(decisions.safe_create_task_broadcast)


# ── RFC-007 Step 1 — passport plumbing / telemetry contract ──────────────


class _StubDecisionEngine:
    """Minimal decision-engine stand-in — fixed outputs, no LLM-shaped parsing.

    Builds ``AgentOutput`` via ``orchestrator.pipelines``'s own binding (not a
    fresh ``core.schemas`` import) so this stays correct even if an earlier
    test in the suite reloaded ``core.schemas``/``orchestrator.pipelines``
    (see test_phase2_cleanup.py) and left the two modules' ``AgentOutput``
    classes pointing at different objects.
    """

    BREAKER_TIMEOUT_MS = 100
    PARALLEL_AGENT_TIMEOUT_SEC = 30

    def __init__(self) -> None:
        import orchestrator.pipelines as pipelines_mod
        from core.schemas import calienneOutput

        self._AgentOutput = pipelines_mod.AgentOutput
        self._calienneOutput = calienneOutput

    async def execute_breaker_gate(self, *, query, gateway, strategy, pool, passport, history=None):
        return True, self._AgentOutput(reasoning_steps=["ok"], answer="continue", confidence=0.9)

    async def execute_generation_agents(self, *, query, gateway, strategy, pool, passport, history=None):
        out = self._AgentOutput(reasoning_steps=["ok"], answer="stub", confidence=0.9)
        return out, out

    async def execute_judge_synthesis(
        self, *, query, logician_output, creative_output, gateway, strategy, pool,
        passport, lessons="", history=None,
    ):
        return self._calienneOutput(
            final_answer="stub verdict",
            overall_confidence="High",
            overall_bias_risk="Low",
            disagreement_notes=[],
            validation_score=9.0,
        )


class _UnsupportedClaimDecisionEngine(_StubDecisionEngine):
    async def execute_judge_synthesis(
        self, *, query, logician_output, creative_output, gateway, strategy, pool,
        passport, lessons="", history=None,
    ):
        return self._calienneOutput(
            final_answer="The API timeout is 90 seconds.",
            overall_confidence="High",
            overall_bias_risk="Low",
            disagreement_notes=[],
            validation_score=9.0,
        )


class _HistoryRecordingDecisionEngine(_StubDecisionEngine):
    def __init__(self) -> None:
        super().__init__()
        self.histories = []

    async def execute_breaker_gate(self, **kwargs):
        self.histories.append(kwargs["history"])
        return await super().execute_breaker_gate(**kwargs)

    async def execute_generation_agents(self, **kwargs):
        self.histories.append(kwargs["history"])
        return await super().execute_generation_agents(**kwargs)

    async def execute_judge_synthesis(self, **kwargs):
        self.histories.append(kwargs["history"])
        return await super().execute_judge_synthesis(**kwargs)


@pytest.mark.asyncio
async def test_run_micro_mode_returns_passport_metrics(
    stub_gateway, stub_strategy, stub_pool, stub_streaming
) -> None:
    """A passport supplied to run_micro_mode must come back in the result.

    Regression for the Step-1 bug where server.py created a passport but
    never passed it into run_micro_mode, so the pipeline never mutated it
    and /api/query returned an inert, empty passport snapshot.
    """
    from core.passport import ExecutionPassport
    from orchestrator.pipelines import _build_frontend_payload

    passport = ExecutionPassport()

    result = await run_micro_mode(
        user_query="hello",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
        passport=passport,
        decision_engine=_StubDecisionEngine(),
        streaming_manager=stub_streaming,
    )

    # The pipeline must have mutated the *same* passport instance the
    # caller supplied, and returned its final snapshot as part of the
    # result contract rather than requiring the caller to bolt it on.
    assert passport.execution_state.current_stage == "completed"
    assert result["passport"] == passport.to_dict()

    # Streaming and non-streaming callers both build their response via
    # _build_frontend_payload, so passport metrics must ride along there too.
    payload = _build_frontend_payload(result)
    assert payload["metrics"] == passport.to_dict()


@pytest.mark.asyncio
async def test_run_micro_mode_without_passport_yields_no_metrics(
    stub_gateway, stub_strategy, stub_pool, stub_streaming
) -> None:
    """Omitting a passport is still legal and must not crash the pipeline."""
    from orchestrator.pipelines import _build_frontend_payload

    result = await run_micro_mode(
        user_query="hello",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
        decision_engine=_StubDecisionEngine(),
        streaming_manager=stub_streaming,
    )

    assert result.get("passport") is None
    assert _build_frontend_payload(result)["metrics"] is None


@pytest.mark.asyncio
async def test_run_micro_mode_firewall_qualifies_unsupported_claims(
    stub_gateway, stub_strategy, stub_pool, stub_streaming
) -> None:
    result = await run_micro_mode(
        user_query="What is the configured API timeout?",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
        history=[{"role": "system", "content": "The API timeout is 30 seconds."}],
        decision_engine=_UnsupportedClaimDecisionEngine(),
        streaming_manager=stub_streaming,
    )

    assert "Qualifier:" in result["winning_answer"]
    assert result["firewall_result"]["removed_or_qualified_count"] == 1
    assert result["unverified_claims"][0]["validation_status"] == "unverified"


@pytest.mark.asyncio
async def test_run_micro_mode_preserves_history_and_records_query_once(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    from tests.test_phase2_cleanup import _StubDirector

    director = _StubDirector()
    engine = _HistoryRecordingDecisionEngine()
    supplied_history = [{"role": "user", "content": "Earlier context"}]

    await run_micro_mode(
        user_query="Current question",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
        history=supplied_history,
        decision_engine=engine,
        conversation_director=director,
        session_id="session-1",
    )

    assert engine.histories == [supplied_history, supplied_history, supplied_history]
    history = director.get_history("session-1")
    assert [turn for turn in history if turn["role"] == "user"] == [
        {"role": "user", "content": "Current question"}
    ]
    assert len([turn for turn in history if turn["role"] == "assistant"]) == 1


def test_frontend_payload_uses_canonical_answer_field() -> None:
    from orchestrator.pipelines import _build_frontend_payload

    payload = _build_frontend_payload(
        {
            "status": "success",
            "winning_answer": "Final answer",
            "validation_score": 9.0,
        }
    )

    assert payload["answer"] == "Final answer"
    assert "final_answer" not in payload


@pytest.mark.asyncio
async def test_wired_path_emits_no_answer_prose_before_firewall(
    stub_gateway, stub_strategy, stub_pool, stub_streaming
) -> None:
    """Wired streaming path must not emit answer prose before the firewall.

    The now-deleted ``stream_micro_mode`` generator yielded raw ``draft_answer``
    prose before any verification. The shipped path (run_micro_mode ->
    DecisionEngine) streams progress-only events and exposes the answer only in
    the post-firewall result. Lock that invariant so nobody re-introduces a
    prose emit ahead of ``apply_firewall``.
    """
    from core.passport import ExecutionPassport

    prose = "ZZUNVERIFIEDDRAFTPROSE"

    class _ProseJudge(_StubDecisionEngine):
        async def execute_judge_synthesis(self, **kwargs):
            return self._calienneOutput(
                final_answer=prose,
                overall_confidence="High",
                overall_bias_risk="Low",
                disagreement_notes=[],
                validation_score=9.0,
            )

    result = await run_micro_mode(
        user_query="hello",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
        passport=ExecutionPassport(),
        decision_engine=_ProseJudge(),
        streaming_manager=stub_streaming,
    )

    # Streaming was actually exercised on the wired path.
    assert stub_streaming.events
    # No streamed event leaks the answer prose before the firewall/result.
    for ev in stub_streaming.events:
        assert prose not in str(ev["data"]), f"answer prose leaked before firewall: {ev}"
    # The answer surfaces only in the post-firewall result.
    assert prose in result["winning_answer"]


@pytest.mark.asyncio
async def test_knowledge_layer_flag_preserves_legacy_payload(
    monkeypatch, stub_gateway, stub_strategy, stub_pool, stub_streaming
) -> None:
    monkeypatch.setenv("CALIENNE_ENABLE_KNOWLEDGE_LAYER", "true")
    result = await run_micro_mode(
        user_query="hello",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
        decision_engine=_StubDecisionEngine(),
        streaming_manager=stub_streaming,
    )

    assert result["status"] == "success"
    assert result["winning_answer"] == "stub verdict"
    assert result["validation_score"] == 9.0
    assert result["logician_output"].answer == "stub"
    assert result["creative_output"].answer == "stub"
