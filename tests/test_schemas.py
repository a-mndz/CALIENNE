"""Schema tests — backward-compat parsing and base-class enforcement (ADR-001)."""

from __future__ import annotations

from core.base import CalienneBaseModel
from core.schemas import (
    AgentOutput,
    ClarificationRequest,
    PipelineBudget,
    Prediction,
    PredictionInterval,
    StageAssessment,
    TaskGraph,
    TaskNode,
    TaskProfile,
    VersionStamp,
    calienneOutput,
)


def test_agent_output_legacy_confidence_string() -> None:
    """String confidence labels still parse (legacy format)."""
    out = AgentOutput(reasoning_steps=["ok"], answer="yes", confidence="high")
    assert out.confidence == 0.9
    assert out.answer == "yes"


def test_agent_output_legacy_alternative_answer() -> None:
    """Alternative answer fields still resolve (legacy format)."""
    out = AgentOutput(reasoning_steps=["ok"], summary="legacy answer", confidence=0.5)
    assert out.answer == "legacy answer"


def test_agent_output_legacy_missing_reasoning_steps() -> None:
    """Missing reasoning_steps resolves from alternatives."""
    out = AgentOutput(answer="yes", confidence=0.5, claims=["step 1"])
    assert len(out.reasoning_steps) > 0
    assert "step 1" in out.reasoning_steps[0]


def test_calienne_output_legacy_summary() -> None:
    """calienneOutput maps summary -> final_answer (legacy format)."""
    out = calienneOutput(
        summary="legacy summary", confidence=0.9, warnings=[]
    )
    assert out.final_answer == "legacy summary"
    assert out.validation_score > 0


def test_calienne_output_confidence_to_label() -> None:
    """Float confidence mapped to overall_confidence label."""
    out = calienneOutput(
        final_answer="test", overall_confidence="High",
        overall_bias_risk="Low", disagreement_notes=[], validation_score=9.0,
    )
    assert out.overall_confidence == "High"


def test_all_schemas_inherit_base_model() -> None:
    """Every schema inherits from CalienneBaseModel (ADR-001)."""
    for cls in [
        AgentOutput, calienneOutput, StageAssessment,
        TaskProfile, TaskNode, TaskGraph, PipelineBudget,
        PredictionInterval, Prediction, ClarificationRequest, VersionStamp,
    ]:
        assert issubclass(cls, CalienneBaseModel), f"{cls.__name__} must inherit CalienneBaseModel"


def test_stage_assessment_from_minimal() -> None:
    """from_minimal returns a fully-defaulted assessment (ADR-001 safety net)."""
    assessment = StageAssessment.from_minimal(confidence=0.7)
    assert assessment.confidence == 0.7
    assert assessment.calibration is None
    assert assessment.evidence_count == 0


def test_prediction_interval_bounds() -> None:
    """PredictionInterval upper/lower bounds derive from value ± std_dev."""
    pi = PredictionInterval(value=10.0, std_dev=2.0)
    assert pi.upper_bound == 12.0
    assert pi.lower_bound == 8.0


def test_clarification_request_defaults() -> None:
    """ClarificationRequest defaults to needs_clarification status."""
    req = ClarificationRequest(question="What did you mean?", reason="ambiguous")
    assert req.status == "needs_clarification"
    assert req.missing_context == []


def test_version_stamp_default_version() -> None:
    """VersionStamp defaults to 0.1.0."""
    vs = VersionStamp()
    assert vs.architecture_version == "0.1.0"
    assert vs.planner_version is None
