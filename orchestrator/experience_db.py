"""Experience Database repository (RFC-004 §7, ADR-008, DEC-013).

The Experience DB is the durable, queryable record of what actually happened
during execution.  It is split into **two physical tables** with different
lifecycles (DEC-013):

* ``experience_operational`` — high-write, short retention (default 7 days):
  prediction-vs-actual deltas, latency, cost, failure/recovery outcomes.
* ``experience_learning`` — read-heavy, long retention (default 90 days):
  planner / consensus / routing quality and the graph mutation audit.

This module exposes the **only** path to that SQL (RFC-004 §7.3, invariant 8):
:class:`ExperienceRepository`.  No orchestration module talks to the tables
directly.  The repository is constructed with a ``db_session_factory`` — a
callable returning an ``AsyncSession`` — exactly like
:class:`~orchestrator.checkpoints.CheckpointManager` (CRIT-003).  The
connection pool behind that factory is owned by the ``ResourceManager``
(ADR-008), not by the repository.

Writes are gated by ``CALIENNE_ENABLE_EXPERIENCE_DB`` (RFC-006).  The
repository itself is async-first (ADR-002); a missing factory raises
``RuntimeError`` from the internal helper so callers can decide whether to
degrade.  ``pgvector`` is installed but unused in v1 (DEC-007).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import Field

from core.base import CalienneBaseModel

LOGGER = logging.getLogger(__name__)

# Retention defaults (RFC-004 §7.1/§7.2). Enforced at prune time, not by the
# schema — the caller decides the cadence.
DEFAULT_OPERATIONAL_RETENTION_DAYS = 7
DEFAULT_LEARNING_RETENTION_DAYS = 90


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Transfer objects (decoupled from the ORM rows) ──────────────────────────


class OperationalExperience(CalienneBaseModel):
    """A single ``experience_operational`` record (RFC-004 §7.1)."""

    prompt_fingerprint: str
    task_profile: dict[str, Any] = Field(default_factory=dict)
    prediction_actual_deltas: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float | None = None
    cost_usd: float | None = None
    failure_class: str | None = None
    recovery_action: str | None = None
    replay_trace_id: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)


class LearningExperience(CalienneBaseModel):
    """A single ``experience_learning`` record (RFC-004 §7.2)."""

    prompt_fingerprint: str
    task_profile: dict[str, Any] = Field(default_factory=dict)
    task_graph_fingerprint: str | None = None
    planner_version: str | None = None
    consensus_quality: float | None = None
    routing_quality: float | None = None
    user_satisfaction: float | None = None
    graph_mutation_audit: dict[str, Any] = Field(default_factory=dict)
    replay_trace_id: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)


# ── Repository ──────────────────────────────────────────────────────────────


class ExperienceRepository:
    """The sole SQL boundary for the Experience DB (RFC-004 §7.3)."""

    def __init__(
        self,
        *,
        db_session_factory: Callable[[], Any] | None = None,
        enabled: bool = True,
    ) -> None:
        self.db_session_factory = db_session_factory
        self.enabled = enabled
        if db_session_factory is None:
            LOGGER.warning(
                "ExperienceRepository created without a db_session_factory; "
                "write/query operations will raise RuntimeError until one is wired in."
            )

    def _require_factory(self) -> Callable[[], Any]:
        if self.db_session_factory is None:
            raise RuntimeError(
                "ExperienceRepository requires a db_session_factory to be provided."
            )
        return self.db_session_factory

    # ── Writes ───────────────────────────────────────────────────────────────

    async def record_operational(self, record: OperationalExperience) -> None:
        """Insert one operational-experience row (gated by ``enabled``)."""

        if not self.enabled:
            LOGGER.debug("ExperienceRepository disabled; skipping operational write.")
            return
        from core.models import ExperienceOperationalRecord

        factory = self._require_factory()
        async with factory() as session:
            session.add(
                ExperienceOperationalRecord(
                    prompt_fingerprint=record.prompt_fingerprint,
                    task_profile=record.task_profile,
                    prediction_actual_deltas=record.prediction_actual_deltas,
                    latency_ms=record.latency_ms,
                    cost_usd=record.cost_usd,
                    failure_class=record.failure_class,
                    recovery_action=record.recovery_action,
                    replay_trace_id=record.replay_trace_id,
                    created_at=record.created_at,
                )
            )
            await session.commit()

    async def record_learning(self, record: LearningExperience) -> None:
        """Insert one learning-experience row (gated by ``enabled``)."""

        if not self.enabled:
            LOGGER.debug("ExperienceRepository disabled; skipping learning write.")
            return
        from core.models import ExperienceLearningRecord

        factory = self._require_factory()
        async with factory() as session:
            session.add(
                ExperienceLearningRecord(
                    prompt_fingerprint=record.prompt_fingerprint,
                    task_profile=record.task_profile,
                    task_graph_fingerprint=record.task_graph_fingerprint,
                    planner_version=record.planner_version,
                    consensus_quality=record.consensus_quality,
                    routing_quality=record.routing_quality,
                    user_satisfaction=record.user_satisfaction,
                    graph_mutation_audit=record.graph_mutation_audit,
                    replay_trace_id=record.replay_trace_id,
                    created_at=record.created_at,
                )
            )
            await session.commit()

    # ── Queries ──────────────────────────────────────────────────────────────

    async def query_operational(
        self,
        *,
        prompt_fingerprint: str | None = None,
        failure_class: str | None = None,
        limit: int = 100,
    ) -> list[OperationalExperience]:
        from sqlalchemy import select

        from core.models import ExperienceOperationalRecord

        factory = self._require_factory()
        async with factory() as session:
            stmt = select(ExperienceOperationalRecord)
            if prompt_fingerprint is not None:
                stmt = stmt.where(
                    ExperienceOperationalRecord.prompt_fingerprint == prompt_fingerprint
                )
            if failure_class is not None:
                stmt = stmt.where(
                    ExperienceOperationalRecord.failure_class == failure_class
                )
            stmt = stmt.order_by(ExperienceOperationalRecord.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            return [self._to_operational(row) for row in result.scalars()]

    async def query_learning(
        self,
        *,
        prompt_fingerprint: str | None = None,
        task_graph_fingerprint: str | None = None,
        planner_version: str | None = None,
        limit: int = 100,
    ) -> list[LearningExperience]:
        from sqlalchemy import select

        from core.models import ExperienceLearningRecord

        factory = self._require_factory()
        async with factory() as session:
            stmt = select(ExperienceLearningRecord)
            if prompt_fingerprint is not None:
                stmt = stmt.where(
                    ExperienceLearningRecord.prompt_fingerprint == prompt_fingerprint
                )
            if task_graph_fingerprint is not None:
                stmt = stmt.where(
                    ExperienceLearningRecord.task_graph_fingerprint == task_graph_fingerprint
                )
            if planner_version is not None:
                stmt = stmt.where(
                    ExperienceLearningRecord.planner_version == planner_version
                )
            stmt = stmt.order_by(ExperienceLearningRecord.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            return [self._to_learning(row) for row in result.scalars()]

    # ── Retention ────────────────────────────────────────────────────────────

    async def prune(self, before: datetime) -> int:
        """Delete rows in both tables created before ``before``; return count.

        Retention cadence is the caller's decision (RFC-004 §7.1/§7.2); the
        repository only enforces the cutoff it is handed.
        """

        from sqlalchemy import delete

        from core.models import ExperienceLearningRecord, ExperienceOperationalRecord

        factory = self._require_factory()
        removed = 0
        async with factory() as session:
            op_result = await session.execute(
                delete(ExperienceOperationalRecord).where(
                    ExperienceOperationalRecord.created_at < before
                )
            )
            learn_result = await session.execute(
                delete(ExperienceLearningRecord).where(
                    ExperienceLearningRecord.created_at < before
                )
            )
            await session.commit()
            removed = int(op_result.rowcount or 0) + int(learn_result.rowcount or 0)
        return removed

    # ── Adapters ─────────────────────────────────────────────────────────────

    @staticmethod
    def _to_operational(record: Any) -> OperationalExperience:
        return OperationalExperience(
            prompt_fingerprint=record.prompt_fingerprint,
            task_profile=record.task_profile or {},
            prediction_actual_deltas=record.prediction_actual_deltas or {},
            latency_ms=record.latency_ms,
            cost_usd=record.cost_usd,
            failure_class=record.failure_class,
            recovery_action=record.recovery_action,
            replay_trace_id=record.replay_trace_id,
            created_at=record.created_at,
        )

    @staticmethod
    def _to_learning(record: Any) -> LearningExperience:
        return LearningExperience(
            prompt_fingerprint=record.prompt_fingerprint,
            task_profile=record.task_profile or {},
            task_graph_fingerprint=record.task_graph_fingerprint,
            planner_version=record.planner_version,
            consensus_quality=record.consensus_quality,
            routing_quality=record.routing_quality,
            user_satisfaction=record.user_satisfaction,
            graph_mutation_audit=record.graph_mutation_audit or {},
            replay_trace_id=record.replay_trace_id,
            created_at=record.created_at,
        )
