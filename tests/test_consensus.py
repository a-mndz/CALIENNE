"""Step 12 exit gate: weighted consensus + dynamic judge allocation (RFC-003 §8/§10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.consensus import (
    JudgeOutput,
    allocate_judges,
    compute_consensus,
)
from orchestrator.execution_manager import ExecutionManager
from orchestrator.feature_flags import FeatureFlags


@pytest.fixture
def caps_file():
    # ponytail: tmp_path fixture is broken on this Windows runner (WinError 5),
    # so write beside the test and clean up. Upgrade path: drop when the CI
    # tmp dir permission issue is fixed.
    written: list[Path] = []

    def _write(caps: dict) -> Path:
        path = Path(__file__).parent / f"_caps_{len(written)}.json"
        path.write_text(json.dumps(caps), encoding="utf-8")
        written.append(path)
        return path

    yield _write
    for path in written:
        path.unlink(missing_ok=True)


# ── Dynamic judge allocation (RFC-003 §8) ─────────────────────────────


def test_low_complexity_no_judges_when_early_exit_passes() -> None:
    plan = allocate_judges("low", early_exit_failed=False)
    assert plan.judge_count == 0
    assert plan.requires_consensus is False


def test_complexity_maps_to_judge_count() -> None:
    assert allocate_judges("low", early_exit_failed=True).judge_count == 1
    assert allocate_judges("medium").judge_count == 2
    assert allocate_judges("high").judge_count == 4
    assert allocate_judges("critical").judge_count == 6


def test_multi_judge_requires_consensus_and_capability_weighting() -> None:
    plan = allocate_judges("high")
    assert plan.requires_consensus is True
    assert plan.model_weighting_strategy == "capability_weighted"


def test_coding_route_uses_verifiers_not_creative() -> None:
    plan = allocate_judges("high", task_type="coding")
    assert plan.judge_roles == ["verifier"] * 4


# ── Weighted agreement + minority view (RFC-003 §10) ──────────────────


def test_unanimous_judges_have_full_agreement() -> None:
    judges = [JudgeOutput(model_id=f"j-{i}", claims=["a", "b"], confidence=0.8) for i in range(3)]
    result = compute_consensus(judges, task_type="general")
    assert result.raw_agreement == 1.0
    assert result.minority_views == []
    assert result.minority_should_influence_final is False


def test_weighted_agreement_differs_from_raw_under_capability_weights(caps_file) -> None:
    # Two high-weight models disagree with one low-weight model.
    path = caps_file({
        "version": "1",
        "models": {
            "strong-a": {"weights": {"general": 0.9}},
            "strong-b": {"weights": {"general": 0.9}},
            "weak-c": {"weights": {"general": 0.2}},
        },
    })

    judges = [
        JudgeOutput(model_id="strong-a", claims=["x"], confidence=0.9),
        JudgeOutput(model_id="strong-b", claims=["x"], confidence=0.9),
        JudgeOutput(model_id="weak-c", claims=["y"], confidence=0.4),
    ]
    result = compute_consensus(judges, task_type="general", config_path=path)

    # weak-c is the minority; strong models agree with each other.
    assert result.weighted_agreement != result.raw_agreement
    assert any(mv.model_id == "weak-c" for mv in result.minority_views)


def test_high_weight_minority_flags_influence_on_low_agreement(caps_file) -> None:
    # One high-weight model dissents; overall agreement is low → flag True.
    path = caps_file({
        "version": "1",
        "models": {
            "strong": {"weights": {"general": 0.9}},
            "weak-1": {"weights": {"general": 0.3}},
            "weak-2": {"weights": {"general": 0.3}},
        },
    })

    judges = [
        JudgeOutput(model_id="strong", claims=["truth"], confidence=0.95),
        JudgeOutput(model_id="weak-1", claims=["other"], confidence=0.4),
        JudgeOutput(model_id="weak-2", claims=["another"], confidence=0.4),
    ]
    result = compute_consensus(judges, task_type="general", config_path=path)

    assert result.weighted_agreement < 0.6
    assert result.minority_should_influence_final is True


# ── DAG integration (Step 12 wiring) ──────────────────────────────────


@pytest.mark.asyncio
async def test_execution_manager_consensus_mode_does_not_fabricate_result(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    manager = ExecutionManager(
        flags=FeatureFlags(dag=True, planner=True, consensus=True),
    )
    result = await manager.execute(
        user_query="Design and critically evaluate a complex distributed system architecture.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )

    assert result["status"] == "success"
    assert result["consensus_result"] is None


@pytest.mark.asyncio
async def test_execution_manager_consensus_off_leaves_result_none(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    manager = ExecutionManager(flags=FeatureFlags(dag=True, planner=True, consensus=False))
    result = await manager.execute(
        user_query="Fix the bug in server.py.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )
    assert result["consensus_result"] is None


@pytest.mark.asyncio
async def test_decision_engine_execute_judge_synthesis_high_complexity_consensus(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from core.passport import ExecutionPassport
    from core.schemas import AgentOutput
    from orchestrator.decisions import DecisionEngine
    from orchestrator.streaming import EventType

    engine = DecisionEngine()
    streaming_mock = MagicMock()
    streaming_mock.emit_event = AsyncMock()
    engine.streaming_manager = streaming_mock

    logician = AgentOutput(answer="Premise: X is true. Conclusion: Y is valid.", confidence=0.9)
    creative = AgentOutput(answer="Alternative: X may be false in state Z. Consider W.", confidence=0.8)
    passport = ExecutionPassport()

    result = await engine.execute_judge_synthesis(
        query="Analyze multi-agent Byzantine fault tolerance under partial network partition.",
        logician_output=logician,
        creative_output=creative,
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
        passport=passport,
        complexity="high",
    )

    assert result is not None
    assert result.validation_score >= 0.0
    assert streaming_mock.emit_event.called
    calls = streaming_mock.emit_event.call_args_list
    events = [
        call.kwargs.get("event") or call.args[1]
        for call in calls
        if len(call.args) > 1 or "event" in call.kwargs
    ]
    assert any(getattr(e, "event", None) == EventType.CONSENSUS_COMPUTED for e in events)
