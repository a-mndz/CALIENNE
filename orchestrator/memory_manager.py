"""
calienne — Adaptive Multi-Model Reasoning Orchestrator
Memory Manager: context window management with compression strategies.

Handles conversation history tracking, token counting, and context window
management with multiple summarization strategies (truncation, semantic
compression, hierarchical summarization).
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SummarizationStrategy(str, Enum):
    """Supported summarization strategies for history compression."""

    TRUNCATION = "truncation"
    SEMANTIC_COMPRESSION = "semantic_compression"
    HIERARCHICAL = "hierarchical"


class InsufficientCapacityError(Exception):
    """Raised when compression cannot reduce token count below the rejection threshold."""

    def __init__(
        self,
        required_tokens: int,
        available_tokens: int,
        compression_attempted: bool,
    ) -> None:
        self.required_tokens = required_tokens
        self.available_tokens = available_tokens
        self.compression_attempted = compression_attempted
        super().__init__(
            f"insufficient context window capacity: "
            f"required_tokens={required_tokens}, "
            f"available_tokens={available_tokens}, "
            f"compression_attempted={compression_attempted}"
        )


class MemoryManager:
    """Enhanced memory management with multiple summarization strategies.

    Specifications from Requirement 15:
    - Token counting using same tokenization method as target LLM
    - Compression triggered at 80% of provider-specific maximum token limit
    - Preserve system prompts and most recent 5 user/assistant message pairs
    - Summarization strategies: truncation, semantic_compression (500 tokens max),
      hierarchical_summarization (300 tokens per level)
    - Fallback to truncation if summarization fails
    - Reject requests if compression cannot reduce below 90% of maximum limit
    """

    TRUNCATION_THRESHOLD = 0.8
    COMPRESSION_REJECTION_THRESHOLD = 0.9
    PRESERVED_TURNS = 5
    SEMANTIC_COMPRESSION_MAX_TOKENS = 500
    HIERARCHICAL_SUMMARY_MAX_TOKENS = 300

    def __init__(
        self,
        strategy: SummarizationStrategy = SummarizationStrategy.TRUNCATION,
        context_limit: int = 128_000,
    ) -> None:
        self.strategy = strategy
        self.context_limit = context_limit
        self._token_encoder: Any = None

    def _get_encoder(self) -> Any:
        """Lazy-load tiktoken encoder."""
        if self._token_encoder is None:
            try:
                import tiktoken

                self._token_encoder = tiktoken.get_encoding("cl100k_base")
            except Exception as exc:
                logger.warning(
                    "tiktoken unavailable; using word-count fallback for token estimation: %s",
                    exc,
                    extra={"stage": "memory_manager"}
                )
                self._token_encoder = None
        return self._token_encoder

    def track_tokens(self, messages: list[dict[str, str]]) -> int:
        """Count tokens for a list of messages.

        Uses tiktoken when available, falls back to a word-count heuristic
        (approximately 1.3 tokens per word).
        """
        text = " ".join(m.get("content", "") for m in messages)
        encoder = self._get_encoder()
        if encoder is not None:
            return len(encoder.encode(text))
        words = text.split()
        return max(1, int(len(words) * 1.3)) if words else 0

    def calculate_remaining_capacity(
        self, current_tokens: int, provider_max_limit: Optional[int] = None
    ) -> int:
        """Calculate remaining token capacity in context window."""
        limit = provider_max_limit if provider_max_limit is not None else self.context_limit
        return max(0, limit - current_tokens)

    def should_compress(self, current_tokens: int, max_limit: Optional[int] = None) -> bool:
        """Check if compression is needed based on 80% threshold."""
        limit = max_limit if max_limit is not None else self.context_limit
        return current_tokens > self.TRUNCATION_THRESHOLD * limit

    def compress_history(
        self,
        messages: list[dict[str, str]],
        strategy: Optional[SummarizationStrategy] = None,
        max_limit: Optional[int] = None,
    ) -> tuple[list[dict[str, str]], Optional[str]]:
        """Compress history using the specified strategy.

        Returns (compressed_messages, summary_text).

        On strategy failure, falls back to TRUNCATION and logs the error.
        """
        effective_strategy = strategy if strategy is not None else self.strategy
        limit = max_limit if max_limit is not None else self.context_limit
        original_count = len(messages)

        try:
            if effective_strategy == SummarizationStrategy.TRUNCATION:
                compressed, summary = self._truncate(messages, self.PRESERVED_TURNS)
            elif effective_strategy == SummarizationStrategy.SEMANTIC_COMPRESSION:
                compressed, summary = self._semantic_compression(messages, self.PRESERVED_TURNS)
            elif effective_strategy == SummarizationStrategy.HIERARCHICAL:
                compressed, summary = self._hierarchical(messages, self.PRESERVED_TURNS)
            else:
                compressed, summary = self._truncate(messages, self.PRESERVED_TURNS)
        except Exception as exc:
            logger.error(
                "Strategy %s failed: %s; falling back to TRUNCATION",
                effective_strategy.value,
                exc,
                extra={"stage": "memory_manager", "strategy": effective_strategy.value, "error": str(exc)}
            )
            compressed, summary = self._truncate(messages, self.PRESERVED_TURNS)

        compressed_count = len(compressed) if compressed else 0
        metrics = self.get_context_metrics(original_count, compressed_count, limit)

        if metrics.get("compression_failed", False):
            logger.warning("Compression failed for strategy %s", effective_strategy.value, extra={"stage": "memory_manager", "strategy": effective_strategy.value})  # noqa: E501

        return compressed, summary

    def get_context_metrics(
        self,
        original_token_count: int,
        compressed_token_count: int,
        max_limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """Return context window metrics."""
        limit = max_limit if max_limit is not None else self.context_limit
        used_tokens = compressed_token_count
        remaining_tokens = max(0, limit - used_tokens)
        compression_ratio = (
            original_token_count / compressed_token_count
            if compressed_token_count > 0
            else 1.0
        )
        return {
            "used_tokens": used_tokens,
            "remaining_tokens": remaining_tokens,
            "compression_ratio": round(compression_ratio, 4),
            "compression_failed": False,
        }

    # ── Strategy Implementations ────────────────────────────────────────

    @staticmethod
    def _is_system_prompt(msg: dict[str, str]) -> bool:
        return msg.get("role") == "system"

    def _truncate(
        self, messages: list[dict[str, str]], preserve_recent: int
    ) -> tuple[list[dict[str, str]], Optional[str]]:
        """Truncation: preserve system prompts + most recent N turns."""
        system_msgs = [m for m in messages if self._is_system_prompt(m)]
        non_system = [m for m in messages if not self._is_system_prompt(m)]

        if len(non_system) <= preserve_recent:
            return list(messages), None

        removed = non_system[:-preserve_recent]
        preserved = non_system[-preserve_recent:]

        summary_parts = [f"[Truncated {len(removed)} messages]" if removed else ""]
        summary = " ".join(p for p in summary_parts if p) or None

        return system_msgs + preserved, summary

    def _semantic_compression(
        self, messages: list[dict[str, str]], preserve_recent: int
    ) -> tuple[list[dict[str, str]], Optional[str]]:
        """Semantic compression: generate summary not exceeding 500 tokens."""
        system_msgs = [m for m in messages if self._is_system_prompt(m)]
        non_system = [m for m in messages if not self._is_system_prompt(m)]

        if len(non_system) <= preserve_recent:
            return list(messages), None

        removed = non_system[:-preserve_recent]
        preserved = non_system[-preserve_recent:]

        summary_parts: list[str] = []
        for msg in removed:
            content = msg.get("content", "")
            if content:
                summary_parts.append(content[:200])

        summary_text = " ".join(summary_parts)
        summary_text = self._truncate_to_tokens(summary_text, self.SEMANTIC_COMPRESSION_MAX_TOKENS)

        return system_msgs + preserved, summary_text or None

    def _hierarchical(
        self, messages: list[dict[str, str]], preserve_recent: int
    ) -> tuple[list[dict[str, str]], Optional[str]]:
        """Hierarchical summarization: multi-level summaries, each max 300 tokens."""
        system_msgs = [m for m in messages if self._is_system_prompt(m)]
        non_system = [m for m in messages if not self._is_system_prompt(m)]

        if len(non_system) <= preserve_recent:
            return list(messages), None

        removed = non_system[:-preserve_recent]
        preserved = non_system[-preserve_recent:]

        chunk_size = max(1, len(removed) // 3)
        level_summaries: list[str] = []
        for i in range(0, len(removed), chunk_size):
            chunk = removed[i : i + chunk_size]
            chunk_text = " ".join(m.get("content", "")[:200] for m in chunk if m.get("content"))
            chunk_summary = self._truncate_to_tokens(
                chunk_text, self.HIERARCHICAL_SUMMARY_MAX_TOKENS
            )
            level_summaries.append(chunk_summary or "")

        summary_text = " ".join(s for s in level_summaries if s)

        return system_msgs + preserved, summary_text or None

    @staticmethod
    def _truncate_to_tokens(text: str, max_tokens: int) -> str:
        """Truncate text to approximately max_tokens using word count."""
        words = text.split()
        estimated_tokens = int(len(words) * 1.3)
        if estimated_tokens <= max_tokens:
            return text
        keep_words = int(max_tokens / 1.3)
        return " ".join(words[:keep_words])
