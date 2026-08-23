"""Reflection / repair loop (RFC-003 §9).

Flow: Generate → Judge/Critique → Reflect → Repair → Rejudge → Done.
Gate: CALIENNE_ENABLE_REPAIR.

The Token Budget Manager is the circuit breaker: if a repair cycle would
exceed the critique/repair budget, bypass repair and synthesize from the
best-available verified state with caveats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.schemas import PipelineBudget
from orchestrator.budget import RepairBudgetDecision, TokenBudgetManager

# ponytail: actionable defect types from RFC-003 §3.5 / §9.
ACTIONABLE_DEFECTS: frozenset[str] = frozenset({
    "contradiction",
    "unsupported_claim",
    "failed_code_check",
    "math_error",
    "missing_requirement",
    "validation_error",
})


@dataclass(frozen=True)
class Defect:
    """A single actionable defect found by a judge/critique pass."""

    kind: str  # one of ACTIONABLE_DEFECTS
    description: str = ""
    location: str | None = None  # node or field reference


@dataclass(frozen=True)
class RepairAttempt:
    """Record of one repair cycle."""

    cycle: int
    defects_addressed: list[Defect]
    repaired_output: Any = None
    rejudge_passed: bool = False
    budget_decision: RepairBudgetDecision | None = None


@dataclass
class RepairResult:
    """Final result of the repair loop."""

    output: Any
    repaired: bool = False
    bypassed: bool = False
    bypass_reason: str | None = None
    caveats: list[str] = field(default_factory=list)
    attempts: list[RepairAttempt] = field(default_factory=list)
    total_repair_tokens_spent: int = 0

    @property
    def repair_count(self) -> int:
        return len(self.attempts)


# ponytail: max_repairs=2 per RFC-003 §9, configurable for testing only.
DEFAULT_MAX_REPAIRS = 2

# ponytail: rough per-cycle token estimate for budget checks; real
# counting comes from the actual LLM calls once wired. Upgrade path:
# use prediction layer's expected_repair_count * per-node token estimate.
_ESTIMATED_TOKENS_PER_REPAIR = 500


def _filter_actionable(defects: list[Defect]) -> list[Defect]:
    """Keep only defects the repair loop can act on."""
    return [d for d in defects if d.kind in ACTIONABLE_DEFECTS]


def run_repair_loop(
    *,
    generated_output: Any,
    judge_defects: list[Defect],
    budget_manager: TokenBudgetManager,
    budget: PipelineBudget,
    critique_repair_tokens_spent: int = 0,
    used_total_tokens: int = 0,
    max_repairs: int = DEFAULT_MAX_REPAIRS,
    repair_fn: Any | None = None,
    rejudge_fn: Any | None = None,
) -> RepairResult:
    """Synchronous repair loop — runs up to *max_repairs* cycles.

    *repair_fn(output, defects) -> repaired_output* produces a repaired
    version.  *rejudge_fn(output) -> list[Defect]* re-evaluates.  Both
    default to identity/empty when ``None`` (useful for budget-only tests).

    The budget manager is consulted before every cycle.  If the budget
    says no, the loop synthesizes from the best available state with
    caveats attached.
    """
    actionable = _filter_actionable(judge_defects)
    if not actionable:
        return RepairResult(output=generated_output, repaired=False)

    best_output = generated_output
    attempts: list[RepairAttempt] = []
    tokens_spent = critique_repair_tokens_spent

    for cycle in range(1, max_repairs + 1):
        decision = budget_manager.evaluate_repair_cycle(
            budget=budget,
            estimated_repair_tokens=_ESTIMATED_TOKENS_PER_REPAIR,
            critique_repair_tokens_spent=tokens_spent,
            used_total_tokens=used_total_tokens + tokens_spent,
        )
        if not decision.allowed:
            # Circuit breaker: synthesize with caveats.
            caveats = [
                f"Repair cycle {cycle} skipped: {decision.reason}",
                *(f"Unresolved {d.kind}: {d.description}" for d in actionable),
            ]
            return RepairResult(
                output=best_output,
                repaired=bool(attempts),
                bypassed=True,
                bypass_reason=decision.reason,
                caveats=caveats,
                attempts=attempts,
                total_repair_tokens_spent=tokens_spent,
            )

        # Repair step.
        if repair_fn is not None:
            repaired = repair_fn(best_output, actionable)
        else:
            repaired = best_output  # identity stub

        tokens_spent += _ESTIMATED_TOKENS_PER_REPAIR

        # Rejudge step.
        if rejudge_fn is not None:
            new_defects = rejudge_fn(repaired)
        else:
            new_defects = []

        passed = len(_filter_actionable(new_defects)) == 0
        attempt = RepairAttempt(
            cycle=cycle,
            defects_addressed=list(actionable),
            repaired_output=repaired,
            rejudge_passed=passed,
            budget_decision=decision,
        )
        attempts.append(attempt)
        best_output = repaired

        if passed:
            return RepairResult(
                output=best_output,
                repaired=True,
                attempts=attempts,
                total_repair_tokens_spent=tokens_spent,
            )

        # Carry forward only the new actionable defects for next cycle.
        actionable = _filter_actionable(new_defects)

    # Exhausted max_repairs without passing rejudge.
    caveats = [
        f"Reached max_repairs={max_repairs} without passing rejudge",
        *(f"Remaining {d.kind}: {d.description}" for d in actionable),
    ]
    return RepairResult(
        output=best_output,
        repaired=True,
        bypassed=True,
        bypass_reason=f"max_repairs={max_repairs} exhausted",
        caveats=caveats,
        attempts=attempts,
        total_repair_tokens_spent=tokens_spent,
    )
