from __future__ import annotations

import asyncio

import pytest

from core.passport import ExecutionPassport
from core.runtime import RuntimeContract
from core.schemas import TaskGraph, TaskNode
from orchestrator.execution_manager import ExecutionManager
from orchestrator.feature_flags import FeatureFlags
from orchestrator.scheduler import Scheduler


def _graph(*nodes: TaskNode) -> TaskGraph:
    return TaskGraph(nodes=list(nodes), root_task_id=nodes[0].task_id, final_task_id=nodes[-1].task_id)


def _node(task_id: str, *, depends_on: list[str] | None = None, priority: str = "normal", can_run_parallel: bool = True) -> TaskNode:  # noqa: E501
    from orchestrator.contracts import OutputContract

    return TaskNode(
        task_id=task_id,
        objective=f"objective for {task_id}",
        depends_on=depends_on or [],
        priority=priority,
        can_run_parallel=can_run_parallel,
        output_contract=OutputContract(produced_fields=["result"], types={"result": "string"}),
    )


class _UnsupportedClaimPlanner:
    def __init__(self) -> None:
        from orchestrator.contracts import OutputContract

        self._final_contract = OutputContract(
            produced_fields=["final_response"],
            types={"final_response": "string"},
        )
        self.last_skill_plan = None

    def create_graph(self, task_profile, strategic_plan=None, budget=None, enable_skill_composition=False, force_skills=None, block_skills=None):  # noqa: E501
        return TaskGraph(
            nodes=[
                TaskNode(
                    task_id="final",
                    objective="The API timeout is 90 seconds.",
                    output_contract=self._final_contract,
                )
            ],
            root_task_id="final",
            final_task_id="final",
        )


@pytest.mark.asyncio
async def test_scheduler_respects_dependency_order() -> None:
    order: list[str] = []

    async def executor(node: TaskNode, prior_results: dict[str, object]) -> str:
        order.append(node.task_id)
        await asyncio.sleep(0.01)
        return node.task_id

    graph = _graph(
        _node("plan"),
        _node("implement", depends_on=["plan"], can_run_parallel=False),
        _node("verify", depends_on=["implement"], can_run_parallel=False),
    )
    scheduler = Scheduler(executor=executor, concurrency_limit=3)

    results = await scheduler.run(graph)

    assert order == ["plan", "implement", "verify"]
    assert results["verify"] == "verify"


@pytest.mark.asyncio
async def test_scheduler_runs_zero_dependency_nodes_in_parallel() -> None:
    started: set[str] = set()
    gate = asyncio.Event()

    async def executor(node: TaskNode, prior_results: dict[str, object]) -> str:
        started.add(node.task_id)
        if len(started) >= 2:
            gate.set()
        await gate.wait()
        return node.task_id

    graph = TaskGraph(
        nodes=[_node("a"), _node("b"), _node("final", depends_on=["a", "b"], can_run_parallel=False)],
        root_task_id="a",
        final_task_id="final",
    )
    scheduler = Scheduler(executor=executor, concurrency_limit=2)

    results = await scheduler.run(graph)

    assert started >= {"a", "b"}
    assert results["final"] == "final"


@pytest.mark.asyncio
async def test_scheduler_condition_does_not_block_sibling_on_slow_call() -> None:
    completion_order: list[str] = []

    async def executor(node: TaskNode, prior_results: dict[str, object]) -> str:
        if node.task_id == "slow":
            await asyncio.sleep(0.05)
        else:
            await asyncio.sleep(0.01)
        completion_order.append(node.task_id)
        return node.task_id

    graph = TaskGraph(
        nodes=[_node("slow"), _node("fast"), _node("final", depends_on=["slow", "fast"], can_run_parallel=False)],  # noqa: E501
        root_task_id="slow",
        final_task_id="final",
    )
    scheduler = Scheduler(executor=executor, concurrency_limit=2)

    await scheduler.run(graph)

    assert completion_order.index("fast") < completion_order.index("slow")


class _FallbackDecisionEngine:
    BREAKER_TIMEOUT_MS: int = 100
    PARALLEL_AGENT_TIMEOUT_SEC: int = 30

    async def execute_breaker_gate(self, *, query, gateway, strategy, pool, passport, history=None):
        from orchestrator.pipelines import AgentOutput

        return True, AgentOutput(reasoning_steps=["ok"], answer="continue", confidence=0.9)

    async def execute_generation_agents(self, *, query, gateway, strategy, pool, passport, history=None):
        from orchestrator.pipelines import AgentOutput

        out = AgentOutput(reasoning_steps=["ok"], answer="fallback", confidence=0.9)
        return out, out

    async def execute_judge_synthesis(self, *, query, logician_output, creative_output, gateway, strategy, pool, passport, lessons="", history=None):  # noqa: E501
        from core.schemas import calienneOutput

        return calienneOutput(
            final_answer="fallback verdict",
            overall_confidence="High",
            overall_bias_risk="Low",
            disagreement_notes=[],
            validation_score=9.0,
        )


@pytest.mark.asyncio
async def test_execution_manager_dag_off_falls_back_to_run_micro_mode(
    stub_gateway, stub_strategy, stub_pool, stub_streaming
) -> None:
    manager = ExecutionManager(flags=FeatureFlags(dag=False, planner=False))
    passport = ExecutionPassport()

    result = await manager.execute(
        user_query="hello",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
        passport=passport,
        decision_engine=_FallbackDecisionEngine(),
        streaming_manager=stub_streaming,
    )

    assert result["status"] == "success"
    assert result["winning_answer"] == "fallback verdict"
    assert result["passport"] == passport.to_dict()


@pytest.mark.asyncio
async def test_execution_manager_passes_injected_knowledge_flag_to_fallback(
    monkeypatch, stub_gateway, stub_strategy, stub_pool, stub_streaming
) -> None:
    from orchestrator.knowledge_layer import KnowledgeLayer

    calls = 0
    original = KnowledgeLayer.gather

    async def tracked_gather(self, **kwargs):
        nonlocal calls
        calls += 1
        return await original(self, **kwargs)

    monkeypatch.setattr(KnowledgeLayer, "gather", tracked_gather)
    manager = ExecutionManager(flags=FeatureFlags(dag=False, knowledge_layer=True))

    result = await manager.execute(
        user_query="hello",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
        decision_engine=_FallbackDecisionEngine(),
        streaming_manager=stub_streaming,
    )

    assert result["status"] == "success"
    assert calls == 1


def test_component_factory_wires_execution_manager() -> None:
    from orchestrator.calienne_orchestrator import initialize_calienne_components

    components = initialize_calienne_components()

    assert isinstance(components["execution_manager"], ExecutionManager)


@pytest.mark.asyncio
async def test_execution_manager_dag_on_returns_graph_results(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    manager = ExecutionManager(flags=FeatureFlags(dag=True, planner=True))

    result = await manager.execute(
        user_query="Fix server.py and add tests, then verify the behavior.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )

    assert result["status"] == "success"
    assert result["graph"].final_task_id == "final"
    assert "final" in result["results"]
    assert result["execution_manifest"] is result["graph"].execution_manifest
    assert result["version_stamp"] is result["graph"].version_stamp
    assert result["graph"].graph_version.startswith("v")
    assert len(result["graph"].graph_fingerprint) == 64
    assert result["version_stamp"].graph_fingerprint == result["graph"].graph_fingerprint
    assert result["dashboard_metrics"]["planner.fingerprint.hash"] == result["graph"].graph_fingerprint
    assert result["dashboard_metrics"]["learning.graph.fingerprint"] == result["graph"].graph_fingerprint


@pytest.mark.asyncio
async def test_execution_manager_dag_calls_gateway_and_returns_semantic_answer(
    stub_strategy, stub_pool
) -> None:
    class Gateway:
        def __init__(self) -> None:
            self.calls = []

        async def execute_with_fallback(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs["role"] == "judge":
                return '{"final_answer":"Verified semantic result"}'
            return '{"answer":"Executed node work"}'

    gateway = Gateway()
    manager = ExecutionManager(flags=FeatureFlags(dag=True, planner=True))

    result = await manager.execute(
        user_query="Fix server.py and add tests, then verify the behavior.",
        gateway=gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )

    assert gateway.calls
    assert any(call["role"] == "generation" for call in gateway.calls)
    assert gateway.calls[-1]["role"] == "judge"
    assert result["winning_answer"] == "Verified semantic result"
    assert result["results"]["final"]["final_response"] == "Verified semantic result"
    assert all(
        not str(value).startswith(f"{node_id}:")
        for node_id, node_result in result["results"].items()
        for value in node_result["produced_outputs"].values()
    )


@pytest.mark.asyncio
async def test_execution_manager_releases_dag_resources(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    class Resources:
        def __init__(self) -> None:
            self.acquired = 0
            self.released = 0

        def scheduler_concurrency_limit(self, graph):
            return 1

        def recompute_plan(self, graph, prediction=None):
            return "ok"

        def snapshot(self):
            return type("State", (), {
                "concurrency_active": 0,
                "rate_limit_remaining": 10,
                "cpu_parallel_ceiling": 1,
                "connection_pool_size": 1,
            })()

        async def acquire(self, node):
            from orchestrator.resource_manager import Reservation

            self.acquired += 1
            return Reservation(node.task_id, "local", "local/sim", 1)

        async def release(self, reservation):
            self.released += 1

    resources = Resources()
    manager = ExecutionManager(
        flags=FeatureFlags(dag=True, planner=True),
        resource_manager=resources,
    )

    result = await manager.execute(
        user_query="Fix server.py and add tests, then verify the behavior.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )

    assert resources.acquired > 0
    assert resources.released == resources.acquired
    assert result["budget_snapshot"].used_tokens > 0


@pytest.mark.asyncio
async def test_execution_manager_rejects_node_over_token_budget(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    manager = ExecutionManager(
        flags=FeatureFlags(dag=True, planner=True),
        runtime_contract=RuntimeContract(max_tokens=10),
    )

    with pytest.raises(RuntimeError, match="Scheduler node"):
        await manager.execute(
            user_query="Fix server.py and add tests, then verify the behavior.",
            gateway=stub_gateway,
            strategy=stub_strategy,
            pool=stub_pool,
        )


@pytest.mark.asyncio
async def test_execution_manager_prediction_mode_emits_budget_and_prediction_telemetry(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    manager = ExecutionManager(
        flags=FeatureFlags(dag=True, planner=True, prediction=True),
        runtime_contract=RuntimeContract(max_tokens=20_000),
    )
    history = [
        {"role": "user", "content": "Please inspect the module and verify edge cases."},
        {"role": "assistant", "content": "I will inspect the module and summarize the edge cases."},
    ]

    result = await manager.execute(
        user_query="Research the bug, decompose the work, and verify the outcome.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
        history=history,
    )

    assert result["budget"].total_tokens == 15_000
    assert result["budget_snapshot"].pressure in {"normal", "tight", "critical", "exhausted"}
    assert result["prediction"] is not None
    assert result["prediction_telemetry"] is not None
    assert "prediction.tokens.actual" in result["prediction_telemetry"]


@pytest.mark.asyncio
async def test_execution_manager_context_mode_attaches_per_node_context_window(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    manager = ExecutionManager(
        flags=FeatureFlags(dag=True, planner=True, context=True),
    )
    history = [
        {"role": "system", "content": "Preserve safety constraints."},
        {"role": "developer", "content": "Respect existing repository conventions."},
        {"role": "user", "content": "Please research the issue carefully."},
        {"role": "assistant", "content": "I will compare evidence and summarize it clearly."},
    ]

    result = await manager.execute(
        user_query="Research the failure and compare the evidence, then summarize the outcome.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
        history=history,
    )

    plan_window = result["results"]["plan"]["context_window"]
    assert plan_window.input_contract is not None
    assert plan_window.input_contract.required_fields == ["request", "task_profile"]
    assert plan_window.incoming_outputs["request"].startswith("Research the failure")
    assert any(message["content"] == "Preserve safety constraints." for message in plan_window.messages)
    assert any(message["content"] == "Respect existing repository conventions." for message in plan_window.messages)  # noqa: E501


@pytest.mark.asyncio
async def test_execution_manager_skills_mode_returns_skill_plan(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    manager = ExecutionManager(
        flags=FeatureFlags(dag=True, planner=True, skills=True),
    )

    result = await manager.execute(
        user_query="Research the failure, compare the evidence, and summarize the outcome.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )

    assert result["skill_plan"] is not None
    assert "final" in result["skill_plan"]
    final_skills = result["skill_plan"]["final"].skills
    assert "researcher" in final_skills
    assert "academic" in final_skills


@pytest.mark.asyncio
async def test_execution_manager_exposes_early_exit_and_meta_reasoner_audit(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    manager = ExecutionManager(flags=FeatureFlags(dag=True, planner=True))

    result = await manager.execute(
        user_query="What time does the release window open?",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )

    assert result["early_exit_decision"] is not None
    assert result["early_exit_decision"].can_exit_early is True
    assert isinstance(result["mutation_audit_trail"], list)


@pytest.mark.asyncio
async def test_execution_manager_returns_structured_clarification_for_ambiguous_prompt(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    manager = ExecutionManager(flags=FeatureFlags(dag=True, planner=True))

    result = await manager.execute(
        user_query="Fix this.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )

    assert result["status"] == "needs_clarification"
    assert result["clarification_request"] is not None
    assert result["clarification_request"].status == "needs_clarification"
    assert result["uncertainty_decision"].outcome == "ask_user_clarification"


@pytest.mark.asyncio
async def test_execution_manager_firewall_qualifies_unsupported_final_claim(
    stub_strategy, stub_pool
) -> None:
    class _ClaimGateway:
        async def execute_with_fallback(self, **kwargs):
            return '{"answer":"The API timeout is 90 seconds."}'

    manager = ExecutionManager(
        flags=FeatureFlags(dag=True, planner=True),
        execution_planner=_UnsupportedClaimPlanner(),
    )

    result = await manager.execute(
        user_query="What timeout should we report?",
        gateway=_ClaimGateway(),
        strategy=stub_strategy,
        pool=stub_pool,
        history=[{"role": "system", "content": "The API timeout is 30 seconds."}],
    )

    assert result["status"] == "success"
    assert "Qualifier:" in result["final_output"].final_answer
    assert result["firewall_result"]["removed_or_qualified_count"] >= 1
    assert result["firewall_result"]["unsupported_claims"]


@pytest.mark.asyncio
async def test_execution_manager_rag_off_emits_disabled_telemetry(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    manager = ExecutionManager(flags=FeatureFlags(dag=True, planner=True, rag=False))

    result = await manager.execute(
        user_query="Research the failure and compare the evidence.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )

    assert result["status"] == "success"
    assert result["rag_telemetry"]["status"] == "disabled"
    assert result["rag_telemetry"]["selected_total"] == 0
    for node_result in result["results"].values():
        assert node_result["retrieval_result"] is None


@pytest.mark.asyncio
async def test_execution_manager_rag_on_runs_research_retrieval(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    from orchestrator.retrieval import (
        RetrievalProvider,
        RetrievalRequest,
        SourceCandidate,
    )

    class _ResearchProvider(RetrievalProvider):
        async def retrieve(self, request: RetrievalRequest):  # type: ignore[override]
            return [
                SourceCandidate(
                    url="https://docs.example.test/handbook",
                    title="Calienne Handbook",
                    excerpt="Smart RAG ranks sources by relevance, credibility, freshness, and consensus.",
                    credibility_score=0.9,
                    freshness_score=0.7,
                    relevance_score=0.95,
                    consensus_score=0.8,
                )
            ]

    service = _build_rag_service(_ResearchProvider())
    manager = ExecutionManager(
        flags=FeatureFlags(dag=True, planner=True, rag=True, context=True),
        retrieval_service=service,
    )

    result = await manager.execute(
        user_query="Research the failure, compare the evidence, and summarize the outcome.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )

    assert result["status"] == "success"
    rag_telemetry = result["rag_telemetry"]
    assert rag_telemetry["status"] == "ok"
    assert rag_telemetry["selected_total"] >= 1
    assert rag_telemetry["evidence_bump_total"] == rag_telemetry["selected_total"]
    assert rag_telemetry["nodes_attempted"] >= 1
    final_window = result["results"]["final"]["context_window"]
    assert final_window.retrieval_result is not None
    assert final_window.retrieval_result.selected_count >= 1
    snippet = final_window.retrieved_snippets[0]
    assert snippet.metadata["final_score"] > 0.0


def _build_rag_service(provider):
    from orchestrator.retrieval import (
        DEFAULT_RANKING_WEIGHTS,
        ROUTE_GATING,
        RetrievalService,
    )

    return RetrievalService(
        provider=provider,
        weights=dict(DEFAULT_RANKING_WEIGHTS),
        route_gating=dict(ROUTE_GATING),
    )


@pytest.mark.asyncio
async def test_execution_manager_rag_provider_failure_degrades_silently(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    from orchestrator.retrieval import (
        DEFAULT_RANKING_WEIGHTS,
        ROUTE_GATING,
        RetrievalProvider,
        RetrievalRequest,
        RetrievalService,
    )

    class _Boom(RetrievalProvider):
        async def retrieve(self, request: RetrievalRequest):  # type: ignore[override]
            raise RuntimeError("provider offline")

    service = RetrievalService(
        provider=_Boom(),
        weights=dict(DEFAULT_RANKING_WEIGHTS),
        route_gating=dict(ROUTE_GATING),
    )
    manager = ExecutionManager(
        flags=FeatureFlags(dag=True, planner=True, rag=True, context=True),
        retrieval_service=service,
    )

    result = await manager.execute(
        user_query="Research the failure, compare the evidence, and summarize the outcome.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )

    assert result["status"] == "success"
    assert result["rag_telemetry"]["status"] == "ok"
    for node_result in result["results"].values():
        retrieval_result = node_result["retrieval_result"]
        if retrieval_result is not None and retrieval_result.retrieval_attempted:
            assert retrieval_result.sources == []


def _dashboard_template_keys() -> set[str]:
    from orchestrator.execution_manager import _DASHBOARD_METRIC_TEMPLATE

    return set(_DASHBOARD_METRIC_TEMPLATE)


@pytest.mark.asyncio
async def test_execution_manager_success_emits_all_namespaced_dashboard_metrics(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    manager = ExecutionManager(flags=FeatureFlags(dag=True, planner=True))

    result = await manager.execute(
        user_query="Fix server.py and add tests, then verify the behavior.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )

    metrics = result["dashboard_metrics"]
    # Every RFC-005 §4.1 example key is present, never silently omitted.
    assert set(metrics) == _dashboard_template_keys()
    # All nine namespaces are represented.
    namespaces = {key.split(".", 1)[0] for key in metrics}
    assert namespaces == {
        "execution",
        "quality",
        "resources",
        "prediction",
        "learning",
        "environment",
        "manifest",
        "scheduler",
        "planner",
    }
    # Live-sourced fields carry real values, not the None template default.
    assert metrics["execution.node.completed"] is not None
    assert metrics["scheduler.node.queued"] == metrics["scheduler.node.released"]
    assert metrics["quality.confidence"] is not None
    assert metrics["manifest.architecture_version"] is not None
    assert metrics["environment.python_version"] is not None


@pytest.mark.asyncio
async def test_execution_manager_clarification_emits_partial_dashboard_metrics(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    manager = ExecutionManager(flags=FeatureFlags(dag=True, planner=True))

    result = await manager.execute(
        user_query="Fix this.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )

    assert result["status"] == "needs_clarification"
    metrics = result["dashboard_metrics"]
    assert set(metrics) == _dashboard_template_keys()
    # Scheduler never ran on the clarification branch, so execution.* stays None...
    assert metrics["execution.node.started"] is None
    assert metrics["scheduler.node.queued"] is None
    # ...but the pre-scheduling quality snapshot is already populated.
    assert metrics["quality.confidence"] is not None
    assert metrics["manifest.architecture_version"] is not None
    assert metrics["manifest.graph_version"] == result["graph"].graph_version
    assert metrics["manifest.graph_fingerprint"] == result["graph"].graph_fingerprint


@pytest.mark.asyncio
async def test_execution_manager_attaches_manifest_to_passport(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    passport = ExecutionPassport()
    manager = ExecutionManager(flags=FeatureFlags(dag=True, planner=True))

    result = await manager.execute(
        user_query="Fix server.py and add tests, then verify the behavior.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
        passport=passport,
    )

    assert passport.execution_manifest is result["execution_manifest"]
    assert result["passport"]["execution_manifest"] == result[
        "execution_manifest"
    ].model_dump(mode="json")


@pytest.mark.asyncio
async def test_execution_manager_prediction_dashboard_metrics_match_prediction_telemetry(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    manager = ExecutionManager(
        flags=FeatureFlags(dag=True, planner=True, prediction=True),
        runtime_contract=RuntimeContract(max_tokens=20_000),
    )

    result = await manager.execute(
        user_query="Research the bug, decompose the work, and verify the outcome.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )

    metrics = result["dashboard_metrics"]
    telemetry = result["prediction_telemetry"]
    assert telemetry is not None
    assert metrics["prediction.tokens.actual"] == telemetry["prediction.tokens.actual"]


# ── Honest contract-field population (research Tier 0.2, fixed 2026-08-22) ─


class TestPopulateContractFields:
    """Every declared field used to receive the same response string — a
    contract layer certifying fabricated content. Now only fields the model
    actually produced are populated."""

    def test_single_field_contract_gets_normalized_text(self) -> None:
        from orchestrator.execution_manager import populate_contract_fields

        out = populate_contract_fields('{"answer": "hi"}', "hi", ["answer"])
        assert out == {"answer": "hi"}

    def test_multi_field_structured_response_populates_real_fields(self) -> None:
        from orchestrator.execution_manager import populate_contract_fields

        raw = '{"answer": "ship it", "reasoning": "tests pass"}'
        out = populate_contract_fields(raw, "ship it", ["answer", "reasoning"])
        assert out == {"answer": "ship it", "reasoning": "tests pass"}

    def test_multi_field_partial_response_leaves_missing_fields_out(self) -> None:
        from orchestrator.execution_manager import populate_contract_fields

        raw = '{"answer": "ship it"}'
        out = populate_contract_fields(raw, "ship it", ["answer", "reasoning"])
        assert out == {"answer": "ship it"}  # "reasoning" NOT fabricated

    def test_unstructured_multi_field_emits_one_field_only(self) -> None:
        from orchestrator.execution_manager import populate_contract_fields

        out = populate_contract_fields("plain text answer", "plain text answer", ["a", "b", "c"])
        assert out == {"a": "plain text answer"}  # b, c left for violations

    @pytest.mark.asyncio
    async def test_dag_multi_field_violation_is_raised_not_certified(
        stub_strategy, stub_pool
    ) -> None:
        """A node declaring fields the model did not produce must fail its
        contract, not pass with fabricated copies (validate_outputs sees the
        missing fields and the node raises)."""
        from orchestrator.contracts import OutputContract
        from orchestrator.execution_manager import populate_contract_fields

        contract = OutputContract(
            produced_fields=["answer", "reasoning"], types={"answer": "string", "reasoning": "string"}
        )

        class _Node:
            task_id = "n1"
            output_contract = contract

        from orchestrator.contracts import validate_outputs

        produced = populate_contract_fields('{"answer": "x"}', "x", contract.produced_fields)
        violations = validate_outputs(_Node(), produced)
        assert [v.kind for v in violations] == ["missing_output"]
        assert violations[0].field == "reasoning"
