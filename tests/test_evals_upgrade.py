"""Tests for the eval upgrade: reference checks, multi-arm capture grading,
multi-set manifest, mcnemar aggregation, and the report SUSPECT invariant."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.checks import evaluate_checks
from evals.capture import grade_item

pytestmark = pytest.mark.unit


# ── Reference checks ────────────────────────────────────────────────────


def test_numeric_check_matches_with_commas_and_units() -> None:
    checks = [{"type": "numeric", "value": 84, "tolerance": 0.0}]
    assert evaluate_checks("The average speed is 84 km/h.", checks)[0]["passed"]
    assert evaluate_checks("It is 1,280 meters; average 84.", checks)[0]["passed"]
    assert not evaluate_checks("About 85 km/h.", checks)[0]["passed"]


def test_numeric_check_tolerance() -> None:
    checks = [{"type": "numeric", "value": 19.02, "tolerance": 0.2}]
    assert evaluate_checks("About 19.0 years.", checks)[0]["passed"]
    assert not evaluate_checks("About 20 years.", checks)[0]["passed"]


def test_not_contains_detects_pii_echo() -> None:
    checks = [{"type": "not_contains", "values": ["jane.doe@example.com"]}]
    assert not evaluate_checks("Sure, jane.doe@example.com is safe.", checks)[0]["passed"]
    assert evaluate_checks("I will not store your contact details.", checks)[0]["passed"]


def test_max_sentences_counts_terminal_punctuation() -> None:
    checks = [{"type": "max_sentences", "value": 3}]
    assert evaluate_checks("One. Two. Three.", checks)[0]["passed"]
    assert not evaluate_checks("One. Two. Three. Four. Five.", checks)[0]["passed"]


def test_unknown_check_type_fails_closed() -> None:
    checks = [{"type": "telepathy", "values": ["yes"]}]
    assert not evaluate_checks("yes", checks)[0]["passed"]


def test_contains_all_and_any() -> None:
    assert evaluate_checks(
        "Legislative, executive and judicial branches.",
        [{"type": "contains_all", "values": ["legislative", "executive", "judicial"]}],
    )[0]["passed"]
    result = evaluate_checks(
        "Nothing relevant here.",
        [{"type": "contains_any", "values": ["veto", "impeach"]}],
    )[0]
    assert not result["passed"]
    assert "none of" in result["detail"]


# ── Grading with checks ─────────────────────────────────────────────────


def test_grade_item_liveness_only_without_expect() -> None:
    graded = grade_item({"status": "completed", "answer": "A fine answer."})
    assert graded["pass"] is True
    assert graded["checks_total"] == 0


def test_grade_item_fails_when_reference_check_fails() -> None:
    expect = {"checks": [{"type": "numeric", "value": 84, "tolerance": 0.0}]}
    graded = grade_item(
        {"status": "completed", "answer": "The speed is 85 km/h."}, expect=expect
    )
    assert graded["pass"] is False
    assert graded["liveness_pass"] is True
    assert graded["checks_passed"] == 0
    assert graded["checks_total"] == 1
    assert graded["failed_check_details"]


def test_grade_item_passes_when_all_checks_pass() -> None:
    expect = {"checks": [{"type": "numeric", "value": 84, "tolerance": 0.0}]}
    graded = grade_item({"status": "completed", "answer": "84 km/h"}, expect=expect)
    assert graded["pass"] is True


# ── Multi-set manifest ──────────────────────────────────────────────────


@pytest.mark.parametrize("version", ["v1", "v2", "gsm8k_v1"])
def test_all_golden_sets_validate(version: str) -> None:
    from evals.validate import load_golden

    items, meta = load_golden(version)
    assert meta["errors"] == []
    assert len(items) == 50


def test_v2_items_carry_checks_and_v1_fingerprints() -> None:
    from evals.validate import load_golden

    v1_items, _ = load_golden("v1")
    v2_items, _ = load_golden("v2")
    v1_by_id = {i["id"]: i for i in v1_items}
    for item in v2_items:
        assert item["expect"]["rubric"] == "v2"
        assert item["expect"]["checks"], f"{item['id']} has no checks"
        assert item["query"] == v1_by_id[item["id"]]["query"]
        assert item["prompt_fingerprint"] == v1_by_id[item["id"]]["prompt_fingerprint"]


# ── mcnemar aggregation ─────────────────────────────────────────────────


def test_mcnemar_aggregate_majority() -> None:
    from evals.mcnemar import _aggregate_outcomes

    rows = [
        {"id": "a", "pass": True}, {"id": "a", "pass": True},   # 2/2 -> pass
        {"id": "b", "pass": True}, {"id": "b", "pass": False},  # 1/2 -> fail (strict majority)
        {"id": "c", "pass": False}, {"id": "c", "pass": False}, # 0/2 -> fail
    ]
    outcomes = _aggregate_outcomes(rows)
    assert outcomes == {"a": True, "b": False, "c": False}


def test_mcnemar_cli_aggregate_flag(tmp_path: Path) -> None:
    from evals.mcnemar import main

    base = tmp_path / "base.jsonl"
    cand = tmp_path / "cand.jsonl"
    # duplicates without --aggregate would raise; with --aggregate it must work
    base.write_text(
        '{"id": "a", "pass": false}\n{"id": "a", "pass": false}\n'
        '{"id": "b", "pass": false}\n{"id": "b", "pass": false}\n',
        encoding="utf-8",
    )
    cand.write_text(
        '{"id": "a", "pass": true}\n{"id": "a", "pass": true}\n'
        '{"id": "b", "pass": false}\n{"id": "b", "pass": false}\n',
        encoding="utf-8",
    )
    # tmp_path is outside CWD containment? run files must be under CWD —
    # chroot the check by monkeypatching cwd via monkeypatch.chdir
    import os

    os.chdir(tmp_path)
    try:
        rc = main([str(base), str(cand), "--aggregate"])
    finally:
        os.chdir(Path(__file__).resolve().parents[1])
    assert rc == 0  # no regression: improvement only


# ── Report SUSPECT invariant ────────────────────────────────────────────


def _row(over: dict) -> dict:
    row = {"id": "x", "rep": 0, "cluster_id": "c", "pass": True, "arm": "triad",
           "golden": "v2", "git_commit": "abc", "simulated": False,
           "validation_score": 8.0}
    row.update(over)
    return row


def test_report_flags_all_zero_scores_as_suspect() -> None:
    from evals.report import _score_verdict

    verdict = _score_verdict([0.0, 0.0, 0.0], simulated=False)
    assert "SUSPECT" in verdict


def test_report_flags_constant_scores_as_suspect() -> None:
    from evals.report import _score_verdict

    verdict = _score_verdict([9.2, 9.2, 9.2], simulated=False)
    assert "SUSPECT" in verdict


def test_report_healthy_scores_pass() -> None:
    from evals.report import _score_verdict

    verdict = _score_verdict([7.0, 8.5, 9.0], simulated=False)
    assert "SUSPECT" not in verdict
    assert "min 7.00" in verdict


def test_report_missing_scores_flagged_on_live_run() -> None:
    from evals.report import _score_verdict

    assert "SUSPECT" in _score_verdict([None, None], simulated=False)


def test_report_renders_cluster_table(tmp_path: Path, monkeypatch) -> None:
    from evals.report import render

    rows = [
        _row({"id": f"i{i}", "cluster_id": c, "pass": True, "checks_passed": 2,
              "checks_total": 2, "logician_pass": True, "creative_pass": True})
        for i, c in enumerate(["math", "math", "coding"])
    ]
    out = render(tmp_path / "run.jsonl", rows)
    assert "pass: 3/3" in out
    assert "| math |" in out
    assert "| coding |" in out
