from __future__ import annotations

import pytest

from core.schemas import AgentOutput, TaskProfile, calienneOutput
from orchestrator.knowledge_layer import KnowledgeLayer
from orchestrator.reasoning_layer import ReasoningLayer
from orchestrator.retrieval import RetrievalService, SourceCandidate, StaticOverrideProvider
from orchestrator.validation_layer import ValidationLayer


class _DecisionStub:
    async def execute_breaker_gate(self, **kwargs):
        return True, AgentOutput(reasoning_steps=["ok"], answer="continue", confidence=0.9)

    async def execute_generation_agents(self, **kwargs):
        output = AgentOutput(reasoning_steps=["ok"], answer="candidate", confidence=0.9)
        return output, output

    async def execute_judge_synthesis(self, **kwargs):
        return calienneOutput(
            final_answer="validated",
            overall_confidence="High",
            overall_bias_risk="Low",
            validation_score=9.0,
        )


@pytest.mark.asyncio
async def test_knowledge_layer_returns_retrieval_provenance() -> None:
    service = RetrievalService(
        provider=StaticOverrideProvider(
            [SourceCandidate(title="spec", excerpt="Known fact", relevance_score=1.0)]
        ),
        route_gating={"research": "required"},
    )
    bundle = await KnowledgeLayer(service).gather(
        query="Research known fact",
        task_profile=TaskProfile(task_type="research"),
    )

    assert bundle.facts[-1].content == "Known fact"
    assert bundle.facts[-1].provenance["kind"] == "retrieval"
    assert bundle.reasoning_history()[-1]["role"] == "user"


@pytest.mark.asyncio
async def test_reasoning_layer_preserves_decision_engine_contract() -> None:
    layer = ReasoningLayer(_DecisionStub())
    from core.passport import ExecutionPassport
    from orchestrator.knowledge_layer import KnowledgeBundle

    knowledge = KnowledgeBundle(query="hello")
    passport = ExecutionPassport()
    should_continue, breaker = await layer.run_breaker(
        knowledge=knowledge, gateway=None, strategy=None, pool=None, passport=passport
    )
    generated = await layer.generate(
        knowledge=knowledge, gateway=None, strategy=None, pool=None, passport=passport
    )

    assert should_continue is True
    assert breaker.answer == "continue"
    assert generated[0].answer == "candidate"


def test_validation_layer_owns_firewall_and_stage_assessment() -> None:
    layer = ValidationLayer()
    output, firewall = layer.validate_dag_output(
        user_query="What is timeout?",
        history=[{"role": "system", "content": "Timeout is 30 seconds."}],
        task_profile=TaskProfile(task_type="general"),
        strategic_plan=None,
        results={"final": {"final_response": "Timeout is 90 seconds."}},
    )

    assert "Qualifier:" in output.final_answer
    assert firewall["removed_or_qualified_count"] == 1
    assert layer.assess(TaskProfile(complexity="low")).confidence == 0.97
