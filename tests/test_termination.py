"""Unit tests for composable termination conditions."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.schemas import PipelineBudget
from orchestrator.budget import RepairBudgetDecision, TokenBudgetManager
from orchestrator.repair import Defect, RepairResult, run_repair_loop
from orchestrator.termination import (
    BaseTermination,
    BudgetExhausted,
    MaxRepairsReached,
    _Composed,
)

pytestmark = pytest.mark.unit


class _SpyTermination:
    def __init__(self, is_met_result: bool, reason: str) -> None:
        self._is_met_result = is_met_result
        self._reason = reason
        self.call_count = 0

    @property
    def reason(self) -> str:
        return self._reason

    def is_met(self, cycle: int = 0, tokens_spent: int = 0, attempts: int = 0) -> bool:
        self.call_count += 1
        return self._is_met_result

    def __or__(self, other: BaseTermination) -> _Composed:
        return _Composed(self, other, op="OR")

    def __and__(self, other: BaseTermination) -> _Composed:
        return _Composed(self, other, op="AND")


def test_or_short_circuits() -> None:
    t1 = _SpyTermination(False, "t1 reason")
    t2 = _SpyTermination(True, "t2 reason")
    t3 = _SpyTermination(True, "t3 reason")

    composed = t1 | t2 | t3
    assert composed.is_met() is True
    assert composed.reason == "t2 reason"
    assert t1.call_count == 1
    assert t2.call_count == 1
    assert t3.call_count == 0  # Short-circuited after t2


def test_and_short_circuits() -> None:
    t1 = _SpyTermination(True, "t1 reason")
    t2 = _SpyTermination(False, "t2 reason")
    t3 = _SpyTermination(True, "t3 reason")

    composed = t1 & t2 & t3
    assert composed.is_met() is False
    assert composed.reason == "t2 reason"
    assert t1.call_count == 1
    assert t2.call_count == 1
    assert t3.call_count == 0  # Short-circuited after t2


def test_budget_exhausted_truth_table() -> None:
    budget = PipelineBudget(total_tokens=1000, strategy="balanced")
    mock_mgr = MagicMock(spec=TokenBudgetManager)

    # 1. Under budget, no attempts
    mock_mgr.evaluate_repair_cycle.return_value = RepairBudgetDecision(
        allowed=True,
        reason="repair budget available",
        remaining_critique_repair_tokens=200,
        estimated_repair_tokens=100,
        pressure="normal",
    )
    b1 = BudgetExhausted(mock_mgr, budget=budget, estimated_repair_tokens=100, used_total_tokens=200)
    assert b1.is_met(cycle=1, tokens_spent=0, attempts=0) is False
    assert b1.reason == "repair budget available"

    # 2. Over budget / exhausted, no attempts
    mock_mgr.evaluate_repair_cycle.return_value = RepairBudgetDecision(
        allowed=False,
        reason="budget exhausted; synthesize from verified state",
        remaining_critique_repair_tokens=0,
        estimated_repair_tokens=100,
        pressure="exhausted",
    )
    b2 = BudgetExhausted(mock_mgr, budget=budget, estimated_repair_tokens=100, used_total_tokens=950)
    assert b2.is_met(cycle=1, tokens_spent=0, attempts=0) is True
    assert b2.reason == "budget exhausted; synthesize from verified state"

    # 3. Under budget, with attempts
    mock_mgr.evaluate_repair_cycle.return_value = RepairBudgetDecision(
        allowed=True,
        reason="repair budget available",
        remaining_critique_repair_tokens=150,
        estimated_repair_tokens=100,
        pressure="normal",
    )
    b3 = BudgetExhausted(mock_mgr, budget=budget, estimated_repair_tokens=100, used_total_tokens=500)
    assert b3.is_met(cycle=2, tokens_spent=100, attempts=1) is False

    # 4. Exceeds critique budget, with attempts
    mock_mgr.evaluate_repair_cycle.return_value = RepairBudgetDecision(
        allowed=False,
        reason="repair would exceed the critique / repair budget",
        remaining_critique_repair_tokens=50,
        estimated_repair_tokens=100,
        pressure="tight",
    )
    b4 = BudgetExhausted(mock_mgr, budget=budget, estimated_repair_tokens=100, used_total_tokens=700)
    assert b4.is_met(cycle=2, tokens_spent=200, attempts=1) is True
    assert b4.reason == "repair would exceed the critique / repair budget"


def test_repair_loop_uses_composed_stop() -> None:
    budget = PipelineBudget(total_tokens=500, strategy="balanced")
    budget_manager = TokenBudgetManager()
    defects = [Defect(kind="contradiction", description="two facts conflict")]

    # Set up budget so it triggers budget exhaustion on repair evaluation
    result = run_repair_loop(
        generated_output="flawed output",
        judge_defects=defects,
        budget=budget,
        budget_manager=budget_manager,
        max_repairs=2,
        used_total_tokens=600,  # exceeds 500 total tokens
    )

    assert isinstance(result, RepairResult)
    assert result.bypassed is True
    assert "budget" in result.bypass_reason.lower()
    assert any("Repair cycle 1 skipped" in c for c in result.caveats)
