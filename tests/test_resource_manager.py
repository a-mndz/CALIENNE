"""Exit-gate tests for the ResourceManager (Step 18, RFC-002 §4/§6, ADR-004).

Focus: the ``effective_parallel`` min() honors BOTH provider and model limits,
the reservation lifecycle is safe, and ``recompute_plan`` /
``scheduler_concurrency_limit`` stay deterministic.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from api_gateway.capabilities import CapabilityRegistry
from orchestrator.resource_manager import ResourceManager, ResourceState

# ── Test doubles ─────────────────────────────────────────────────────────


@dataclass
class _Node:
    task_id: str = "n1"
    model: str | None = None
    model_tier: str = "default"


@dataclass
class _Graph:
    nodes: list[Any] = field(default_factory=list)


def _scratch_dir() -> Path:
    # Windows async-fixture glitch makes pytest's tmp_path flaky here; use a
    # stable scratch root instead (matches tests/test_retrieval.py).
    root = Path("C:/Users/amand/AppData/Local/Temp/opencode") / f"caps-{uuid.uuid4()}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _rm(**kw: Any) -> ResourceManager:
    # Wide CPU/memory/budget ceilings so provider+model limits are what bind.
    kw.setdefault("cpu_parallel_ceiling", 999)
    kw.setdefault("memory_parallel_ceiling", 999)
    kw.setdefault("default_budget_parallel", 999)
    return ResourceManager(**kw)


# ── effective_parallel honors provider AND model (RFC-002 §6) ─────────────


def test_effective_parallel_bound_by_model_limit() -> None:
    rm = _rm()
    # google provider_limit=8, gemini-pro-latest max_concurrency=4 → model wins.
    assert rm.effective_parallel(provider="google", model="google/gemini-pro-latest") == 4


def test_effective_parallel_bound_by_provider_limit() -> None:
    rm = _rm()
    # groq provider_limit=6, gpt-oss-20b max_concurrency=10 → provider wins.
    assert rm.effective_parallel(provider="groq", model="groq/openai/gpt-oss-20b") == 6


def test_effective_parallel_bound_by_budget() -> None:
    rm = _rm()
    assert (
        rm.effective_parallel(
            provider="google", model="google/gemini-3.5-flash-lite", budget_parallel=2
        )
        == 2
    )


def test_effective_parallel_bound_by_rate_limit() -> None:
    rm = _rm()
    # rate_limit.remaining is the sixth min() term; a small positive binds it.
    assert (
        rm.effective_parallel(
            provider="google", model="google/gemini-3.5-flash-lite", rate_limit_remaining=1
        )
        == 1
    )


def test_effective_parallel_rejects_zero_rate_limit() -> None:
    rm = _rm()
    got = rm.effective_parallel(
        provider="google", model="google/gemini-3.5-flash-lite", rate_limit_remaining=0
    )
    assert got == 0


# ── reservation lifecycle ────────────────────────────────────────────────


def test_acquire_release_roundtrip() -> None:
    async def run() -> None:
        rm = _rm()
        node = _Node(model="google/gemini-3.5-flash-lite")
        res = await rm.acquire(node)
        assert res.granted is True
        # provider is extract_provider_key(model) — first two path segments.
        assert res.provider == "google/gemini-3.5-flash-lite"
        assert res.model == "google/gemini-3.5-flash-lite"
        assert rm.snapshot().concurrency_active == 1
        await rm.release(res)
        assert rm.snapshot().concurrency_active == 0

    asyncio.run(run())


def test_acquire_rejects_when_ceiling_reached() -> None:
    async def run() -> None:
        # Force effective_parallel down to 1 via a tight budget.
        rm = ResourceManager(
            cpu_parallel_ceiling=1, memory_parallel_ceiling=1, default_budget_parallel=1
        )
        node = _Node(model="google/gemini-3.5-flash-lite")
        first = await rm.acquire(node)
        assert first.granted is True
        second = await rm.acquire(node)
        assert second.granted is False
        assert "effective_parallel" in second.reason

    asyncio.run(run())


def test_release_is_idempotent_and_safe() -> None:
    async def run() -> None:
        rm = _rm()
        await rm.release(None)  # no-op
        assert rm.snapshot().concurrency_active == 0

    asyncio.run(run())


# ── snapshot shape ───────────────────────────────────────────────────────


def test_snapshot_is_resource_state_with_dict() -> None:
    rm = _rm()
    snap = rm.snapshot()
    assert isinstance(snap, ResourceState)
    d = snap.as_dict()
    for key in (
        "concurrency_active",
        "connection_pool_size",
        "cpu_parallel_ceiling",
        "capability_load_failed",
    ):
        assert key in d


# ── recompute_plan / scheduler_concurrency_limit ─────────────────────────


def test_recompute_plan_rejects_empty_graph() -> None:
    assert _rm().recompute_plan(_Graph(nodes=[])) == "reject"


def test_recompute_plan_ok_for_runnable_graph() -> None:
    g = _Graph(nodes=[_Node(model="google/gemini-3.5-flash-lite")])
    assert _rm().recompute_plan(g) == "ok"


def test_scheduler_limit_capped_by_node_count() -> None:
    rm = _rm()
    g = _Graph(nodes=[_Node(task_id="a"), _Node(task_id="b")])
    # cpu ceiling is wide (999) but only 2 nodes → capped at 2.
    assert rm.scheduler_concurrency_limit(g) == 2


def test_scheduler_limit_floor_is_one() -> None:
    rm = _rm()
    assert rm.scheduler_concurrency_limit(_Graph(nodes=[])) == 1


# ── capability-load failure degrades, never raises (ADR-007) ─────────────


def test_uses_defaults_when_capabilities_failed() -> None:
    caps = CapabilityRegistry(capabilities_dir=_scratch_dir())  # empty dir → all failed
    assert caps.capability_load_failed is True
    rm = _rm(capabilities=caps)
    # DEFAULT provider limit (5) and DEFAULT model concurrency (5) → 5.
    assert rm.effective_parallel(provider="ghost", model="ghost/model") == 5
    assert rm.snapshot().capability_load_failed is True
