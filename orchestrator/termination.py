"""Composable termination conditions for Calienne loops and pipelines."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from orchestrator.budget import PipelineBudget, TokenBudgetManager


@runtime_checkable
class BaseTermination(Protocol):
    """Protocol for termination conditions supporting | (OR) and & (AND) composition."""

    @property
    def reason(self) -> str:
        """Human-readable explanation of why termination was triggered."""
        ...

    def is_met(self, cycle: int = 0, tokens_spent: int = 0, attempts: int = 0) -> bool:
        """Evaluate whether this termination condition is met."""
        ...

    def __or__(self, other: BaseTermination) -> _Composed:
        return _Composed(self, other, op="OR")

    def __and__(self, other: BaseTermination) -> _Composed:
        return _Composed(self, other, op="AND")


class _Composed:
    """Composed termination condition implementing short-circuiting Boolean logic."""

    def __init__(self, left: BaseTermination, right: BaseTermination, op: str) -> None:
        self.left = left
        self.right = right
        self.op = op
        self._reason: str = ""

    @property
    def reason(self) -> str:
        return self._reason

    def is_met(self, cycle: int = 0, tokens_spent: int = 0, attempts: int = 0) -> bool:
        if self.op == "OR":
            if self.left.is_met(cycle=cycle, tokens_spent=tokens_spent, attempts=attempts):
                self._reason = self.left.reason
                return True
            if self.right.is_met(cycle=cycle, tokens_spent=tokens_spent, attempts=attempts):
                self._reason = self.right.reason
                return True
            self._reason = self.right.reason or self.left.reason
            return False
        elif self.op == "AND":
            if not self.left.is_met(cycle=cycle, tokens_spent=tokens_spent, attempts=attempts):
                self._reason = self.left.reason
                return False
            if not self.right.is_met(cycle=cycle, tokens_spent=tokens_spent, attempts=attempts):
                self._reason = self.right.reason
                return False
            self._reason = f"{self.left.reason} and {self.right.reason}"
            return True
        raise ValueError(f"Unsupported composition operation: {self.op}")

    def __or__(self, other: BaseTermination) -> _Composed:
        return _Composed(self, other, op="OR")

    def __and__(self, other: BaseTermination) -> _Composed:
        return _Composed(self, other, op="AND")


class BudgetExhausted:
    """Circuit breaker termination condition wrapping TokenBudgetManager."""

    def __init__(
        self,
        budget_manager: TokenBudgetManager,
        *,
        budget: PipelineBudget | None = None,
        estimated_repair_tokens: int = 400,
        used_total_tokens: int = 0,
    ) -> None:
        self.budget_manager = budget_manager
        self.budget = budget
        self.estimated_repair_tokens = estimated_repair_tokens
        self.used_total_tokens = used_total_tokens
        self._reason: str = ""
        self.last_decision: Any | None = None

    @property
    def reason(self) -> str:
        return self._reason

    def is_met(self, cycle: int = 0, tokens_spent: int = 0, attempts: int = 0) -> bool:
        if self.budget is None:
            return False
        decision = self.budget_manager.evaluate_repair_cycle(
            budget=self.budget,
            estimated_repair_tokens=self.estimated_repair_tokens,
            critique_repair_tokens_spent=tokens_spent,
            used_total_tokens=self.used_total_tokens + tokens_spent,
        )
        self.last_decision = decision
        self._reason = decision.reason
        return not decision.allowed

    def __or__(self, other: BaseTermination) -> _Composed:
        return _Composed(self, other, op="OR")

    def __and__(self, other: BaseTermination) -> _Composed:
        return _Composed(self, other, op="AND")


class MaxRepairsReached:
    """Termination condition triggered when maximum repair cycles/attempts are reached."""

    def __init__(self, max_repairs: int) -> None:
        self.max_repairs = max_repairs
        self._reason = f"maximum repair cycles ({max_repairs}) reached"

    @property
    def reason(self) -> str:
        return self._reason

    def is_met(self, cycle: int = 0, tokens_spent: int = 0, attempts: Any = 0) -> bool:
        num_attempts = len(attempts) if isinstance(attempts, (list, tuple, set)) else int(attempts)
        if cycle > self.max_repairs or num_attempts >= self.max_repairs:
            return True
        return False

    def __or__(self, other: BaseTermination) -> _Composed:
        return _Composed(self, other, op="OR")

    def __and__(self, other: BaseTermination) -> _Composed:
        return _Composed(self, other, op="AND")
