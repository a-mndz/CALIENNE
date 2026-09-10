"""007 - pgvector embeddings on experience_learning and document_chunks.

P1-03: pgvector Dense Embeddings & HNSW Index Pipeline (GAP-RAG-02, GAP-RAG-03).
Adds embedding vector(1024) to experience_learning for offline semantic retrieval,
creates document_chunks table with HNSW index for high-throughput cosine nearest-neighbor search.

Revision ID: 007_pgvector_embeddings
Revises: 006_schema_enhancements
Create Date: 2026-09-10
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_pgvector_embeddings"
down_revision: Union[str, None] = "006_schema_enhancements"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # 1. Add vector extension if pg
    if is_pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Add embedding column to experience_learning
    if is_pg:
        op.execute("ALTER TABLE experience_learning ADD COLUMN IF NOT EXISTS embedding vector(1024)")
    else:
        op.add_column("experience_learning", sa.Column("embedding", sa.JSON(), nullable=True))

    # 3. Create document_chunks table
    if is_pg:
        op.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id UUID PRIMARY KEY,
                document_id VARCHAR(128) NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                token_count INTEGER NOT NULL DEFAULT 0,
                metadata_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                embedding vector(1024),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        op.execute("CREATE INDEX IF NOT EXISTS ix_document_chunks_doc_idx ON document_chunks (document_id, chunk_index)")
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
            ON document_chunks USING hnsw (embedding vector_cosine_ops)
        """)
    else:
        op.create_table(
            "document_chunks",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("document_id", sa.String(128), nullable=False, index=True),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("token_count", sa.Integer(), nullable=False, default=0),
            sa.Column("metadata_payload", sa.JSON(), nullable=False, default=dict),
            sa.Column("embedding", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_document_chunks_doc_idx", "document_chunks", ["document_id", "chunk_index"])


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("DROP TABLE IF EXISTS document_chunks CASCADE")
        op.execute("ALTER TABLE experience_learning DROP COLUMN IF EXISTS embedding")
    else:
        op.drop_table("document_chunks")
        op.drop_column("experience_learning", "embedding")
