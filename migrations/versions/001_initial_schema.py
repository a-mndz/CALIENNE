"""001 — initial calienne schema.

CRIT-006 / HIGH-017: create the ``users``, ``conversation_sessions``,
``conversation_messages``, ``checkpoints``, and ``telemetry_events`` tables
defined in :mod:`core.models`.  This migration is the single source of
truth for the production schema and replaces the implicit
``Base.metadata.create_all`` pre-migration bootstrap.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-06-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("owner_email", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("session_id", name="uq_sessions_session_id"),
    )
    op.create_index("ix_sessions_session_id", "conversation_sessions", ["session_id"], unique=False)
    op.create_index(
        "ix_sessions_owner_email", "conversation_sessions", ["owner_email"], unique=False
    )
    op.create_index(
        "ix_sessions_owner_created",
        "conversation_sessions",
        ["owner_email", "created_at"],
        unique=False,
    )

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_conversation_messages_session_id",
        "conversation_messages",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "checkpoints",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("checkpoint_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("user_email", sa.String(length=255), nullable=True),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("checkpoint_id", name="uq_checkpoints_checkpoint_id"),
    )
    op.create_index("ix_checkpoints_checkpoint_id", "checkpoints", ["checkpoint_id"], unique=False)
    op.create_index("ix_checkpoints_request_id", "checkpoints", ["request_id"], unique=False)
    op.create_index(
        "ix_checkpoints_request_stage", "checkpoints", ["request_id", "stage"], unique=False
    )
    op.create_index("ix_checkpoints_user_email", "checkpoints", ["user_email"], unique=False)

    op.create_table(
        "telemetry_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("user_email", sa.String(length=255), nullable=True),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("payload", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_telemetry_events_request_id", "telemetry_events", ["request_id"], unique=False
    )
    op.create_index(
        "ix_telemetry_events_user_email", "telemetry_events", ["user_email"], unique=False
    )
    op.create_index(
        "ix_telemetry_stage_ts", "telemetry_events", ["stage", "timestamp"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_telemetry_stage_ts", table_name="telemetry_events")
    op.drop_index("ix_telemetry_events_user_email", table_name="telemetry_events")
    op.drop_index("ix_telemetry_events_request_id", table_name="telemetry_events")
    op.drop_table("telemetry_events")

    op.drop_index("ix_checkpoints_user_email", table_name="checkpoints")
    op.drop_index("ix_checkpoints_request_stage", table_name="checkpoints")
    op.drop_index("ix_checkpoints_request_id", table_name="checkpoints")
    op.drop_index("ix_checkpoints_checkpoint_id", table_name="checkpoints")
    op.drop_table("checkpoints")

    op.drop_index(
        "ix_conversation_messages_session_id", table_name="conversation_messages"
    )
    op.drop_table("conversation_messages")

    op.drop_index("ix_sessions_owner_created", table_name="conversation_sessions")
    op.drop_index("ix_sessions_owner_email", table_name="conversation_sessions")
    op.drop_index("ix_sessions_session_id", table_name="conversation_sessions")
    op.drop_table("conversation_sessions")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
