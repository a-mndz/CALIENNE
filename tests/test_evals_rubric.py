"""Tests for Calibrated LLM-as-a-Judge Rubric & Semantic Evaluation (P2-03)."""

from __future__ import annotations

from evals.rubric import SemanticJudge


def test_semantic_judge_passing_response() -> None:
    judge = SemanticJudge()
    query = "Explain why memoization speeds up recursive Fibonacci."
    response = (
        "Memoization speeds up the calculation because it stores the results of subproblems. "
        "Therefore, instead of recalculating duplicate Fibonacci branches "
        "with exponential time complexity O(2^n), "
        "each subproblem is resolved once in O(1) table lookup, yielding overall linear time complexity O(n)."
    )
    result = judge.evaluate(
        query=query,
        response=response,
        reference_answer="stores subproblems in table reducing time from exponential to linear O(n)",
        assertions=["O(n)", "memoization"],
    )
    assert result.passed is True
    assert result.overall_score >= 3.5
    assert len(result.failed_assertions) == 0
    assert result.verdict == "PASS"


def test_semantic_judge_failing_assertion() -> None:
    judge = SemanticJudge()
    query = "What is the time complexity of bubble sort in worst case?"
    response = "Bubble sort is very simple and takes O(n) time."
    result = judge.evaluate(
        query=query,
        response=response,
        assertions=["O(n^2)", "quadratic"],
    )
    assert result.passed is False
    assert "O(n^2)" in result.failed_assertions
    assert result.verdict == "FAIL_CRITERIA"


def test_semantic_judge_empty_response() -> None:
    judge = SemanticJudge()
    result = judge.evaluate(query="Any query", response="")
    assert result.passed is False
    assert result.overall_score == 0.0
    assert result.verdict == "REJECTED_EMPTY"
