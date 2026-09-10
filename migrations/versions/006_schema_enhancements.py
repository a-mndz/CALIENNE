"""006 - schema enhancements: session composite index, checkpoint session_id, FK cascade.

Revision ID: 006_schema_enhancements
Revises: 005_memory_search
Create Date: 2026-09-10
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_schema_enhancements"
down_revision: Union[str, None] = "005_memory_search"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add session_id to checkpoints
    op.add_column("checkpoints", sa.Column("session_id", sa.String(length=64), nullable=True))
    op.create_index("ix_checkpoints_session_id", "checkpoints", ["session_id"])

    # 2. Add composite index ix_sessions_owner_updated to conversation_sessions
    op.create_index("ix_sessions_owner_updated", "conversation_sessions", ["owner_email", "updated_at"])

    # 3. Optional pgvector extension setup if postgresql dialect
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.drop_index("ix_sessions_owner_updated", table_name="conversation_sessions")
    op.drop_index("ix_checkpoints_session_id", table_name="checkpoints")
    op.drop_column("checkpoints", "session_id")
