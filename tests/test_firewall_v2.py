"""Firewall v2 tests — measured support scoring replaces keyword luck.

Acceptance criteria traced to evals/firewall_known_gaps.md:
  - class A rows (co-occurring keywords, unsupported subject) → unverified
  - substring containment still verifies
  - polarity (contradiction) behaviour unchanged
  - support_score recorded in provenance is a measured 0-1 value
"""

from __future__ import annotations

import pytest

from orchestrator.claims import (
    Claim,
    ClaimManager,
    ClaimType,
    EvidenceRecord,
    ValidationStatus,
    score_support,
    support_coverage,
)


def _validate(claim_text: str, evidence_texts: list[str]) -> ValidationStatus:
    manager = ClaimManager()
    claim = Claim(
        claim_id="t",
        content=claim_text,
        claim_type=ClaimType.FACTUAL,
        confidence=0.5,
        source_agent="test",
    )
    evidence = [
        EvidenceRecord(source_id=f"s{i}", evidence_type="context", content=text)
        for i, text in enumerate(evidence_texts)
    ]
    status = manager.validate_claim(claim, evidence)
    return status, claim


class TestScoreSupport:
    def test_identical_text_scores_one(self) -> None:
        assert score_support("The suite runs 439 tests.", ["The suite runs 439 tests."]) == 1.0

    def test_regular_inflections_stem_together(self) -> None:
        # logging/log, emitted/emit, windows/window — the naive stemmer with
        # double-consonant collapse must align these.
        assert support_coverage("logs are emitted", "logging emits") == 1.0
        assert support_coverage("the windows are open", "the window is open") == 1.0

    def test_negation_words_do_not_count_against_coverage(self) -> None:
        # Polarity is judged separately; "not" is not content.
        assert support_coverage("the service does not stream", "the service streams") == 1.0

    def test_disjoint_evidence_scores_zero(self) -> None:
        assert score_support("Revenue doubled in Q3", ["The office plant was watered"]) == 0.0

    def test_empty_evidence_scores_zero(self) -> None:
        assert score_support("anything", []) == 0.0

    def test_best_evidence_wins(self) -> None:
        score = score_support(
            "The gateway timeout is 600 seconds",
            ["irrelevant text here", "The gateway client uses a 600 second timeout"],
        )
        assert score >= 0.7


class TestKnownGapResolution:
    def test_class_a_revenue_row_now_unverified(self) -> None:
        status, _ = _validate(
            "Revenue doubled in the third quarter.",
            ["The company hired 40 engineers and opened two offices in the third quarter."],
        )
        assert status == ValidationStatus.UNVERIFIED

    def test_class_a_number_mismatch_still_unverified(self) -> None:
        status, _ = _validate(
            "Latency improved by 40 percent after the upgrade.",
            ["Latency improved by 18 percent after the upgrade was measured over one week."],
        )
        assert status == ValidationStatus.UNVERIFIED

    def test_verbatim_substring_still_verifies(self) -> None:
        status, _ = _validate(
            "The suite runs 439 tests",
            ["Context: The suite runs 439 tests across markers, verified today."],
        )
        assert status == ValidationStatus.VERIFIED

    def test_contradiction_parity_unchanged(self) -> None:
        status, _ = _validate(
            "The service does not support streaming responses.",
            ["The service supports streaming responses over server-sent events."],
        )
        assert status == ValidationStatus.CONTRADICTED

    def test_well_supported_paraphrase_verifies(self) -> None:
        status, _ = _validate(
            "Integration tests run against PostgreSQL 16.2.",
            ["Integration tests run against PostgreSQL 16.2 in the CI pipeline."],
        )
        assert status == ValidationStatus.VERIFIED

    def test_support_score_recorded_in_provenance(self) -> None:
        status, claim = _validate(
            "Integration tests run against PostgreSQL 16.2.",
            ["Integration tests run against PostgreSQL 16.2 in the CI pipeline."],
        )
        assert status == ValidationStatus.VERIFIED
        score = claim.provenance.get("support_score")
        assert isinstance(score, float) and 0.0 <= score <= 1.0


class TestCoverageEdgeCases:
    def test_stopword_only_claim_scores_zero_without_crashing(self) -> None:
        assert support_coverage("it is of the", "it is of the and with") == 0.0

    def test_threshold_is_a_class_constant(self) -> None:
        # 0.7 keeps the frozen corpus green; changing it is a gate-visible
        # behaviour change and must re-run evals/golden tests deliberately.
        assert ClaimManager.SUPPORT_COVERAGE_MIN == pytest.approx(0.7)


class TestDegenerateClaimSubstringBypass:
    """``"" in x`` is vacuously True: an empty (or near-empty) claim used to
    take the substring path straight to VERIFIED against any evidence."""

    def test_empty_claim_does_not_verify(self) -> None:
        status, _ = _validate("", ["Totally unrelated evidence text."])
        assert status == ValidationStatus.UNVERIFIED

    def test_whitespace_claim_does_not_verify(self) -> None:
        status, _ = _validate("   ", ["Totally unrelated evidence text."])
        assert status == ValidationStatus.UNVERIFIED

    def test_three_char_claim_does_not_take_substring_bypass(self) -> None:
        # "est" appears verbatim inside "best"/"test"/"established" but shares
        # no keyword with the evidence — old code verified it on substring
        # alone; the bypass now requires a claim long enough to carry meaning.
        status, _ = _validate(
            "est", ["The best test established coverage gates for the corpus."]
        )
        assert status == ValidationStatus.UNVERIFIED

    def test_meaningful_substring_claims_still_verify(self) -> None:
        # Four characters is the floor, not a new barrier: real verbatim
        # claims are sentences and must keep verifying.
        status, _ = _validate(
            "The suite runs 439 tests",
            ["Context: The suite runs 439 tests across markers, verified today."],
        )
        assert status == ValidationStatus.VERIFIED
