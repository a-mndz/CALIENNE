"""Judge, consensus, repair, firewall, and validation-owned schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.schemas import (
    AgentOutput,
    ClarificationRequest,
    StageAssessment,
    TaskProfile,
    calienneOutput,
)
from orchestrator.claims import ClaimManager
from orchestrator.knowledge_layer import KnowledgeBundle


class ValidationLayer:
    """Own all post-generation validation behavior."""

    def __init__(self, claim_manager: ClaimManager | None = None) -> None:
        self._claim_manager = claim_manager or ClaimManager()

    async def judge(
        self,
        *,
        decision_engine: Any,
        knowledge: KnowledgeBundle,
        logician_output: AgentOutput | None,
        creative_output: AgentOutput | None,
        gateway: Any,
        strategy: Any,
        pool: Any,
        passport: Any,
    ) -> calienneOutput:
        return await decision_engine.execute_judge_synthesis(
            query=knowledge.query,
            logician_output=logician_output,
            creative_output=creative_output,
            gateway=gateway,
            strategy=strategy,
            pool=pool,
            passport=passport,
            lessons=knowledge.lessons,
            history=knowledge.reasoning_history(),
        )

    def process_claims(
        self,
        *,
        outputs: list[tuple[str, Any]],
        user_query: str,
        history: list[dict[str, str]] | None,
        reasoning_graph: Any | None,
        enabled: bool = True,
    ) -> list[Any]:
        if not enabled:
            return []

        evidence = self._claim_manager.build_evidence(
            user_query=user_query,
            history=history,
            agent_outputs={name: output for name, output in outputs if output is not None},
        )
        claims: list[Any] = []
        timestamp = datetime.now(timezone.utc)
        for agent_name, agent_output in outputs:
            answer = getattr(agent_output, "answer", "")
            if isinstance(agent_output, dict):
                answer = agent_output.get("answer", "")
            if not answer:
                continue
            extracted = self._claim_manager.extract_claims(answer, agent_name)
            for claim in extracted:
                self._claim_manager.validate_claim(
                    claim,
                    [record for record in evidence if record.source_id != agent_name],
                )
                if reasoning_graph is not None:
                    self._claim_manager.store_claim(claim, reasoning_graph)
                self._claim_manager.track_claim_provenance(
                    claim,
                    source=agent_name,
                    timestamp=timestamp,
                    validation_method="evidence_checker",
                )
            claims.extend(extracted)
        return claims

    def apply_firewall(
        self,
        *,
        final_text: str,
        user_query: str,
        history: list[dict[str, str]] | None,
        agent_outputs: dict[str, Any],
        reasoning_graph: Any | None,
        enabled: bool = True,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
        if not enabled:
            return final_text, [], None

        evidence = self._claim_manager.build_evidence(
            user_query=user_query,
            history=history,
            agent_outputs=agent_outputs,
        )
        firewall = self._claim_manager.apply_firewall(
            final_text,
            agent_name="judge",
            evidence=[record for record in evidence if record.source_id != "judge"],
        )
        timestamp = datetime.now(timezone.utc)
        for claim in firewall.claims:
            if reasoning_graph is not None:
                self._claim_manager.store_claim(claim, reasoning_graph)
            self._claim_manager.track_claim_provenance(
                claim,
                source=claim.source_agent,
                timestamp=timestamp,
                validation_method="evidence_checker",
            )
        unsupported = self._claim_manager.get_unverified_claims(claims=firewall.claims)
        unsupported_payload = [self.claim_dict(claim) for claim in unsupported]
        return firewall.sanitized_text, unsupported_payload, {
            "original_text": firewall.original_text,
            "sanitized_text": firewall.sanitized_text,
            "removed_or_qualified_count": firewall.removed_or_qualified_count,
            "unsupported_claims": unsupported_payload,
        }

    def validate_dag_output(
        self,
        *,
        user_query: str,
        history: list[dict[str, str]] | None,
        task_profile: TaskProfile,
        strategic_plan: Any | None,
        results: dict[str, Any],
        final_node_id: str | None = None,
    ) -> tuple[calienneOutput, dict[str, Any]]:
        final_node_id = final_node_id or (next(reversed(results.keys())) if results else "")
        final_result = results.get(final_node_id, {}) if final_node_id else {}
        final_text = str(final_result.get("final_response") or final_result.get("objective") or "")
        evidence = self._claim_manager.build_evidence(
            user_query=user_query,
            history=history,
            agent_outputs={
                "task_profile": task_profile.model_dump(),
                "strategic_plan": strategic_plan.model_dump() if strategic_plan is not None else None,
            },
            prior_results={
                node_id: result.get("final_response") or result.get("objective") or ""
                for node_id, result in results.items()
                if node_id != final_node_id
            },
        )
        firewall = self._claim_manager.apply_firewall(final_text, agent_name="final", evidence=evidence)
        unsupported = self._claim_manager.get_unverified_claims(claims=firewall.claims)
        notes = []
        if firewall.removed_or_qualified_count:
            notes.append(
                f"Hallucination firewall qualified {firewall.removed_or_qualified_count} unsupported claim(s)."  # noqa: E501
            )
        # Stage 2: the score is the measured fraction of supported claims,
        # not a hardcoded 7.5/9.0. Zero extracted claims is vacuous support —
        # stated in the notes rather than silently scored as perfect.
        total_claims = len(firewall.claims)
        unsupported_count = len(unsupported)
        if total_claims:
            support_ratio = (total_claims - unsupported_count) / total_claims
        else:
            support_ratio = 1.0
            notes.append("No claims extracted — support score is vacuous, not measured.")
        validation_score = round(10.0 * support_ratio, 1)
        if unsupported_count == 0:
            overall_confidence = "High"
        elif support_ratio >= 0.5:
            overall_confidence = "Medium"
        else:
            overall_confidence = "Low"
        output = calienneOutput(
            final_answer=firewall.sanitized_text or final_text,
            overall_confidence=overall_confidence,
            overall_bias_risk="Medium" if unsupported else "Low",
            disagreement_notes=notes,
            validation_score=validation_score,
        )
        return output, {
            "original_text": firewall.original_text,
            "sanitized_text": firewall.sanitized_text,
            "removed_or_qualified_count": firewall.removed_or_qualified_count,
            "unsupported_claims": [self.claim_dict(claim) for claim in unsupported],
        }

    @staticmethod
    def assess(task_profile: TaskProfile) -> StageAssessment:
        """Return UNCALIBRATED PRIOR estimates for the uncertainty engine.

        These lookup tables are seed priors, not measurements — nothing here
        traces to an observation. They may bias the uncertainty engine until
        calibrated against real outcome data (Experience DB); treat every
        field accordingly and never surface them as telemetry.
        """
        confidence = {"low": 0.97, "medium": 0.92, "high": 0.88, "critical": 0.82}
        calibration = {"low": 0.90, "medium": 0.86, "high": 0.82, "critical": 0.78}
        route = {
            "general": (0.0, 0.0, 0.0, 0),
            "creative": (0.0, 0.0, 0.0, 0),
            "coding": (0.6, 0.65, 0.6, 1),
            "research": (0.72, 0.65, 0.55, 2),
            "math": (0.65, 0.72, 0.65, 1),
        }.get(task_profile.task_type, (0.0, 0.0, 0.0, 0))
        return StageAssessment(
            confidence=confidence.get(task_profile.complexity, 0.90),
            calibration=calibration.get(task_profile.complexity, 0.85),
            evidence_strength=route[0],
            agreement=route[1],
            stability=route[2],
            reasoning_quality="strong" if task_profile.complexity in {"low", "medium"} else "adequate",
            evidence_count=route[3],
        )

    @staticmethod
    def clarification_request(
        *,
        question: str,
        reason: str,
        missing_context: list[str] | None = None,
        options: list[str] | None = None,
    ) -> ClarificationRequest:
        return ClarificationRequest(
            question=question,
            reason=reason,
            missing_context=missing_context or [],
            options=options or [],
        )

    @staticmethod
    def claim_dict(claim: Any) -> dict[str, Any]:
        return {
            "claim_id": claim.claim_id,
            "content": claim.content,
            "claim_type": claim.claim_type.value,
            "confidence": claim.confidence,
            "source_agent": claim.source_agent,
            "validation_status": claim.validation_status.value,
            "evidence": (claim.provenance or {}).get("evidence", []),
        }
