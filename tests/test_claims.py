from __future__ import annotations

from orchestrator.claims import ClaimManager, EvidenceRecord, ValidationStatus


def test_validate_claim_marks_supported_claim_verified() -> None:
    manager = ClaimManager()
    claim = manager.extract_claims("The API timeout is 30 seconds.", "judge")[0]

    status = manager.validate_claim(
        claim,
        [EvidenceRecord(source_id="config", evidence_type="source", content="The API timeout is 30 seconds in production.")],  # noqa: E501
    )

    assert status == ValidationStatus.VERIFIED
    assert claim.confidence >= 0.8
    assert claim.provenance["evidence"]


def test_apply_firewall_qualifies_unsupported_claims() -> None:
    manager = ClaimManager()

    result = manager.apply_firewall(
        "The API timeout is 90 seconds.",
        agent_name="judge",
        evidence=[EvidenceRecord(source_id="config", evidence_type="source", content="The API timeout is 30 seconds.")],  # noqa: E501
    )

    assert result.removed_or_qualified_count == 1
    assert "Qualifier:" in result.sanitized_text
    assert result.unsupported_claims[0].validation_status == ValidationStatus.UNVERIFIED


def test_factual_claim_circular_sibling_reasoning_remains_unverified() -> None:
    manager = ClaimManager()
    claim = manager.extract_claims("The database is configured with 50 tables.", "creative")[0]

    # Sibling agent output with evidence_type="reasoning"
    status = manager.validate_claim(
        claim,
        [
            EvidenceRecord(
                source_id="logician",
                evidence_type="reasoning",
                content="The database is configured with 50 tables.",
            )
        ],
    )

    assert status == ValidationStatus.UNVERIFIED
    assert claim.confidence < 0.5
    assert claim.provenance.get("unverified_reason") == "circular_sibling_reasoning_only"
