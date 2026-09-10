"""
Document Ingestion & Recursive Chunking Engine for Calienne RAG Subsystems.

Supports recursive character splitting with syntax boundary preservation
(code blocks, paragraph double newlines, sentences, words) and configurable
chunk size and token overlap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


@dataclass
class Chunk:
    """Represents a chunked segment of a document."""
    index: int
    content: str
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentChunker:
    """
    Recursive boundary-preserving text chunker.

    Attributes:
        chunk_size: Target token capacity per chunk (default: 512 tokens).
        chunk_overlap: Sliding window overlap between consecutive chunks (default: 64 tokens).
        separators: Priority list of boundary separators.
    """

    DEFAULT_SEPARATORS: tuple[str, ...] = (
        "\n```",       # Fenced code block boundary
        "\n\n",        # Paragraph break
        "\n",          # Line break
        ". ",          # Sentence end
        "? ",          # Question sentence end
        "! ",          # Exclamation sentence end
        "; ",          # Clause separator
        ", ",          # Phrase separator
        " ",           # Word separator
        "",            # Character fallback
    )

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        separators: Sequence[str] | None = None,
        chars_per_token: float = 4.0,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than 0")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap cannot be negative")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be strictly less than chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = list(separators or self.DEFAULT_SEPARATORS)
        self.chars_per_token = chars_per_token

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for a string (~4 chars/token heuristic)."""
        if not text:
            return 0
        return max(1, int(len(text) / self.chars_per_token))

    def split_text(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """
        Split text recursively using hierarchical boundary separators.

        Parameters:
            text: Raw input document string.
            metadata: Optional dictionary of document metadata to attach to chunks.

        Returns:
            List of Chunk objects with token counts and sequential indices.
        """
        if not text or not text.strip():
            return []

        base_meta = dict(metadata or {})
        raw_pieces = self._split_recursive(text.strip(), self.separators)
        merged_chunks = self._merge_pieces(raw_pieces)

        chunks: list[Chunk] = []
        for idx, content in enumerate(merged_chunks):
            token_count = self.estimate_tokens(content)
            chunk_meta = dict(base_meta)
            chunk_meta["chunk_index"] = idx
            chunks.append(
                Chunk(
                    index=idx,
                    content=content,
                    token_count=token_count,
                    metadata=chunk_meta,
                )
            )

        return chunks

    def split_document(
        self,
        file_path: str | Path,
        metadata: dict[str, Any] | None = None,
        encoding: str = "utf-8",
    ) -> list[Chunk]:
        """
        Read a file from disk and split into chunks.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Document file not found: {path}")

        text = path.read_text(encoding=encoding)
        doc_meta = dict(metadata or {})
        doc_meta.setdefault("source_file", str(path.name))
        doc_meta.setdefault("source_path", str(path.resolve()))
        return self.split_text(text, metadata=doc_meta)

    def _split_recursive(self, text: str, separators: Sequence[str]) -> list[str]:
        """Recursively divide text using available separators until pieces fit budget."""
        if not text:
            return []

        if self.estimate_tokens(text) <= self.chunk_size:
            return [text]

        if not separators:
            # Fallback: hard character slice
            max_chars = int(self.chunk_size * self.chars_per_token)
            return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]

        separator = separators[0]
        remaining_separators = separators[1:]

        if separator == "":
            return list(text)

        if separator in text:
            # Split and retain separator where possible for syntax integrity
            if separator == "\n```":
                parts = text.split("\n```")
                splits = [parts[0]] + [f"\n```{p}" for p in parts[1:]]
            else:
                splits = text.split(separator)
                if separator not in ("\n\n", "\n"):
                    # Re-attach trailing separator to preserve punctuation
                    splits = [s + separator if i < len(splits) - 1 else s for i, s in enumerate(splits)]
        else:
            return self._split_recursive(text, remaining_separators)

        result: list[str] = []
        for part in splits:
            part = part.strip()
            if not part:
                continue
            if self.estimate_tokens(part) <= self.chunk_size:
                result.append(part)
            else:
                result.extend(self._split_recursive(part, remaining_separators))

        return result

    def _merge_pieces(self, pieces: list[str]) -> list[str]:
        """Merge short pieces up to chunk_size with sliding chunk_overlap."""
        if not pieces:
            return []

        merged: list[str] = []
        current_accum: list[str] = []
        current_tokens = 0

        for piece in pieces:
            piece_tokens = self.estimate_tokens(piece)

            if current_tokens + piece_tokens <= self.chunk_size:
                current_accum.append(piece)
                current_tokens += piece_tokens
            else:
                if current_accum:
                    merged_text = "\n\n".join(current_accum).strip()
                    if merged_text:
                        merged.append(merged_text)

                    # Build overlap from tail of current_accum
                    overlap_accum: list[str] = []
                    overlap_tokens = 0
                    for p in reversed(current_accum):
                        p_toks = self.estimate_tokens(p)
                        if overlap_tokens + p_toks <= self.chunk_overlap:
                            overlap_accum.insert(0, p)
                            overlap_tokens += p_toks
                        else:
                            break

                    current_accum = list(overlap_accum)
                    current_tokens = overlap_tokens

                current_accum.append(piece)
                current_tokens += piece_tokens

        if current_accum:
            final_text = "\n\n".join(current_accum).strip()
            if final_text:
                merged.append(final_text)

        return merged
