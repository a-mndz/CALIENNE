"""Tests for pgvector dense embeddings and DocumentChunk persistence (P1-03)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import core.models
from orchestrator.embeddings import EmbeddingService, cosine_similarity


def test_embedding_service_dimensions_and_norm() -> None:
    service = EmbeddingService(dimension=1024)
    vec = service.embed_text("Calienne multi-model orchestration with epistemic verification.")
    assert len(vec) == 1024
    norm = sum(x * x for x in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-4


def test_embedding_service_batch() -> None:
    service = EmbeddingService(dimension=1024)
    batch = ["Query A", "Query B", "Query C"]
    results = service.embed_batch(batch)
    assert len(results) == 3
    for r in results:
        assert len(r) == 1024


def test_cosine_similarity_properties() -> None:
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]
    assert abs(cosine_similarity(v1, v2) - 1.0) < 1e-5
    assert abs(cosine_similarity(v1, v3) - 0.0) < 1e-5


def test_semantic_affinity_preserved() -> None:
    service = EmbeddingService(dimension=1024)
    emb_target = service.embed_text("quantum computing state vector superposition")
    emb_similar = service.embed_text("quantum computing state superposition algorithms")
    emb_unrelated = service.embed_text("baking artisan sourdough bread with whole wheat flour")

    sim_high = cosine_similarity(emb_target, emb_similar)
    sim_low = cosine_similarity(emb_target, emb_unrelated)
    assert sim_high > sim_low


@pytest.mark.asyncio
async def test_document_chunk_record_persistence(tmp_path: Any) -> None:
    db_file = tmp_path / "test_embeddings.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")

    async with engine.begin() as conn:
        await conn.run_sync(lambda sc: core.models.DocumentChunkRecord.__table__.create(sc))
        await conn.run_sync(lambda sc: core.models.ExperienceLearningRecord.__table__.create(sc))

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    service = EmbeddingService(dimension=1024)
    embedding = service.embed_text("Hierarchical RAG document chunk.")

    chunk_id = uuid.uuid4()
    async with session_factory() as session:
        chunk = core.models.DocumentChunkRecord(
            id=chunk_id,
            document_id="doc-spec-001",
            chunk_index=0,
            content="Hierarchical RAG document chunk.",
            token_count=6,
            metadata_payload={"section": "architecture"},
            embedding=embedding,
        )
        session.add(chunk)
        await session.commit()

    async with session_factory() as session:
        result = await session.execute(
            select(core.models.DocumentChunkRecord).where(core.models.DocumentChunkRecord.id == chunk_id)
        )
        loaded = result.scalars().first()
        assert loaded is not None
        assert loaded.document_id == "doc-spec-001"
        assert loaded.chunk_index == 0
        assert loaded.token_count == 6
        assert loaded.metadata_payload["section"] == "architecture"
        assert loaded.embedding is not None
        assert len(loaded.embedding) == 1024

    await engine.dispose()
