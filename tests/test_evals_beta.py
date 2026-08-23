"""β co-failure measurement + capture grader tests."""

from __future__ import annotations

import pytest

from evals.beta import _wilson_interval, beta_with_interval, measure_beta
from evals.capture import grade_item, noise_floor


def _rows(pairs: list[tuple[bool, bool]], cluster: str = "c") -> list[dict]:
    return [
        {"id": f"i{i}", "cluster_id": cluster, "logician_pass": lg, "creative_pass": cr}
        for i, (lg, cr) in enumerate(pairs)
    ]


class TestBeta:
    def test_counts_and_ratios(self) -> None:
        report = measure_beta(_rows([
            (True, True),     # both succeed
            (True, False),    # one succeeds
            (False, True),    # one succeeds
            (False, False),   # both fail
        ]))
        assert report.n == 4
        assert report.both_succeed == 1
        assert report.one_succeeds == 2
        assert report.both_fail == 1
        assert report.beta == 0.25
        assert report.benefit_ceiling == 0.5

    def test_empty_rows(self) -> None:
        report = measure_beta([])
        assert report.beta == 0.0 and report.benefit_ceiling == 0.0

    def test_per_cluster_breakdown(self) -> None:
        rows = _rows([(False, False)], cluster="hard") + _rows([(True, True)], cluster="easy")
        report = measure_beta(rows)
        assert report.clusters["hard"]["beta"] == 1.0
        assert report.clusters["easy"]["beta"] == 0.0
        assert report.clusters["hard"]["n"] == 1.0

    def test_unclustered_rows_bucketed(self) -> None:
        report = measure_beta([{"id": "x", "logician_pass": True, "creative_pass": False}])
        assert "_unclustered" in report.clusters


class TestWilsonInterval:
    def test_bounds_inside_unit_interval(self) -> None:
        lo, hi = _wilson_interval(0, 10)
        assert 0.0 <= lo <= hi <= 1.0

    def test_zero_successes_lower_bound_is_zero(self) -> None:
        lo, _ = _wilson_interval(0, 50)
        assert lo == 0.0

    def test_all_successes_upper_bound_is_one(self) -> None:
        _, hi = _wilson_interval(50, 50)
        assert hi == 1.0

    def test_wilson_narrower_than_naive_at_small_n(self) -> None:
        # Naive p̂ ± z√(p̂(1-p̂)/n) at p̂=0.5, n=10 is ±0.3099; Wilson must be
        # narrower than that at the same z.
        lo, hi = _wilson_interval(5, 10)
        assert (hi - lo) / 2 < 0.3099

    def test_report_with_interval(self) -> None:
        report, (lo, hi) = beta_with_interval(_rows([(False, False)] * 4 + [(True, True)] * 16))
        assert report.beta == 0.2
        assert lo <= 0.2 <= hi


class TestGraderRubricV1:
    def test_complete_result_passes(self) -> None:
        graded = grade_item({
            "status": "completed",
            "answer": "The average speed is 84 km/h.",
            "agent_outputs": {
                "logician": {"answer": "Reasoned: 84 km/h."},
                "creative": {"answer": "Alternatively, 84 km/h."},
            },
        })
        assert graded["pass"] and graded["logician_pass"] and graded["creative_pass"]

    def test_parse_failure_marker_fails(self) -> None:
        graded = grade_item({
            "status": "completed",
            "answer": "PARSE FAILURE for judge agent.",
            "agent_outputs": {"logician": {"answer": "ok"}, "creative": {"answer": "ok"}},
        })
        assert not graded["pass"]

    def test_empty_answer_fails(self) -> None:
        graded = grade_item({"status": "completed", "answer": "   "})
        assert not graded["pass"] and not graded["logician_pass"]

    def test_failed_status_fails(self) -> None:
        graded = grade_item({"status": "failed", "answer": "something"})
        assert not graded["pass"]

    def test_missing_agent_output_fails_that_agent(self) -> None:
        graded = grade_item({
            "status": "completed",
            "answer": "fine",
            "agent_outputs": {"logician": {"answer": "fine"}, "creative": None},
        })
        assert graded["logician_pass"] and not graded["creative_pass"]


class TestNoiseFloor:
    def test_stable_verdicts_zero_floor(self) -> None:
        rows = [
            {"id": "a", "pass": True}, {"id": "a", "pass": True},
            {"id": "b", "pass": False}, {"id": "b", "pass": False},
        ]
        assert noise_floor(rows) == 0.0

    def test_flipping_verdict_measured(self) -> None:
        rows = [
            {"id": "a", "pass": True}, {"id": "a", "pass": True},
            {"id": "b", "pass": True}, {"id": "b", "pass": False},
        ]
        assert noise_floor(rows) == pytest.approx(0.5)

    def test_empty(self) -> None:
        assert noise_floor([]) == 0.0
