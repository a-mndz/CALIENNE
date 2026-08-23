"""005 - memory search: tsvector + indexes on conversation_messages.

Memory v1 (ReFind pattern, arXiv:2608.12888; design in
.research_tmp/retry_agent_memory.md idea 1): the durable turn store becomes
lexically searchable with **no LLM extraction and no trigger maintenance** —
a GENERATED ALWAYS ... STORED column keeps the index derived from content by
construction, so the write path stays a plain INSERT.

- ``content_tsv``: english tsvector over ``content``.
- GIN index for ``@@ websearch_to_tsquery(...)`` lookups.
- ``(session_id, timestamp DESC)`` for ordered history reads and temporal
  narrowing — only ``session_id`` was indexed before.

Tenancy note (MAFIA poisoning, 90.7% on shared memory): ``conversation_messages``
carries NO owner column on purpose — the owner lives on the parent session row
(HIGH-015), so every memory query MUST join ``conversation_sessions`` and
filter ``owner_email``. The provider in orchestrator/memory_search.py enforces
this; a query that forgets the join returns every user's turns.

Revision ID: 005_memory_search
Revises: 004_sessions_updated_at
Create Date: 2026-08-22
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "005_memory_search"
down_revision: Union[str, None] = "004_sessions_updated_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversation_messages "
        "ADD COLUMN content_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', content)) STORED"
    )
    op.execute(
        "CREATE INDEX ix_conversation_messages_tsv "
        "ON conversation_messages USING GIN (content_tsv)"
    )
    op.execute(
        'CREATE INDEX ix_conversation_messages_session_ts '
        'ON conversation_messages (session_id, "timestamp" DESC)'
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_conversation_messages_session_ts")
    op.execute("DROP INDEX IF EXISTS ix_conversation_messages_tsv")
    op.execute("ALTER TABLE conversation_messages DROP COLUMN IF EXISTS content_tsv")
