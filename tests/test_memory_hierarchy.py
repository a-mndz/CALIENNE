from __future__ import annotations

import asyncio

import pytest

from core.schemas import TaskNode, TaskProfile
from orchestrator.context_manager import ContextManager
from orchestrator.execution_manager import ExecutionManager
from orchestrator.feature_flags import FeatureFlags
from orchestrator.memory_hierarchy import (
    LAYER_NAMES,
    AgentMemory,
    LongTermMemory,
    MemoryEntry,
    MemoryHierarchy,
    MemoryHierarchyConfig,
    MemoryQuery,
    SharedCache,
    ShortTermMemory,
    UserMemory,
    VectorMemory,
)

# ── Layer unit tests ────────────────────────────────────────────────────


def test_layer_names_match_rfc_004() -> None:
    """RFC-004 §2 mandates the six named layers in this exact order."""

    assert LAYER_NAMES == (
        "short_term",
        "long_term",
        "user_memory",
        "agent_memory",
        "shared_cache",
        "vector_memory",
    )


def test_short_term_memory_evicts_oldest_when_full() -> None:
    layer = ShortTermMemory(max_entries=2)
    asyncio.run(
        layer.write(MemoryEntry(key="a", content="alpha", layer="short_term"))
    )
    asyncio.run(
        layer.write(MemoryEntry(key="b", content="bravo", layer="short_term"))
    )
    asyncio.run(
        layer.write(MemoryEntry(key="c", content="charlie", layer="short_term"))
    )

    snapshot = layer.snapshot()
    assert snapshot["entries"] == 2
    assert "a" not in [key for key, _ in layer._entries.items()]  # type: ignore[attr-defined]


def test_long_term_memory_overwrites_by_key() -> None:
    layer = LongTermMemory(max_entries=10)
    asyncio.run(
        layer.write(
            MemoryEntry(key="topic-1", content="old summary", layer="long_term")
        )
    )
    asyncio.run(
        layer.write(
            MemoryEntry(
                key="topic-1",
                content="new summary",
                layer="long_term",
                tags=["research"],
            )
        )
    )

    snapshot = layer.snapshot()
    assert snapshot["entries"] == 1
    results = asyncio.run(
        layer.read(MemoryQuery(query="summary", top_k=5))
    )
    assert results[0].content == "new summary"
    assert "research" in results[0].tags


def test_user_memory_segments_by_user_id() -> None:
    layer = UserMemory(max_entries=10)
    asyncio.run(
        layer.write(
            MemoryEntry(
                key="pref-1",
                content="I prefer terse answers.",
                layer="user_memory",
                metadata={"user_id": "alice"},
            )
        )
    )
    asyncio.run(
        layer.write(
            MemoryEntry(
                key="pref-2",
                content="I enjoy long-form essays.",
                layer="user_memory",
                metadata={"user_id": "bob"},
            )
        )
    )

    alice_results = asyncio.run(
        layer.read(
            MemoryQuery(
                query="terse",
                top_k=5,
                metadata={"user_id": "alice"},
            )
        )
    )
    bob_results = asyncio.run(
        layer.read(
            MemoryQuery(
                query="terse",
                top_k=5,
                metadata={"user_id": "bob"},
            )
        )
    )

    assert len(alice_results) == 1
    assert "terse" in alice_results[0].content
    assert bob_results == []


def test_agent_memory_segments_by_agent() -> None:
    layer = AgentMemory(max_entries=10)
    asyncio.run(
        layer.write(
            MemoryEntry(
                key="breaker-fail-1",
                content="router breaker hit timeout",
                layer="agent_memory",
                metadata={"agent": "breaker"},
                tags=["failure"],
            )
        )
    )
    asyncio.run(
        layer.write(
            MemoryEntry(
                key="judge-fail-1",
                content="judge rejected missing evidence",
                layer="agent_memory",
                metadata={"agent": "judge"},
                tags=["failure"],
            )
        )
    )

    breaker = asyncio.run(
        layer.read(
            MemoryQuery(
                query="timeout",
                top_k=5,
                metadata={"agent": "breaker"},
            )
        )
    )
    assert breaker and breaker[0].metadata.get("agent") == "breaker"


def test_shared_cache_tracks_hits_and_misses() -> None:
    layer = SharedCache(max_entries=10)
    asyncio.run(
        layer.write(
            MemoryEntry(
                key="src-1",
                content="Calienne documentation page",
                layer="shared_cache",
            )
        )
    )

    hit = asyncio.run(
        layer.read(MemoryQuery(query="documentation", top_k=5))
    )
    miss = asyncio.run(
        layer.read(MemoryQuery(query="quantum-thermodynamics", top_k=5))
    )

    assert hit and hit[0].content.startswith("Calienne")
    assert miss == []
    snapshot = layer.snapshot()
    assert snapshot["hits"] == 1
    assert snapshot["misses"] == 1


def test_vector_memory_finds_semantic_match_via_cosine() -> None:
    layer = VectorMemory(max_entries=10)
    asyncio.run(
        layer.write(
            MemoryEntry(
                key="v1",
                content="machine learning models generalize from data",
                layer="vector_memory",
            )
        )
    )
    asyncio.run(
        layer.write(
            MemoryEntry(
                key="v2",
                content="chocolate cake recipe with butter and sugar",
                layer="vector_memory",
            )
        )
    )

    results = asyncio.run(
        layer.read(MemoryQuery(query="data generalization models", top_k=3))
    )
    assert results and results[0].key == "v1"
    assert all(result.score > 0.0 for result in results)


# ── Hierarchy facade tests ──────────────────────────────────────────────


def test_hierarchy_gathers_across_layers_and_merges_by_score() -> None:
    config = MemoryHierarchyConfig(
        short_term_max=8,
        long_term_max=8,
        user_max=8,
        agent_max=8,
        shared_cache_max=8,
        vector_max=8,
        per_layer_top_k=2,
        gather_top_k=6,
    )
    hierarchy = MemoryHierarchy(config=config)

    async def populate() -> None:
        await hierarchy.write(
            MemoryEntry(
                key="st:user",
                content="What is the API timeout?",
                layer="short_term",
                tags=["user"],
            )
        )
        await hierarchy.write(
            MemoryEntry(
                key="lt:timeout",
                content="The API timeout is 30 seconds.",
                layer="long_term",
                tags=["timeout", "research"],
            )
        )
        await hierarchy.write(
            MemoryEntry(
                key="um:style",
                content="Prefer concise answers about timeout defaults.",
                layer="user_memory",
                metadata={"user_id": "u1"},
                tags=["preference"],
            )
        )
        await hierarchy.write(
            MemoryEntry(
                key="am:breaker",
                content="Breaker hit API timeout last time.",
                layer="agent_memory",
                metadata={"agent": "breaker"},
                tags=["failure"],
            )
        )
        await hierarchy.write(
            MemoryEntry(
                key="sc:docs",
                content="API timeout configuration documentation reference.",
                layer="shared_cache",
            )
        )
        await hierarchy.write(
            MemoryEntry(
                key="vm:models",
                content="default API timeout values for inference models",
                layer="vector_memory",
            )
        )

    asyncio.run(populate())

    entries = asyncio.run(
        hierarchy.gather(
            query="What is the API timeout?",
            user_id="u1",
            agent="breaker",
        )
    )
    layers_seen = {entry.layer for entry in entries}
    assert layers_seen == {
        "short_term",
        "long_term",
        "user_memory",
        "agent_memory",
        "shared_cache",
        "vector_memory",
    }
    # Merged output is score-sorted
    scores = [entry.score for entry in entries]
    assert scores == sorted(scores, reverse=True)
    assert len(entries) <= config.gather_top_k


def test_hierarchy_swallows_layer_failures() -> None:
    hierarchy = MemoryHierarchy()

    class _Boom:
        name = "long_term"

        async def read(self, query):
            raise RuntimeError("kaboom")

        async def write(self, entry):
            return None

        async def evict(self, *, max_age_seconds=None):
            return 0

        def snapshot(self):
            return {"layer": "long_term", "entries": 0}

    hierarchy._layers["long_term"] = _Boom()  # type: ignore[assignment]

    entries = asyncio.run(
        hierarchy.gather(
            query="anything",
            layers=["short_term", "long_term", "vector_memory"],
        )
    )
    # Long-term raised, but the surviving layers should still return (possibly empty)
    assert isinstance(entries, list)


def test_hierarchy_evict_all_zeroes_layers() -> None:
    hierarchy = MemoryHierarchy(
        config=MemoryHierarchyConfig(short_term_max=4, long_term_max=4)
    )

    async def populate() -> None:
        await hierarchy.write(
            MemoryEntry(key="x", content="x", layer="short_term")
        )
        await hierarchy.write(
            MemoryEntry(key="y", content="y", layer="long_term")
        )

    asyncio.run(populate())
    counts = asyncio.run(hierarchy.evict_all())
    assert counts["short_term"] >= 1
    assert counts["long_term"] >= 1
    snapshot = hierarchy.snapshot()
    assert snapshot["short_term"]["entries"] == 0
    assert snapshot["long_term"]["entries"] == 0


# ── ContextManager integration ──────────────────────────────────────────


def _node() -> TaskNode:
    return TaskNode(
        task_id="plan",
        objective="Plan the research response around the key findings",
    )


def test_context_manager_attaches_memory_hits_when_hierarchy_wired() -> None:
    hierarchy = MemoryHierarchy(
        config=MemoryHierarchyConfig(gather_top_k=3, per_layer_top_k=2)
    )
    asyncio.run(
        hierarchy.write(
            MemoryEntry(
                key="lt:timeout",
                content="The API timeout is 30 seconds.",
                layer="long_term",
                tags=["research"],
            )
        )
    )

    manager = ContextManager(memory_hierarchy=hierarchy)
    profile = TaskProfile(task_type="research", complexity="medium", requires_rag=True)

    window = asyncio.run(
        manager.assemble_window(
            _node(),
            user_query="What is the API timeout?",
            task_profile=profile,
        )
    )

    assert any(
        snippet.source.startswith("memory:") for snippet in window.retrieved_snippets
    )
    assert any(
        hit["metadata"]["layer"] == "long_term"
        for hit in window.metadata["memory_hits"]
    )


def test_context_manager_without_hierarchy_emits_no_memory_hits() -> None:
    manager = ContextManager()
    profile = TaskProfile(task_type="research", complexity="medium", requires_rag=True)

    window = asyncio.run(
        manager.assemble_window(
            _node(),
            user_query="Research the issue.",
            task_profile=profile,
        )
    )

    assert window.metadata["memory_hits"] == []


# ── ExecutionManager integration ────────────────────────────────────────


@pytest.mark.asyncio
async def test_execution_manager_context_mode_exposes_memory_telemetry(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    hierarchy = MemoryHierarchy()
    manager = ExecutionManager(
        flags=FeatureFlags(dag=True, planner=True, context=True),
        memory_hierarchy=hierarchy,
    )

    result = await manager.execute(
        user_query="Research the failure and compare the evidence.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )

    assert result["status"] == "success"
    telemetry = result["memory_telemetry"]
    assert telemetry["status"] != "disabled"
    assert "short_term" in telemetry
    assert telemetry["short_term"]["entries"] >= 1


@pytest.mark.asyncio
async def test_execution_manager_context_off_disables_memory_telemetry(
    stub_gateway, stub_strategy, stub_pool
) -> None:
    hierarchy = MemoryHierarchy()
    manager = ExecutionManager(
        flags=FeatureFlags(dag=True, planner=True, context=False),
        memory_hierarchy=hierarchy,
    )

    result = await manager.execute(
        user_query="Research the failure and compare the evidence.",
        gateway=stub_gateway,
        strategy=stub_strategy,
        pool=stub_pool,
    )

    assert result["status"] == "success"
    assert result["memory_telemetry"] == {"status": "disabled"}
    assert hierarchy.snapshot()["short_term"]["entries"] == 0


# ── Determinism + guard rails ──────────────────────────────────────────


def test_hierarchy_built_keys_are_stable() -> None:
    a = MemoryHierarchy.build_key("alpha", "beta")
    b = MemoryHierarchy.build_key("ALPHA", "beta")
    c = MemoryHierarchy.build_key("beta", "alpha")
    assert a == b  # case-insensitive
    assert a != c  # order-sensitive
    assert len(a) == 40  # sha1 hex
