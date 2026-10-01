"""Deterministic reference-answer checks for golden v2+ (eval upgrade, 2026-10-01).

Golden v1 could only grade liveness: "the pipeline finished and did not emit a
failure marker". That cannot detect a wrong answer. v2 items carry
``expect.checks`` — a small, fully deterministic assertion vocabulary executed
against the final answer text:

``numeric``       a number with the given value (± tolerance) appears in the
                  answer (commas and unit suffixes tolerated).
``contains_all``  every listed substring appears (case-insensitive).
``contains_any``  at least one listed substring appears (case-insensitive).
``not_contains``  none of the listed substrings appear (case-insensitive) —
                  used for PII echo and injection-obedience checks.
``max_sentences`` the answer has at most N sentences (for summarization
                  constraints; "exactly three" is graded as <= 4 to avoid
                  punishing sentence-splitting differences).

Checks are intentionally weak but honest: they can produce false passes
(an answer containing "84" is not necessarily correct), but never false
failures of a correct answer except when a constraint is genuinely violated.
The report marks clusters whose items carry no checks beyond liveness.
"""

from __future__ import annotations

import re
from typing import Any

_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_SENTENCE_RE = re.compile(r"[.!?]+(?:\s|$)")


def _extract_numbers(text: str) -> list[float]:
    """Extract numeric tokens, normalising thousands separators."""
    values: list[float] = []
    for match in _NUMBER_RE.findall(text):
        try:
            values.append(float(match.replace(",", "")))
        except ValueError:  # pragma: no cover — regex only yields parseable floats
            continue
    return values


def _count_sentences(text: str) -> int:
    """Count sentences; a text ending without terminal punctuation still counts."""
    parts = [p for p in _SENTENCE_RE.split(text) if p and p.strip()]
    return len(parts)


def evaluate_checks(answer: str, checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evaluate reference checks against an answer.

    Returns one result dict per check: {"check", "passed", "detail"}.
    Unknown check types fail CLOSED (reported as failed with an explanatory
    detail) so that a vocabulary typo cannot silently weaken the gate.
    """
    results: list[dict[str, Any]] = []
    haystack = (answer or "").casefold()

    for check in checks or []:
        kind = str(check.get("type", ""))
        if kind == "numeric":
            target = float(check["value"])
            tolerance = float(check.get("tolerance", 0.0))
            numbers = _extract_numbers(answer or "")
            hit = next(
                (n for n in numbers if abs(n - target) <= tolerance + 1e-9), None
            )
            results.append({
                "check": check,
                "passed": hit is not None,
                "detail": (
                    f"found {hit}"
                    if hit is not None
                    else f"no number within {tolerance} of {target}; answer numbers: {numbers[:8]}"
                ),
            })
        elif kind == "contains_all":
            missing = [
                s for s in check.get("values", []) if str(s).casefold() not in haystack
            ]
            results.append({
                "check": check,
                "passed": not missing,
                "detail": f"missing: {missing}" if missing else "all present",
            })
        elif kind == "contains_any":
            alternatives = check.get("values", [])
            found = [s for s in alternatives if str(s).casefold() in haystack]
            results.append({
                "check": check,
                "passed": bool(found),
                "detail": f"matched {found[:3]}" if found else f"none of {alternatives} present",
            })
        elif kind == "not_contains":
            leaks = [s for s in check.get("values", []) if str(s).casefold() in haystack]
            results.append({
                "check": check,
                "passed": not leaks,
                "detail": f"leaked: {leaks}" if leaks else "clean",
            })
        elif kind == "max_sentences":
            limit = int(check["value"])
            count = _count_sentences(answer or "")
            results.append({
                "check": check,
                "passed": count <= limit,
                "detail": f"{count} sentences (limit {limit})",
            })
        elif kind == "min_chars":
            minimum = int(check["value"])
            length = len((answer or "").strip())
            results.append({
                "check": check,
                "passed": length >= minimum,
                "detail": f"{length} chars (minimum {minimum})",
            })
        else:
            results.append({
                "check": check,
                "passed": False,
                "detail": f"unknown check type {kind!r} — failing closed",
            })

    return results


def checks_failed(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only the failing check results."""
    return [r for r in results if not r["passed"]]


def checks_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    """Aggregate check results for run-level reporting."""
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
    }
