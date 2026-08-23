"""Exact McNemar test on discordant pairs — gate G6 (non-blocking).

Two-sided exact p-value for the binomial sign test on discordant pairs:
``b`` items regressed (arm A passed, arm B failed), ``c`` improved. Under the
null both directions are equally likely, so with n = b + c discordant items:

    p = 2 * sum_{k=0}^{min(b,c)} C(n, k) * 0.5**n      (capped at 1.0)

Concordant items contribute nothing — that is the entire point: the test
conditions away both the variance and the inter-arm correlation that make
aggregate-score gates unusable at n=50.

Reference table (verified 2026-08-21, .research_tmp/retry_eval_ci.md):
minimum ``b`` for p <= 0.05 two-sided: c=0 -> 6, c=1 -> 8, c=2 -> 10,
c=3 -> 12, c=4 -> 13, c=5 -> 15.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

ALPHA = 0.05


def exact_mcnemar_two_sided(b: int, c: int) -> float:
    """Two-sided exact p-value for b regressed / c improved discordant pairs.

    b, c >= 0. With no discordant pairs the test is vacuous: p = 1.0.
    """
    if b < 0 or c < 0:
        raise ValueError(f"b and c must be non-negative, got b={b}, c={c}")
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    # Integer division by 2**n via a shift: 2.0**n overflows the float range
    # (OverflowError) once n reaches 1024, and int/int true division is
    # correctly rounded at any magnitude.
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (1 << n)
    return min(1.0, 2.0 * tail)


@dataclass(frozen=True)
class GateResult:
    b: int
    c: int
    p_value: float
    regressed_ids: list[str]
    improved_ids: list[str]
    alpha: float

    @property
    def is_regression(self) -> bool:
        """Red only when significant AND imbalanced toward regression.

        A significant result in the improvement direction is a pass (noted,
        not gated): the gate protects quality, it does not enforce symmetry.
        """
        return self.p_value <= self.alpha and self.b > self.c

    @property
    def verdict(self) -> str:
        if self.b + self.c == 0:
            return "NO_DISCORDANT_PAIRS"
        if self.p_value <= self.alpha:
            return "REGRESSION" if self.b > self.c else "IMPROVEMENT"
        return "NO_SIGNIFICANT_CHANGE"

    def summary(self) -> str:
        lines = [
            f"b (regressed) = {self.b}, c (improved) = {self.c}, "
            f"two-sided exact p = {self.p_value:.6f}, alpha = {self.alpha}",
            f"verdict: {self.verdict}",
        ]
        if self.regressed_ids:
            lines.append("regressed item ids: " + ", ".join(self.regressed_ids))
        if self.improved_ids:
            lines.append("improved item ids: " + ", ".join(self.improved_ids))
        return "\n".join(lines)


def _load_outcomes(path: str | Path) -> dict[str, bool]:
    """Load a run file: one JSONL row per item, {"id": ..., "pass": bool}."""
    outcomes: dict[str, bool] = {}
    with open(path, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "id" not in row or "pass" not in row:
                raise ValueError(f"{path}:{line_no}: row needs 'id' and 'pass'")
            item_id = str(row["id"])
            if item_id in outcomes:
                raise ValueError(f"{path}:{line_no}: duplicate id {item_id!r}")
            outcomes[item_id] = bool(row["pass"])
    if not outcomes:
        raise ValueError(f"{path}: no outcome rows found")
    return outcomes


def compare_runs(
    baseline: dict[str, bool], candidate: dict[str, bool], alpha: float = ALPHA
) -> GateResult:
    """Paired comparison of per-item outcomes across the SAME item set."""
    if set(baseline) != set(candidate):
        missing = set(baseline) - set(candidate)
        extra = set(candidate) - set(baseline)
        raise ValueError(
            "run files must cover the identical item set "
            f"(missing from candidate: {sorted(missing)[:5]}, "
            f"extra in candidate: {sorted(extra)[:5]})"
        )
    regressed = sorted(i for i in baseline if baseline[i] and not candidate[i])
    improved = sorted(i for i in baseline if not baseline[i] and candidate[i])
    b, c = len(regressed), len(improved)
    return GateResult(
        b=b,
        c=c,
        p_value=exact_mcnemar_two_sided(b, c),
        regressed_ids=regressed,
        improved_ids=improved,
        alpha=alpha,
    )


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 2:
        print("usage: python -m evals.mcnemar <baseline_run.jsonl> <candidate_run.jsonl>")
        return 2
    result = compare_runs(_load_outcomes(argv[0]), _load_outcomes(argv[1]))
    print(result.summary())
    return 1 if result.is_regression else 0


if __name__ == "__main__":
    raise SystemExit(main())
