"""Run report — markdown summary of one or more capture runs.

Usage:
  python -m evals.report <run.jsonl> [more_runs.jsonl ...]

For each run: pass rate (overall + per cluster), check-level stats, judge
validation_score distribution with the SUSPECT invariant, β co-failure when
triad agent fields are present, and the noise floor when reps > 1.

SUSPECT invariant: on a live (non-simulated) run, if every validation_score
is missing, zero, or identical across all rows, the judge metric is inert —
the run's quality numbers are void until the judge path is fixed. This is the
invariant the 2026-08-22 baseline silently violated (score 0/null in 100% of
rows) and nobody noticed.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def _load(path: Path) -> list[dict]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _fmt_pct(n: int, d: int) -> str:
    return f"{(n / d * 100):.1f}%" if d else "n/a"


def _validate_path(raw: str) -> Path:
    path = Path(raw).resolve()
    if not path.is_file() or path.suffix != ".jsonl":
        print(f"error: {raw!r} is not an existing .jsonl file", file=sys.stderr)
        raise SystemExit(2)
    return path


def _score_verdict(scores: list[float | None], simulated: bool, arm: str = "triad") -> str:
    live = not simulated
    if not scores or all(s is None for s in scores):
        if arm == "single":
            return "absent by design (no judge in the single arm)"
        return "SUSPECT: missing in 100% of rows" if live else "missing in all rows (sim)"
    clean = [s for s in scores if s is not None]
    if all(s == 0 for s in clean):
        return "SUSPECT: all zeros" if live else "all zeros (sim)"
    if len(set(clean)) == 1:
        return f"SUSPECT: constant value {clean[0]}" if live else f"constant value {clean[0]} (sim)"
    lo, hi = min(clean), max(clean)
    avg = sum(clean) / len(clean)
    return f"min {lo:.2f} / mean {avg:.2f} / max {hi:.2f}"


def render(path: Path, rows: list[dict]) -> str:
    n = len(rows)
    passed = sum(1 for r in rows if r.get("pass"))
    aborted = sum(1 for r in rows if r.get("aborted"))
    checks_total = sum(r.get("checks_total", 0) or 0 for r in rows)
    checks_passed = sum(r.get("checks_passed", 0) or 0 for r in rows)
    simulated = bool(rows and rows[0].get("simulated"))
    arm = rows[0].get("arm", "?") if rows else "?"
    scores = [r.get("validation_score") for r in rows]

    lines = [
        f"## {path.name}",
        "",
        f"- arm: `{arm}` | golden: `{rows[0].get('golden', '?')}` | "
        f"commit: `{rows[0].get('git_commit', '?')}` | simulated: {simulated} | rows: {n}",
        f"- **pass: {passed}/{n} ({_fmt_pct(passed, n)})** | aborted: {aborted} | "
        f"liveness-only passes (checks failed): "
        f"{sum(1 for r in rows if r.get('pass') and (r.get('checks_total', 0) or 0) > 0 and not r.get('aborted') and r.get('checks_passed', 0) == r.get('checks_total', 0))}",  # noqa: E501
        f"- reference checks: {checks_passed}/{checks_total} passed"
        if checks_total
        else "- reference checks: none in this run (v1 set — liveness grading only)",
        f"- validation_score: {_score_verdict(scores, simulated, arm)}",
    ]

    per_cluster: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        per_cluster[r.get("cluster_id") or "?"][bool(r.get("pass"))] += 1
    if per_cluster:
        lines.append("")
        lines.append("| cluster | pass | total | rate |")
        lines.append("|---|---|---|---|")
        for cluster in sorted(per_cluster):
            counts = per_cluster[cluster]
            total = counts[True] + counts[False]
            lines.append(f"| {cluster} | {counts[True]} | {total} | {_fmt_pct(counts[True], total)} |")

    # β co-failure (triad rows only)
    beta_rows = [
        r for r in rows if "logician_pass" in r and "creative_pass" in r and not r.get("aborted")
    ]
    if beta_rows:
        both_fail = sum(
            1 for r in beta_rows if not r["logician_pass"] and not r["creative_pass"]
        )
        lines.append(
            f"- agent liveness co-failure β̂: {both_fail}/{len(beta_rows)} = "
            f"{(both_fail / len(beta_rows)) if beta_rows else 0:.3f}"
            " (uses agent liveness, not correctness — see evals/README)"
        )

    # Noise floor
    reps = {r.get("rep", 0) for r in rows}
    if len(reps) > 1:
        by_item: dict[str, set[bool]] = defaultdict(set)
        for r in rows:
            by_item[r["id"]].add(bool(r.get("pass")))
        unstable = sum(1 for v in by_item.values() if len(v) > 1)
        lines.append(
            f"- G7 noise floor (verdict flip rate across {len(reps)} reps): "
            f"{unstable}/{len(by_item)} = {(unstable / len(by_item)) if by_item else 0:.4f}"
        )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    paths = [_validate_path(a) for a in (argv or sys.argv[1:])]
    if not paths:
        print("usage: python -m evals.report <run.jsonl> [more...]")
        return 2
    print("# Eval run report\n")
    for path in paths:
        rows = _load(path)
        print(render(path, rows))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
