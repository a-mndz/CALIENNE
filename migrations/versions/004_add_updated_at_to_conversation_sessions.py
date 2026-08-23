"""004 - add updated_at to conversation sessions.

Tier 0 quick-win: ``conversation_sessions`` had no ``updated_at``, so the
conversations list ordered and labelled every session by its creation time
forever — a re-saved conversation never floated to the top and never showed
its true last-activity time. Backfills existing rows to ``created_at`` so the
column is non-null from the start.

Revision ID: 004_sessions_updated_at
Revises: 003_experience_db
Create Date: 2026-08-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_sessions_updated_at"
down_revision: Union[str, None] = "003_experience_db"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversation_sessions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Existing rows: last activity is best approximated by creation time.
    op.execute("UPDATE conversation_sessions SET updated_at = created_at")


def downgrade() -> None:
    op.drop_column("conversation_sessions", "updated_at")
