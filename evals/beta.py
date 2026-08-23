"""β (co-failure ceiling) measurement for the dual-agent topology.

The Logician+Creative pair only earns its latency/cost if arbitration has
something to arbitrate. The recoverable window is exactly the items where
ONE agent succeeds and the other fails — when both fail, no judge can pick a
winner; when both succeed, the second agent added nothing the first provided.

β = P(both agents fail) is therefore the co-failure ceiling: the fraction of
items where the multi-agent topology is structurally unable to help. Its
complement-in-relevance, P(exactly one succeeds), is the benefit ceiling —
the largest fraction of items arbitration could ever rescue.

Input: one JSONL row per item:
    {"id": "...", "cluster_id": "...", "logician_pass": bool, "creative_pass": bool}

Pass/fail itself comes from the deterministic grader in evals.capture — a
judgement call belongs to the rubric, not to this module.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BetaReport:
    n: int
    both_fail: int
    one_succeeds: int
    both_succeed: int
    clusters: dict[str, dict[str, float]]

    @property
    def beta(self) -> float:
        """P(both agents fail) — co-failure ceiling."""
        return self.both_fail / self.n if self.n else 0.0

    @property
    def benefit_ceiling(self) -> float:
        """P(exactly one agent succeeds) — max items arbitration can rescue."""
        return self.one_succeeds / self.n if self.n else 0.0

    def summary(self) -> str:
        both_succeed_frac = self.both_succeed / self.n if self.n else 0.0
        lines = [
            f"n = {self.n}",
            f"β (both fail)        = {self.beta:.4f}  ({self.both_fail} items)",
            f"benefit ceiling      = {self.benefit_ceiling:.4f}  ({self.one_succeeds} items)",
            f"both succeed         = {both_succeed_frac:.4f}  ({self.both_succeed} items)",
        ]
        if self.clusters:
            lines.append("per-cluster β:")
            for cluster in sorted(self.clusters):
                stats = self.clusters[cluster]
                lines.append(
                    f"  {cluster}: β={stats['beta']:.3f} "
                    f"ceiling={stats['ceiling']:.3f} (n={int(stats['n'])})"
                )
        return "\n".join(lines)


def _wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval — honest CI for small-n proportions.

    The naive p̂ ± z√(p̂(1-p̂)/n) is anti-conservative at the small n the
    golden set runs at; Wilson stays inside [0, 1] and behaves at p̂=0.
    """
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def measure_beta(rows: list[dict]) -> BetaReport:
    both_fail = one_succeeds = both_succeed = 0
    per_cluster: dict[str, list[int]] = {}
    for row in rows:
        logician = bool(row.get("logician_pass"))
        creative = bool(row.get("creative_pass"))
        if logician and creative:
            both_succeed += 1
        elif logician or creative:
            one_succeeds += 1
        else:
            both_fail += 1
        cluster = str(row.get("cluster_id") or "_unclustered")
        counts = per_cluster.setdefault(cluster, [0, 0, 0])  # both_fail, one, n
        counts[2] += 1
        if not logician and not creative:
            counts[0] += 1
        elif logician != creative:
            counts[1] += 1

    clusters = {
        cluster: {
            "beta": counts[0] / counts[2],
            "ceiling": counts[1] / counts[2],
            "n": float(counts[2]),
        }
        for cluster, counts in per_cluster.items()
    }
    return BetaReport(
        n=len(rows),
        both_fail=both_fail,
        one_succeeds=one_succeeds,
        both_succeed=both_succeed,
        clusters=clusters,
    )


def beta_with_interval(rows: list[dict]) -> tuple[BetaReport, tuple[float, float]]:
    report = measure_beta(rows)
    return report, _wilson_interval(report.both_fail, report.n)


def _load_rows(path: str | Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "logician_pass" not in row or "creative_pass" not in row:
                raise ValueError(f"{path}:{line_no}: row needs logician_pass/creative_pass")
            rows.append(row)
    if not rows:
        raise ValueError(f"{path}: no rows found")
    return rows


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print("usage: python -m evals.beta <agent_outcomes.jsonl>")
        return 2
    report, (lo, hi) = beta_with_interval(_load_rows(argv[0]))
    print(report.summary())
    print(f"β 95% Wilson CI     = [{lo:.4f}, {hi:.4f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
