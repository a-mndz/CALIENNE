"""Gate G2 — consensus invariants (property-style, zero API calls).

Symmetry, reflexivity, range, ``contradiction_score == 1 - raw_agreement``,
and empty-input safety of ``compute_consensus``. The known Jaccard-paraphrase
limitation (exact-string claim matching cannot see paraphrases) is pinned to
its current value rather than papered over.
"""

from __future__ import annotations

import pytest

from orchestrator.consensus import JudgeOutput, _pairwise_agreement, compute_consensus


def _judge(model_id: str, claims: list[str], confidence: float = 0.8) -> JudgeOutput:
    return JudgeOutput(model_id=model_id, claims=claims, confidence=confidence)


class TestPairwiseAgreementInvariants:
    def test_reflexive(self) -> None:
        a = _judge("a", ["p", "q", "r"])
        assert _pairwise_agreement(a, a) == 1.0

    def test_symmetric(self) -> None:
        a = _judge("a", ["p", "q", "s"])
        b = _judge("b", ["q", "r"])
        assert _pairwise_agreement(a, b) == _pairwise_agreement(b, a)

    def test_range(self) -> None:
        a = _judge("a", ["p"])
        b = _judge("b", ["q"])
        assert _pairwise_agreement(a, b) == 0.0
        c = _judge("c", ["p"])
        assert _pairwise_agreement(a, c) == 1.0

    def test_both_empty_claims_is_full_agreement(self) -> None:
        assert _pairwise_agreement(_judge("a", []), _judge("b", [])) == 1.0

    def test_jaccard_value_pinned(self) -> None:
        # {p,q} vs {q,r}: |∩|=1, |∪|=3 → 1/3. Pinned: the matcher is
        # exact-string Jaccard and cannot see paraphrases — changing this
        # value means the similarity function changed, which is a
        # prompt-visible behaviour change and must be deliberate.
        a = _judge("a", ["p", "q"])
        b = _judge("b", ["q", "r"])
        assert _pairwise_agreement(a, b) == 1 / 3

    def test_duplicate_claims_do_not_inflate_agreement(self) -> None:
        # Jaccard over SETS: repeating a claim must not change the score.
        a1 = _judge("a", ["p", "q"])
        a2 = _judge("a2", ["p", "q", "p", "q"])
        b = _judge("b", ["q"])
        assert _pairwise_agreement(a1, b) == _pairwise_agreement(a2, b)


class TestComputeConsensusInvariants:
    def test_empty_outputs_safe(self) -> None:
        result = compute_consensus([])
        assert result.raw_agreement == 0.0
        assert result.contradiction_score == 0.0

    def test_single_judge_self_agreement(self) -> None:
        result = compute_consensus([_judge("only", ["p", "q"])])
        assert result.raw_agreement == 1.0
        assert result.contradiction_score == 0.0
        assert result.confidence_spread == 0.0

    def test_contradiction_score_is_complement_of_raw(self) -> None:
        judges = [
            _judge("a", ["p", "q"]),
            _judge("b", ["q", "r"]),
            _judge("c", ["r"]),
        ]
        result = compute_consensus(judges)
        assert result.contradiction_score == pytest.approx(1.0 - result.raw_agreement)

    def test_agreement_matrix_symmetric_with_unit_diagonal(self) -> None:
        judges = [
            _judge("a", ["p", "q"]),
            _judge("b", ["q", "r"]),
            _judge("c", ["r", "s"]),
        ]
        result = compute_consensus(judges)
        for i in result.agreement_matrix:
            assert result.agreement_matrix[i][i] == 1.0
            for j in result.agreement_matrix[i]:
                assert result.agreement_matrix[i][j] == result.agreement_matrix[j][i]

    def test_scores_in_unit_range(self) -> None:
        judges = [
            _judge("a", ["p"], confidence=0.1),
            _judge("b", ["q"], confidence=0.9),
        ]
        result = compute_consensus(judges)
        for value in (result.raw_agreement, result.weighted_agreement, result.contradiction_score):
            assert 0.0 <= value <= 1.0

    def test_unanimous_judges_full_majority(self) -> None:
        judges = [_judge(f"j{i}", ["p", "q"]) for i in range(4)]
        result = compute_consensus(judges)
        assert result.raw_agreement == 1.0
        assert set(result.majority_claims) == {"p", "q"}

    def test_confidence_spread_is_max_min(self) -> None:
        judges = [
            _judge("a", ["p"], confidence=0.2),
            _judge("b", ["p"], confidence=0.7),
            _judge("c", ["p"], confidence=0.5),
        ]
        result = compute_consensus(judges)
        assert result.confidence_spread == pytest.approx(0.5)

    def test_disjoint_claims_zero_agreement(self) -> None:
        judges = [_judge("a", ["p"]), _judge("b", ["q"])]
        result = compute_consensus(judges)
        assert result.raw_agreement == 0.0
        assert result.contradiction_score == 1.0
