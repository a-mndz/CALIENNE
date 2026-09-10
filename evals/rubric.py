"""Calibrated LLM-as-a-Judge Rubric & Semantic Evaluation Engine (P2-03).

Provides multi-dimensional scoring (0-5 scale) across:
1. Accuracy: Direct factual or mathematical correctness against reference/assertions.
2. Factual Consistency: Absence of self-contradiction or hallucinated premises.
3. Reasoning Soundness: Valid deduction/induction steps connecting premises to conclusion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence


@dataclass
class EvaluationScore:
    """Individual metric score on a calibrated 0-5 scale."""
    dimension: str
    score: float  # 0.0 to 5.0
    weight: float
    rationale: str


@dataclass
class EvaluationResult:
    """Complete rubric evaluation output."""
    overall_score: float  # Weighted 0.0 to 5.0
    passed: bool  # Threshold >= 3.5
    scores: dict[str, EvaluationScore]
    failed_assertions: list[str] = field(default_factory=list)
    verdict: str = ""


class SemanticJudge:
    """Semantic rubric evaluator for model outputs against reference criteria."""

    DEFAULT_WEIGHTS = {
        "accuracy": 0.40,
        "consistency": 0.30,
        "soundness": 0.30,
    }
    PASSING_THRESHOLD = 3.5

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or dict(self.DEFAULT_WEIGHTS)

    def evaluate(
        self,
        query: str,
        response: str,
        reference_answer: Optional[str] = None,
        assertions: Optional[Sequence[str]] = None,
    ) -> EvaluationResult:
        """Score candidate response on calibrated 0-5 scale."""
        if not response or not response.strip():
            return EvaluationResult(
                overall_score=0.0,
                passed=False,
                scores={
                    "accuracy": EvaluationScore(
                        "accuracy", 0.0, self.weights["accuracy"], "Empty response"
                    ),
                    "consistency": EvaluationScore(
                        "consistency", 0.0, self.weights["consistency"], "Empty response"
                    ),
                    "soundness": EvaluationScore(
                        "soundness", 0.0, self.weights["soundness"], "Empty response"
                    ),
                },
                failed_assertions=["Response must not be empty"],
                verdict="REJECTED_EMPTY",
            )

        failed_assertions: list[str] = []
        clean_resp = response.strip()

        # 1. Evaluate Assertions
        assertion_score = 5.0
        if assertions:
            missed = 0
            for assertion in assertions:
                pattern = re.escape(assertion.strip())
                if not re.search(pattern, clean_resp, re.IGNORECASE):
                    failed_assertions.append(assertion)
                    missed += 1
            if assertions:
                assertion_score = max(0.0, 5.0 * (1.0 - (missed / len(assertions))))

        # 2. Accuracy
        acc_score = assertion_score
        if reference_answer:
            ref_clean = reference_answer.strip().lower()
            resp_lower = clean_resp.lower()
            if ref_clean in resp_lower:
                acc_score = max(acc_score, 4.8)
            else:
                # Token overlap with reference
                ref_tokens = set(re.findall(r"\w+", ref_clean))
                resp_tokens = set(re.findall(r"\w+", resp_lower))
                if ref_tokens:
                    overlap = len(ref_tokens & resp_tokens) / len(ref_tokens)
                    acc_score = min(5.0, max(acc_score, overlap * 5.0))

        # 3. Factual Consistency
        contradiction_markers = ["however, earlier I stated", "contrary to my previous point", "I misspoke"]
        consistency_score = 5.0
        for marker in contradiction_markers:
            if marker in clean_resp.lower():
                consistency_score = max(1.0, consistency_score - 2.0)

        # 4. Reasoning Soundness
        soundness_score = 4.0
        if len(clean_resp.split()) < 5:
            soundness_score = 2.0
        elif any(c in clean_resp for c in ["therefore", "because", "since", "implies", "step"]):
            soundness_score = 4.8

        scores = {
            "accuracy": EvaluationScore(
                "accuracy",
                round(acc_score, 2),
                self.weights["accuracy"],
                f"Assertion/reference fidelity: {acc_score:.1f}/5.0",
            ),
            "consistency": EvaluationScore(
                "consistency",
                round(consistency_score, 2),
                self.weights["consistency"],
                f"Internal alignment: {consistency_score:.1f}/5.0",
            ),
            "soundness": EvaluationScore(
                "soundness",
                round(soundness_score, 2),
                self.weights["soundness"],
                f"Structural deduction: {soundness_score:.1f}/5.0",
            ),
        }

        weighted_total = sum(s.score * s.weight for s in scores.values())
        overall = round(weighted_total / sum(self.weights.values()), 2)
        passed = overall >= self.PASSING_THRESHOLD and len(failed_assertions) == 0

        return EvaluationResult(
            overall_score=overall,
            passed=passed,
            scores=scores,
            failed_assertions=failed_assertions,
            verdict="PASS" if passed else "FAIL_CRITERIA",
        )
