"""Tests for the Step 20b Experience DB repository (RFC-004 §7, ADR-008).

Two layers, per the chosen strategy:

* **Default suite** — an in-memory fake ``AsyncSession`` that introspects the
  real SQLAlchemy ``select``/``delete`` statements the repository builds, so
  ``enabled`` gating, the add→query round trip, WHERE filters, and prune all
  run without Docker.
* **Integration** — a Testcontainers-PostgreSQL round trip over all four repo
  methods, marked ``integration``/``slow`` and skipped gracefully when Docker
  or the ``testcontainers`` package is unavailable (ADR-008).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from orchestrator.experience_db import (
    DEFAULT_LEARNING_RETENTION_DAYS,
    DEFAULT_OPERATIONAL_RETENTION_DAYS,
    ExperienceRepository,
    LearningExperience,
    OperationalExperience,
)

# ── In-memory async-session fake ────────────────────────────────────────────


def _extract_equalities(clause: Any) -> list[tuple[str, str, Any]]:
    """Walk a SQLAlchemy whereclause into ``(column, op_name, value)`` tuples."""

    from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

    out: list[tuple[str, str, Any]] = []
    if clause is None:
        return out
    if isinstance(clause, BooleanClauseList):
        for child in clause.clauses:
            out.extend(_extract_equalities(child))
    elif isinstance(clause, BinaryExpression):
        column = clause.left
        name = getattr(column, "key", None) or getattr(column, "name", None)
        op = getattr(clause.operator, "__name__", "eq")
        value = getattr(clause.right, "value", None)
        out.append((name, op, value))
    return out


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> list[Any]:
        return list(self._rows)

    @property
    def rowcount(self) -> int:
        return len(self._rows)


class _FakeAsyncSession:
    """Stand-in for AsyncSession that honours the repository's statements."""

    def __init__(self, store: dict[str, list[Any]]) -> None:
        self._store = store

    async def __aenter__(self) -> "_FakeAsyncSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def add(self, instance: Any) -> None:
        table = type(instance).__tablename__
        self._store.setdefault(table, []).append(instance)

    async def commit(self) -> None:
        return None

    async def execute(self, stmt: Any) -> _FakeResult:
        # DELETE — used by prune().
        if stmt.__class__.__name__ == "Delete":
            table = stmt.table.name
            rows = self._store.get(table, [])
            deletes = _extract_equalities(stmt.whereclause)
            removed = [r for r in rows if _matches(r, deletes)]
            self._store[table] = [r for r in rows if r not in removed]
            return _FakeResult(removed)

        # SELECT — used by query_* methods.
        entity = stmt.column_descriptions[0]["entity"]
        table = entity.__tablename__
        rows = list(self._store.get(table, []))
        rows = [r for r in rows if _matches(r, _extract_equalities(stmt.whereclause))]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return _FakeResult(rows)


def _matches(row: Any, filters: list[tuple[str, str, Any]]) -> bool:
    for name, op, value in filters:
        actual = getattr(row, name, None)
        if op == "lt":
            if not (actual is not None and actual < value):
                return False
        else:  # eq (default)
            if actual != value:
                return False
    return True


def _make_factory(store: dict[str, list[Any]]):
    def _factory() -> _FakeAsyncSession:
        return _FakeAsyncSession(store)

    return _factory


# ── Defaults + construction ─────────────────────────────────────────────────


def test_retention_defaults():
    assert DEFAULT_OPERATIONAL_RETENTION_DAYS == 7
    assert DEFAULT_LEARNING_RETENTION_DAYS == 90


def test_missing_factory_raises_runtime_error():
    repo = ExperienceRepository(db_session_factory=None)

    async def _run() -> None:
        with pytest.raises(RuntimeError):
            await repo.query_operational()

    asyncio.run(_run())


def test_disabled_repository_skips_writes():
    store: dict[str, list[Any]] = {}
    repo = ExperienceRepository(db_session_factory=_make_factory(store), enabled=False)

    async def _run() -> None:
        await repo.record_operational(
            OperationalExperience(prompt_fingerprint="fp1")
        )
        await repo.record_learning(LearningExperience(prompt_fingerprint="fp1"))

    asyncio.run(_run())
    assert store == {}


# ── Fake round trip ─────────────────────────────────────────────────────────


def test_operational_round_trip_and_filter():
    store: dict[str, list[Any]] = {}
    repo = ExperienceRepository(db_session_factory=_make_factory(store), enabled=True)

    async def _run() -> None:
        await repo.record_operational(
            OperationalExperience(
                prompt_fingerprint="fp1",
                latency_ms=12.0,
                cost_usd=0.01,
                failure_class=None,
                created_at=datetime(2026, 7, 15, 10, tzinfo=timezone.utc),
            )
        )
        await repo.record_operational(
            OperationalExperience(
                prompt_fingerprint="fp1",
                failure_class="timeout",
                created_at=datetime(2026, 7, 15, 11, tzinfo=timezone.utc),
            )
        )

        all_fp1 = await repo.query_operational(prompt_fingerprint="fp1")
        assert len(all_fp1) == 2
        # ordered by created_at desc
        assert all_fp1[0].failure_class == "timeout"

        only_timeouts = await repo.query_operational(failure_class="timeout")
        assert len(only_timeouts) == 1
        assert only_timeouts[0].failure_class == "timeout"

        none = await repo.query_operational(prompt_fingerprint="absent")
        assert none == []

    asyncio.run(_run())


def test_learning_round_trip_and_filter():
    store: dict[str, list[Any]] = {}
    repo = ExperienceRepository(db_session_factory=_make_factory(store), enabled=True)

    async def _run() -> None:
        await repo.record_learning(
            LearningExperience(
                prompt_fingerprint="fp1",
                task_graph_fingerprint="tg1",
                planner_version="p1",
                consensus_quality=0.9,
                created_at=datetime(2026, 7, 15, 10, tzinfo=timezone.utc),
            )
        )
        await repo.record_learning(
            LearningExperience(
                prompt_fingerprint="fp1",
                task_graph_fingerprint="tg2",
                planner_version="p2",
                created_at=datetime(2026, 7, 15, 11, tzinfo=timezone.utc),
            )
        )

        by_graph = await repo.query_learning(task_graph_fingerprint="tg1")
        assert len(by_graph) == 1
        assert by_graph[0].planner_version == "p1"

        by_planner = await repo.query_learning(planner_version="p2")
        assert len(by_planner) == 1

    asyncio.run(_run())


def test_prune_deletes_across_both_tables():
    store: dict[str, list[Any]] = {}
    repo = ExperienceRepository(db_session_factory=_make_factory(store), enabled=True)
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    new = datetime(2026, 7, 15, tzinfo=timezone.utc)
    cutoff = datetime(2026, 6, 1, tzinfo=timezone.utc)

    async def _run() -> int:
        await repo.record_operational(
            OperationalExperience(prompt_fingerprint="fp", created_at=old)
        )
        await repo.record_operational(
            OperationalExperience(prompt_fingerprint="fp", created_at=new)
        )
        await repo.record_learning(
            LearningExperience(prompt_fingerprint="fp", created_at=old)
        )
        return await repo.prune(before=cutoff)

    removed = asyncio.run(_run())
    assert removed == 2  # one operational + one learning
    assert len(store["experience_operational"]) == 1
    assert len(store["experience_learning"]) == 0


# ── Integration: real PostgreSQL via Testcontainers (ADR-008) ───────────────


def _testcontainers_available() -> bool:
    try:
        import docker  # noqa: F401
        from testcontainers.postgres import PostgresContainer  # noqa: F401
    except Exception:
        return False
    try:
        import docker as _docker

        _docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.skipif(
    not _testcontainers_available(),
    reason="Docker/testcontainers unavailable — skipping PostgreSQL integration test",
)
def test_experience_repository_postgres_round_trip():
    """All four repo methods against a real PostgreSQL container (ADR-008)."""

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from testcontainers.postgres import PostgresContainer

    from core.database import Base

    # Importing the models registers both tables on ``Base.metadata``.
    from core.models import ExperienceLearningRecord, ExperienceOperationalRecord  # noqa: F401

    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        url = postgres.get_connection_url().replace(
            "postgresql+psycopg2", "postgresql+asyncpg"
        )

        async def _run() -> None:
            engine = create_async_engine(url)
            try:
                async with engine.begin() as conn:
                    try:
                        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                    except Exception:
                        pass
                    await conn.run_sync(Base.metadata.create_all)
                factory = async_sessionmaker(engine, expire_on_commit=False)
                repo = ExperienceRepository(db_session_factory=factory, enabled=True)

                await repo.record_operational(
                    OperationalExperience(
                        prompt_fingerprint="fp1",
                        latency_ms=42.0,
                        failure_class="timeout",
                    )
                )
                await repo.record_learning(
                    LearningExperience(
                        prompt_fingerprint="fp1",
                        planner_version="p1",
                        consensus_quality=0.8,
                    )
                )

                ops = await repo.query_operational(prompt_fingerprint="fp1")
                assert len(ops) == 1 and ops[0].failure_class == "timeout"

                learns = await repo.query_learning(planner_version="p1")
                assert len(learns) == 1 and learns[0].consensus_quality == 0.8

                removed = await repo.prune(before=datetime.now(timezone.utc) + timedelta(days=1))
                assert removed == 2
            finally:
                await engine.dispose()

        asyncio.run(_run())
