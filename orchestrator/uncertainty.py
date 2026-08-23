"""Deterministic uncertainty engine for ambiguity and risk handling."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field

from core.base import CalienneBaseModel
from core.schemas import Prediction, StageAssessment, TaskProfile
from orchestrator.validation_layer import ClarificationRequest, ValidationLayer

UncertaintyOutcome = Literal[
    "continue_execution",
    "run_retrieval",
    "ask_user_clarification",
    "request_more_context",
    "escalate_model",
    "run_additional_checker",
    "synthesize_with_uncertainty",
]

_AMBIGUOUS_REFERENCE_PATTERNS: tuple[str, ...] = (
    r"\b(?:this|that|it|they|them|those|these)\b",
    r"\b(?:something|stuff|thing|things)\b",
)
_CHOICE_PATTERNS: tuple[str, ...] = (
    r"\b(?:which one|which is better|which should|or should i)\b",
    r"\b(?:maybe|not sure|unsure|unclear|ambiguous)\b",
)
_CODE_CONTEXT_REFERENCE_PATTERNS: tuple[str, ...] = (
    r"\b(?:this file|that file|this function|that function|this module|that module)\b",
    r"\b(?:here|above|below|attached)\b",
)


class UncertaintyDecision(CalienneBaseModel):
    """Outcome and rationale from the uncertainty engine."""

    outcome: UncertaintyOutcome = "continue_execution"
    reason: str = ""
    confidence: float = 1.0
    clarification_request: ClarificationRequest | None = None
    missing_context: list[str] = Field(default_factory=list)
    recommended_action: str | None = None


class UncertaintyEngine:
    """Choose the least-hallucinatory next step from deterministic signals."""

    def __init__(self, validation_layer: ValidationLayer | None = None) -> None:
        self._validation_layer = validation_layer or ValidationLayer()

    def evaluate(
        self,
        *,
        user_query: str,
        task_profile: TaskProfile,
        stage_assessment: StageAssessment | None = None,
        prediction: Prediction | None = None,
        available_context_keys: list[str] | None = None,
    ) -> UncertaintyDecision:
        query = user_query.strip()
        lowered = query.lower()
        available = set(available_context_keys or [])

        if self._needs_clarification(query, lowered, task_profile, available):
            missing_context = self._missing_context_hints(task_profile, lowered, available)
            clarification = self._validation_layer.clarification_request(
                question=self._clarification_question(task_profile),
                reason="The request is ambiguous or refers to missing context.",
                missing_context=missing_context or ["target scope", "expected outcome"],
                options=self._clarification_options(task_profile),
            )
            return UncertaintyDecision(
                outcome="ask_user_clarification",
                reason="Ambiguous prompt should yield a structured clarification request.",
                confidence=0.25,
                clarification_request=clarification,
                missing_context=clarification.missing_context,
                recommended_action="Clarify before continuing.",
            )

        if (
            task_profile.requires_code_context
            and self._references_missing_code_context(lowered)
            and not {"code_context", "implementation_plan", "task_profile"}.intersection(available)
        ):
            missing = ["target file or function", "expected code change"]
            return UncertaintyDecision(
                outcome="request_more_context",
                reason="The task refers to code context that is not present in the current window.",
                confidence=0.40,
                missing_context=missing,
                recommended_action="Request the missing repository context.",
            )

        if prediction is not None and prediction.probability_of_retrieval_needed >= 0.5:
            return UncertaintyDecision(
                outcome="run_retrieval",
                reason="Prediction indicates retrieval is likely required before reliable synthesis.",
                confidence=max(0.5, 1.0 - prediction.probability_of_retrieval_needed / 2),
                recommended_action="Retrieve relevant evidence first.",
            )

        if prediction is not None and (
            prediction.probability_of_failure >= 0.45
            or prediction.probability_of_clarification_needed >= 0.4
        ):
            return UncertaintyDecision(
                outcome="escalate_model",
                reason="Predicted failure or clarification pressure is high enough to justify a stronger model path.",  # noqa: E501
                confidence=max(0.35, 1.0 - prediction.probability_of_failure),
                recommended_action="Escalate model tier or provider quality.",
            )

        if stage_assessment is not None and (
            (stage_assessment.contradiction_score > 0.0 and stage_assessment.contradiction_score <= 0.05)
            or (stage_assessment.agreement is not None and stage_assessment.agreement < 0.55)
        ):
            return UncertaintyDecision(
                outcome="run_additional_checker",
                reason="A light contradiction or weak agreement signal benefits from an additional checker.",
                confidence=0.55,
                recommended_action="Run an additional verifier or checker.",
            )

        if stage_assessment is not None and (
            stage_assessment.unsupported_claim_count > 0
            or (stage_assessment.calibration is not None and stage_assessment.calibration < 0.7)
        ):
            return UncertaintyDecision(
                outcome="synthesize_with_uncertainty",
                reason="The best safe fallback is to answer with explicit caveats rather than over-commit.",
                confidence=0.5,
                recommended_action="Synthesize with visible uncertainty caveats.",
            )

        return UncertaintyDecision(
            outcome="continue_execution",
            reason="No uncertainty trigger exceeded the intervention thresholds.",
            confidence=0.9,
            recommended_action="Continue the current execution path.",
        )

    @staticmethod
    def _needs_clarification(
        query: str,
        lowered: str,
        task_profile: TaskProfile,
        available_context_keys: set[str],
    ) -> bool:
        token_count = len(re.findall(r"\b\w+\b", lowered))
        ambiguous_reference = any(re.search(pattern, lowered) for pattern in _AMBIGUOUS_REFERENCE_PATTERNS)
        explicit_choice = any(re.search(pattern, lowered) for pattern in _CHOICE_PATTERNS)
        code_reference = task_profile.requires_code_context and UncertaintyEngine._references_missing_code_context(lowered)  # noqa: E501
        lacks_anchor = not re.search(r"\b[a-z0-9_./\\-]+\.(?:py|ts|tsx|js|jsx|sql|json|md)\b", lowered)
        if explicit_choice and token_count <= 16:
            return True
        if code_reference and lacks_anchor and not available_context_keys:
            return True
        return ambiguous_reference and token_count <= 7 and lacks_anchor

    @staticmethod
    def _references_missing_code_context(lowered: str) -> bool:
        return any(re.search(pattern, lowered) for pattern in _CODE_CONTEXT_REFERENCE_PATTERNS)

    @staticmethod
    def _missing_context_hints(
        task_profile: TaskProfile,
        lowered: str,
        available_context_keys: set[str],
    ) -> list[str]:
        missing: list[str] = []
        if task_profile.requires_code_context and not available_context_keys:
            missing.extend(["target file or function", "expected code behavior"])
        if "compare" in lowered or "better" in lowered:
            missing.append("comparison criteria")
        if "fix" in lowered or "change" in lowered:
            missing.append("desired end state")
        return missing

    @staticmethod
    def _clarification_question(task_profile: TaskProfile) -> str:
        if task_profile.requires_code_context:
            return "Which file, function, or module should I focus on?"
        if task_profile.task_type == "research":
            return "What specific question or scope should the research answer?"
        return "What exactly should I focus on?"

    @staticmethod
    def _clarification_options(task_profile: TaskProfile) -> list[str]:
        if task_profile.requires_code_context:
            return [
                "Point me to the exact file or function.",
                "Describe the expected behavior or fix.",
            ]
        if task_profile.task_type == "research":
            return [
                "Narrow the topic or timeframe.",
                "State the comparison criteria or decision goal.",
            ]
        return [
            "Clarify the target scope.",
            "Describe the expected final outcome.",
        ]
