"""Gate G6 math — exact McNemar on discordant pairs.

Every asserted p-value matches the verified reference table in
.research_tmp/retry_eval_ci.md (computed independently there with math.comb).
"""

from __future__ import annotations

import pytest

from evals.mcnemar import ALPHA, GateResult, compare_runs, exact_mcnemar_two_sided


class TestExactPValues:
    @pytest.mark.parametrize(
        ("b", "c", "expected"),
        [
            (5, 0, 0.0625),
            (6, 0, 0.03125),
            (6, 1, 0.125),
            (8, 1, 0.0390625),
            (10, 2, 0.03857421875),
            (12, 3, 0.03515625),
        ],
    )
    def test_matches_reference_table(self, b: int, c: int, expected: float) -> None:
        assert exact_mcnemar_two_sided(b, c) == pytest.approx(expected, abs=1e-12)

    def test_symmetric_in_b_and_c(self) -> None:
        assert exact_mcnemar_two_sided(7, 3) == exact_mcnemar_two_sided(3, 7)

    def test_no_discordant_pairs_is_vacuous(self) -> None:
        assert exact_mcnemar_two_sided(0, 0) == 1.0

    def test_perfectly_balanced_never_significant(self) -> None:
        assert exact_mcnemar_two_sided(25, 25) == 1.0

    def test_p_is_capped_at_one(self) -> None:
        assert exact_mcnemar_two_sided(1, 1) == 1.0

    def test_negative_counts_rejected(self) -> None:
        with pytest.raises(ValueError):
            exact_mcnemar_two_sided(-1, 0)

    @pytest.mark.parametrize("n", [1023, 1024, 2000])
    def test_no_float_overflow_at_large_discordant_counts(self, n: int) -> None:
        """2.0**n overflowed (OverflowError) from n=1024 before the int-shift fix.

        Unreachable at golden n=50, but the function is a public API: a
        large-candidate run must get a p-value, not a crash. For n=2000 the
        true p (2/2**n ~ 1e-602) underflows to 0.0 — smaller than any float
        can express, which is an acceptable lower bound.
        """
        p = exact_mcnemar_two_sided(n, 0)
        assert 0.0 <= p <= ALPHA  # overwhelmingly significant, no crash


class TestRegressionThresholds:
    """Minimum b for p <= 0.05: c=0 -> 6, c=1 -> 8, c=2 -> 10, c=3 -> 12."""

    @pytest.mark.parametrize(("c", "min_b"), [(0, 6), (1, 8), (2, 10), (3, 12), (4, 13), (5, 15)])
    def test_threshold_boundary(self, c: int, min_b: int) -> None:
        assert exact_mcnemar_two_sided(min_b, c) <= ALPHA
        assert exact_mcnemar_two_sided(min_b - 1, c) > ALPHA


class TestCompareRuns:
    def test_regression_is_red_and_names_items(self) -> None:
        baseline = {f"g{i:03d}": True for i in range(20)}
        candidate = dict(baseline)
        for i in (2, 5, 7, 9, 11, 13):  # six regressions, zero improvements
            candidate[f"g{i:03d}"] = False
        result = compare_runs(baseline, candidate)
        assert result.b == 6 and result.c == 0
        assert result.p_value <= ALPHA
        assert result.is_regression
        assert result.verdict == "REGRESSION"
        assert result.regressed_ids == ["g002", "g005", "g007", "g009", "g011", "g013"]

    def test_significant_improvement_is_not_red(self) -> None:
        baseline = {f"g{i:03d}": False for i in range(20)}
        candidate = dict(baseline)
        for i in range(6):
            candidate[f"g{i:03d}"] = True
        result = compare_runs(baseline, candidate)
        assert result.p_value <= ALPHA
        assert not result.is_regression
        assert result.verdict == "IMPROVEMENT"

    def test_balanced_flips_are_not_significant(self) -> None:
        baseline = {f"g{i:03d}": i % 2 == 0 for i in range(20)}
        candidate = {f"g{i:03d}": i % 2 == 1 for i in range(20)}
        result = compare_runs(baseline, candidate)
        assert result.b == 10 and result.c == 10
        assert result.p_value == 1.0
        assert result.verdict == "NO_SIGNIFICANT_CHANGE"

    def test_identical_runs_have_no_discordant_pairs(self) -> None:
        outcomes = {f"g{i:03d}": i % 3 == 0 for i in range(50)}
        result = compare_runs(outcomes, dict(outcomes))
        assert result.verdict == "NO_DISCORDANT_PAIRS"

    def test_mismatched_item_sets_rejected(self) -> None:
        with pytest.raises(ValueError, match="identical item set"):
            compare_runs({"a": True}, {"a": True, "b": False})

    def test_gate_result_summary_names_both_directions(self) -> None:
        result = GateResult(b=1, c=2, p_value=1.0, regressed_ids=["x"], improved_ids=["y", "z"], alpha=ALPHA)
        summary = result.summary()
        assert "x" in summary and "y" in summary and "z" in summary
