"""Tests for PlannerCommand (DispatchNode, SkipNode, FanOut) and ExecutionPlanner."""

from __future__ import annotations

import pytest

from core.schemas import PipelineBudget, StrategicPlan, TaskProfile
from orchestrator.execution_planner import ExecutionPlanner
from orchestrator.planner_command import (
    DispatchNode,
    FanOut,
    SkipNode,
    apply_skip_node,
)

pytestmark = pytest.mark.unit


def test_dispatch_node_creates_one_task() -> None:
    planner = ExecutionPlanner()
    profile = TaskProfile(task_type="coding", complexity="medium", needs_decomposition=True)
    plan = StrategicPlan(
        goal="Run worker dispatch",
        commands=[DispatchNode("worker", {"task": "execute_task"})],
    )

    graph = planner.create_graph(profile, strategic_plan=plan)

    assert len(graph.nodes) == 1
    node = graph.nodes[0]
    assert node.task_id == "worker"
    assert node.output_contract is not None
    assert len(node.output_contract.produced_fields) > 0


def test_skip_node_rewires_dependents() -> None:
    planner = ExecutionPlanner()
    node_a = planner._make_node("A", "Objective A", depends_on=["root"], tier="default", priority="normal")
    node_b = planner._make_node("B", "Objective B", depends_on=["A"], tier="default", priority="normal")
    node_c = planner._make_node("C", "Objective C", depends_on=["B"], tier="default", priority="normal")

    # Skipping A rewires B's dependency to A's dependency ("root")
    rewired_once = apply_skip_node([node_a, node_b, node_c], "A")
    assert len(rewired_once) == 2
    assert {n.task_id for n in rewired_once} == {"B", "C"}
    b_node = next(n for n in rewired_once if n.task_id == "B")
    assert b_node.depends_on == ["root"]

    # Transitive skip: now skip B, C's dependency should rewire to B's dependency ("root")
    rewired_twice = apply_skip_node(rewired_once, "B")
    assert len(rewired_twice) == 1
    c_node = rewired_twice[0]
    assert c_node.task_id == "C"
    assert c_node.depends_on == ["root"]


def test_fanout_creates_parallel_tasks() -> None:
    planner = ExecutionPlanner()
    profile = TaskProfile(task_type="research", complexity="high", needs_decomposition=True)
    payloads = [
        {"query": "evidence_1"},
        {"query": "evidence_2"},
        {"query": "evidence_3"},
    ]
    plan = StrategicPlan(
        goal="Fan out research",
        commands=[FanOut("researcher", payloads)],
    )

    graph = planner.create_graph(profile, strategic_plan=plan)

    assert len(graph.nodes) == 3
    for idx, node in enumerate(graph.nodes, start=1):
        assert node.task_id == f"researcher_{idx}"
        assert node.can_run_parallel is True
        assert node.depends_on == []


def test_sub_problems_path_still_works() -> None:
    planner = ExecutionPlanner()
    profile = TaskProfile(task_type="coding", complexity="medium", needs_decomposition=True)
    plan = StrategicPlan(
        goal="Standard plan with sub-problems",
        sub_problems=["Task 1", "Task 2"],
    )

    graph = planner.create_graph(profile, strategic_plan=plan)

    task_ids = [n.task_id for n in graph.nodes]
    assert "classify" in task_ids
    assert "plan" in task_ids
    assert "work_1" in task_ids
    assert "work_2" in task_ids
    assert "final" in task_ids
    assert len(graph.nodes) == 5


def test_skip_node_within_commands_graph() -> None:
    planner = ExecutionPlanner()
    profile = TaskProfile(task_type="coding", complexity="medium", needs_decomposition=True)
    plan = StrategicPlan(
        goal="Commands with skip",
        commands=[
            DispatchNode("A", {}, task_id="A", depends_on=[]),
            DispatchNode("B", {}, task_id="B", depends_on=["A"]),
            SkipNode("A"),
        ],
    )

    graph = planner.create_graph(profile, strategic_plan=plan)

    assert len(graph.nodes) == 1
    assert graph.nodes[0].task_id == "B"
    assert graph.nodes[0].depends_on == []


def test_fanout_with_shared_explicit_dependency() -> None:
    planner = ExecutionPlanner()
    profile = TaskProfile(task_type="coding", complexity="high", needs_decomposition=True)
    plan = StrategicPlan(
        goal="Fan out with explicit upstream dependency",
        commands=[
            DispatchNode("prep", {}, task_id="prep"),
            FanOut("coder", [{"part": 1}, {"part": 2}], depends_on=["prep"]),
        ],
    )

    graph = planner.create_graph(profile, strategic_plan=plan)
    assert len(graph.nodes) == 3
    coder_nodes = [n for n in graph.nodes if n.task_id.startswith("coder_")]
    assert len(coder_nodes) == 2
    for node in coder_nodes:
        assert node.depends_on == ["prep"]
        assert node.can_run_parallel is True


def test_skip_node_on_sub_problems() -> None:
    planner = ExecutionPlanner()
    profile = TaskProfile(task_type="coding", complexity="medium", needs_decomposition=True)
    plan = StrategicPlan(
        goal="Sub problems with skip",
        sub_problems=["Task 1", "Task 2"],
        commands=[SkipNode("work_1")],
    )

    graph = planner.create_graph(profile, strategic_plan=plan)
    task_ids = [n.task_id for n in graph.nodes]
    assert "work_1" not in task_ids
    assert "work_2" in task_ids
    work_2 = next(n for n in graph.nodes if n.task_id == "work_2")
    # work_2 previously depended on work_1 or plan; now work_1 is skipped and rewired to plan
    assert "plan" in work_2.depends_on
