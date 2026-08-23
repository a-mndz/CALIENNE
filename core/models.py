"""
SQLAlchemy database models for AETHERIS.

HIGH-017 audit fix: this module now exposes models for the persistent
counterparts of in-memory state — :class:`ConversationSessionRecord`,
:class:`ConversationMessageRecord`, :class:`CheckpointRecord`, and
:class:`TelemetryEvent`.  Migration bridge to in-memory
:class:`ConversationDirector` and :class:`CheckpointManager` is delivered
in Phase 2 (CRIT-003, MED-007, HIGH-008); the schema is the first half of
that work and is what Alembic env pytest fixtures instantiate.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """User database model."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # MED-023 prep (Phase 2): default role of ``user``; admin promoted out-of-band.
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class ConversationSessionRecord(Base):
    """Persistable counterpart to ConversationDirector.ConversationSession.

    HIGH-015: ``owner_email`` enforces per-user isolation at the row level.
    MED-007 prep: paired with the migration chain to make sessions survive
    server restarts in Phase 2.
    """

    __tablename__ = "conversation_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    owner_email: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    # 004: last save activity — the conversations list orders by this so a
    # re-saved session floats to the top instead of showing creation time.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["ConversationMessageRecord"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_sessions_owner_created", "owner_email", "created_at"),
    )


class ConversationMessageRecord(Base):
    """Single turn inside a session."""

    __tablename__ = "conversation_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    session: Mapped[ConversationSessionRecord] = relationship(back_populates="messages")


class CheckpointRecord(Base):
    """Persistable counterpart to CheckpointManager checkpoints (CRIT-003)."""

    __tablename__ = "checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    checkpoint_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_checkpoints_request_stage", "request_id", "stage"),
    )


class TelemetryEvent(Base):
    """Telemetry event — observation phase 1 surface (MED-018 prep)."""

    __tablename__ = "telemetry_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_telemetry_stage_ts", "stage", "timestamp"),
    )


class ExperienceOperationalRecord(Base):
    """High-write / short-retention Experience DB row (RFC-004 §7.1, DEC-013).

    Records per-request operational experience — prediction-vs-actual deltas,
    latency, cost, and failure/recovery outcomes — with a default 7-day
    retention.  Written through :class:`orchestrator.experience_db.ExperienceRepository`
    only; no orchestration module talks to this table directly (invariant 8).
    """

    __tablename__ = "experience_operational"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prompt_fingerprint: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    task_profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    prediction_actual_deltas: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    failure_class: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    recovery_action: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    replay_trace_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_experience_operational_created", "created_at"),
    )


class ExperienceLearningRecord(Base):
    """Read-heavy / long-retention Experience DB row (RFC-004 §7.2, DEC-013).

    Records planner / consensus / routing quality signals and the graph
    mutation audit for offline learning, with a default 90-day retention.  In
    v1 this table is written but never used for live rerouting (DEC-005); the
    ``pgvector`` semantic layer lights up against it in v2 (DEC-007).
    """

    __tablename__ = "experience_learning"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prompt_fingerprint: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    task_profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    task_graph_fingerprint: Mapped[Optional[str]] = mapped_column(
        String(64), index=True, nullable=True
    )
    planner_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    consensus_quality: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    routing_quality: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    user_satisfaction: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    graph_mutation_audit: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    replay_trace_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_experience_learning_created", "created_at"),
    )
