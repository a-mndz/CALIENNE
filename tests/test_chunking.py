"""
Unit tests for core.chunking DocumentChunker and Chunk dataclass.
"""

from __future__ import annotations

import pytest

from core.chunking import Chunk, DocumentChunker


def test_chunker_initialization_validation():
    with pytest.raises(ValueError, match="chunk_size must be greater than 0"):
        DocumentChunker(chunk_size=0)

    with pytest.raises(ValueError, match="chunk_overlap cannot be negative"):
        DocumentChunker(chunk_size=100, chunk_overlap=-1)

    with pytest.raises(ValueError, match="chunk_overlap must be strictly less than chunk_size"):
        DocumentChunker(chunk_size=100, chunk_overlap=100)

    chunker = DocumentChunker(chunk_size=256, chunk_overlap=32)
    assert chunker.chunk_size == 256
    assert chunker.chunk_overlap == 32


def test_chunker_empty_or_whitespace():
    chunker = DocumentChunker(chunk_size=100)
    assert chunker.split_text("") == []
    assert chunker.split_text("   \n\t  ") == []


def test_chunker_short_text_single_chunk():
    chunker = DocumentChunker(chunk_size=100)
    text = "Calienne is an adaptive multi-model reasoning orchestrator."
    chunks = chunker.split_text(text, metadata={"doc_id": "test_1"})
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].content == text
    assert chunks[0].metadata["doc_id"] == "test_1"
    assert chunks[0].metadata["chunk_index"] == 0
    assert chunks[0].token_count > 0


def test_chunker_splits_paragraphs_and_overlap():
    chunker = DocumentChunker(chunk_size=30, chunk_overlap=10)
    paragraphs = [
        "Paragraph one discussing the initial premises of logical reasoning.",
        "Paragraph two exploring alternative divergent creative possibilities.",
        "Paragraph three synthesizing the dialectic between logic and creativity.",
        "Paragraph four presenting final conclusions and claims verification.",
    ]
    doc = "\n\n".join(paragraphs)
    chunks = chunker.split_text(doc)
    assert len(chunks) > 1
    for c in chunks:
        assert isinstance(c, Chunk)
        assert len(c.content) > 0


def test_chunker_code_block_boundary():
    chunker = DocumentChunker(chunk_size=40, chunk_overlap=10)
    text = (
        "Here is an explanation of the pipeline architecture.\n\n"
        "```python\n"
        "def execute_pipeline(query: str):\n"
        "    return 'result'\n"
        "```\n\n"
        "After running the pipeline, we arbitrate the claims."
    )
    chunks = chunker.split_text(text)
    assert len(chunks) >= 1
    # Ensure code blocks do not break randomly in the middle
    all_content = " ".join(c.content for c in chunks)
    assert "def execute_pipeline" in all_content


def test_chunker_split_document(tmp_path):
    doc_path = tmp_path / "sample.md"
    content = "# Heading\n\nSome introductory content.\n\n## Section 2\n\nMore technical depth."
    doc_path.write_text(content, encoding="utf-8")

    chunker = DocumentChunker(chunk_size=20, chunk_overlap=5)
    chunks = chunker.split_document(doc_path)
    assert len(chunks) >= 1
    assert chunks[0].metadata["source_file"] == "sample.md"

    with pytest.raises(FileNotFoundError):
        chunker.split_document(tmp_path / "non_existent.md")
