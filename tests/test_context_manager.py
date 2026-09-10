from __future__ import annotations

import asyncio

import pytest

from core.schemas import PipelineBudget, StrategicPlan, TaskNode, TaskProfile
from orchestrator.context_manager import ContextManager
from orchestrator.contracts import InputContract, OutputContract


def _node() -> TaskNode:
    return TaskNode(
        task_id="plan",
        objective="Plan the research response around the key findings",
        input_contract=InputContract(
            required_fields=["request", "task_profile", "strategic_plan"],
            allowed_types=["dict"],
            validation_rules={},
        ),
        output_contract=OutputContract(
            produced_fields=["research_plan"],
            types={"research_plan": "string"},
        ),
    )


@pytest.mark.asyncio
async def test_context_manager_assembles_bounded_window_and_carries_input_contract() -> None:
    manager = ContextManager(max_window_tokens=800)
    history = [
        {"role": "system", "content": "Always preserve system constraints."},
        {"role": "developer", "content": "Follow repository conventions and existing tests."},
        {"role": "user", "content": "Small talk that is not very relevant."},
        {"role": "assistant", "content": "A casual reply with little bearing on the task."},
        {"role": "user", "content": "The research answer must cite evidence and note tradeoffs."},
        {"role": "assistant", "content": "I will keep sources and tradeoffs in view."},
    ]
    profile = TaskProfile(task_type="research", complexity="high", requires_rag=True)
    strategic_plan = StrategicPlan(goal="Research the issue", sub_problems=["Find evidence"])

    window = await manager.assemble_window(
        _node(),
        user_query="Research the issue and compare the evidence.",
        task_profile=profile,
        strategic_plan=strategic_plan,
        history=history,
        budget=PipelineBudget(total_tokens=2_000),
    )

    contents = [message["content"] for message in window.messages]
    assert contents[0] == "Always preserve system constraints."
    assert any("Follow repository conventions" in content for content in contents)
    assert any("cite evidence and note tradeoffs" in content for content in contents)
    assert window.input_contract == _node().input_contract
    assert window.incoming_outputs["request"] == "Research the issue and compare the evidence."
    assert window.incoming_outputs["strategic_plan"] == strategic_plan


@pytest.mark.asyncio
async def test_context_manager_route_gates_retrieval_hooks() -> None:
    calls: list[str] = []

    def retrieval_provider(**kwargs):
        task_profile = kwargs["task_profile"]
        calls.append(task_profile.task_type)
        return [{"source": "retrieval", "content": "Source-backed research note."}]

    manager = ContextManager(retrieval_provider=retrieval_provider)
    node = _node()

    research_window = await manager.assemble_window(
        node,
        user_query="Research the issue.",
        task_profile=TaskProfile(task_type="research", complexity="medium", requires_rag=True),
        history=[],
    )
    coding_window = await manager.assemble_window(
        node,
        user_query="Debug the endpoint.",
        task_profile=TaskProfile(task_type="coding", complexity="medium", requires_code_context=True),
        history=[],
    )

    assert calls == ["research"]
    assert research_window.retrieved_snippets[0].content == "Source-backed research note."
    assert coding_window.retrieved_snippets == []


@pytest.mark.asyncio
async def test_context_manager_raises_insufficient_capacity_on_oversized_constraints() -> None:
    from orchestrator.memory_manager import InsufficientCapacityError

    manager = ContextManager(max_window_tokens=256)
    node = _node()
    huge_system_constraint = "System constraint rule: " + "repeat instruction " * 200

    with pytest.raises(InsufficientCapacityError, match="insufficient context window capacity"):
        await manager.assemble_window(
            node,
            user_query="Run task",
            history=[{"role": "system", "content": huge_system_constraint}],
            budget=PipelineBudget(total_tokens=256),
        )
