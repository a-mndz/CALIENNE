"""Memory v1 tests — tenancy, SQL shape, hydration merge, freshness decay.

Postgres-specific SQL is asserted structurally (the statements carry the
join + tenancy predicate + safe tsquery); row handling is tested against a
fake async session. The slow testcontainers job exercises the real thing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from orchestrator.memory_search import (
    PostgresTurnSearchProvider,
    _freshness,
    hydrate_history,
    recent_turns,
    search_relevant_turns,
)
from orchestrator.retrieval import RetrievalRequest


class _FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def fetchall(self) -> list:
        return self._rows


class _FakeDB:
    def __init__(self, rows: list | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[object, dict | None]] = []

    async def execute(self, stmt, params=None) -> _FakeResult:
        self.calls.append((stmt, params))
        return _FakeResult(self.rows)


class _Factory:
    def __init__(self, db: _FakeDB) -> None:
        self._db = db

    def __call__(self) -> "_Factory":
        return self

    async def __aenter__(self) -> _FakeDB:
        return self._db

    async def __aexit__(self, *args: object) -> bool:
        return False


def _turn(content: str, role: str = "user", minutes_ago: float = 0, session: str = "s1"):
    return SimpleNamespace(
        content=content,
        role=role,
        ts=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        session_id=session,
        rank=0.5,
    )


# ── Tenancy is fail-closed ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_provider_without_owner_returns_nothing() -> None:
    provider = PostgresTurnSearchProvider(_Factory(_FakeDB([_turn("leak")])) )
    result = await provider.retrieve(RetrievalRequest(query="anything"))
    assert result == []


@pytest.mark.asyncio
async def test_provider_with_metadata_owner_queries_scoped() -> None:
    db = _FakeDB([_turn("matched turn")])
    provider = PostgresTurnSearchProvider(_Factory(db))
    result = await provider.retrieve(
        RetrievalRequest(query="needle", metadata={"owner_email": "a@x"})
    )
    assert len(result) == 1
    assert result[0].excerpt == "matched turn"
    sql = str(db.calls[0][0])
    assert "conversation_sessions" in sql and "owner_email" in sql


@pytest.mark.asyncio
async def test_provider_scores_are_clamped_to_unit_range() -> None:
    row = _turn("big rank")
    row.rank = 42.0  # impossible, but the clamp must hold anyway
    provider = PostgresTurnSearchProvider(_Factory(_FakeDB([row])), owner_email="a@x")
    result = await provider.retrieve(RetrievalRequest(query="q"))
    assert all(0.0 <= c.relevance_score <= 1.0 for c in result)


@pytest.mark.asyncio
async def test_provider_empty_query_short_circuits() -> None:
    db = _FakeDB([_turn("x")])
    provider = PostgresTurnSearchProvider(_Factory(db), owner_email="a@x")
    assert await provider.retrieve(RetrievalRequest(query="   ")) == []
    assert db.calls == []


# ── SQL shape — the load-bearing verified details ───────────────────────


@pytest.mark.asyncio
async def test_search_sql_uses_safe_tsquery_and_bounded_rank() -> None:
    db = _FakeDB([])
    await search_relevant_turns(db, owner_email="a@x", query="cards & fees!")
    sql = str(db.calls[0][0])
    assert "websearch_to_tsquery" in sql        # never raises on raw input
    assert "ts_rank_cd" in sql and ", 32)" in sql  # rank bounded into [0,1)
    assert "JOIN conversation_sessions" in sql  # tenancy lives on the parent
    assert "s.owner_email = :owner_email" in sql


# ── Hydration merge ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hydrate_merges_dedupes_and_orders_chronologically() -> None:
    old = _turn("old turn", minutes_ago=60, session="s1")
    new = _turn("recent turn", minutes_ago=1, session="s2")
    relevant_dup = _turn("recent turn", minutes_ago=1, session="s2")  # same turn via both paths
    relevant_only = _turn("topical turn", minutes_ago=30, session="s3")

    db = _FakeDB([])

    async def fake_recent(db, **_kwargs):
        return [
            {"role": "user", "content": new.content, "session_id": "s2",
             "timestamp": new.ts.isoformat()},
            {"role": "user", "content": old.content, "session_id": "s1",
             "timestamp": old.ts.isoformat()},
        ]

    async def fake_search(db, **_kwargs):
        return [
            {"role": "user", "content": relevant_dup.content, "session_id": "s2",
             "timestamp": new.ts.isoformat()},
            {"role": "user", "content": relevant_only.content, "session_id": "s3",
             "timestamp": relevant_only.ts.isoformat()},
        ]

    import orchestrator.memory_search as ms

    orig_recent, orig_search = ms.recent_turns, ms.search_relevant_turns
    ms.recent_turns, ms.search_relevant_turns = fake_recent, fake_search
    try:
        merged = await hydrate_history(db, owner_email="a@x", query="topic")
    finally:
        ms.recent_turns, ms.search_relevant_turns = orig_recent, orig_search

    contents = [turn["content"] for turn in merged]
    # chronological: old (60m ago) < topical (30m ago) < recent (1m ago)
    assert contents == ["old turn", "topical turn", "recent turn"]
    assert all(set(turn) == {"role", "content"} for turn in merged)


@pytest.mark.asyncio
async def test_recent_turns_normalises_roles() -> None:
    db = _FakeDB([_turn("x", role="system")])
    turns = await recent_turns(db, owner_email="a@x")
    assert turns[0]["role"] == "user"  # unknown roles never leak as fake assistants


# ── Freshness decay ──────────────────────────────────────────────────────


def test_freshness_is_one_now() -> None:
    now = datetime.now(timezone.utc)
    assert _freshness(now, now) == pytest.approx(1.0)


def test_freshness_halves_weekly() -> None:
    now = datetime.now(timezone.utc)
    week_old = now - timedelta(days=7)
    assert _freshness(week_old, now) == pytest.approx(0.5)


def test_freshness_never_negative() -> None:
    now = datetime.now(timezone.utc)
    assert _freshness(now + timedelta(days=365), now) == 1.0  # future timestamps clamp
    assert _freshness(now - timedelta(days=3650), now) == pytest.approx(0.0, abs=1e-3)
