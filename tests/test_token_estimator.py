"""Tests for multi-provider token estimation registry (GAP-RAG-08 / P2-07)."""

from __future__ import annotations

import pytest

from orchestrator.memory_manager import MemoryManager, TokenEstimatorRegistry


def test_token_estimator_openai_and_default():
    text = "Hello world from CALIENNE reasoning orchestrator."
    count = TokenEstimatorRegistry.estimate_tokens(text, "gpt-4o")
    assert count > 0
    default_count = TokenEstimatorRegistry.estimate_tokens(text, None)
    assert default_count > 0


def test_token_estimator_anthropic_and_gemini():
    text = "Detailed logical proof of Byzantine consensus properties."
    claude_count = TokenEstimatorRegistry.estimate_tokens(text, "claude-3-5-sonnet")
    gemini_count = TokenEstimatorRegistry.estimate_tokens(text, "gemini-1.5-pro")

    assert claude_count > 0
    assert gemini_count > 0


def test_memory_manager_track_tokens_supports_model():
    mm = MemoryManager()
    messages = [
        {"role": "user", "content": "What is the capital of France?"},
        {"role": "assistant", "content": "The capital of France is Paris."},
    ]
    tokens = mm.track_tokens(messages, model_name="claude-3-7-sonnet")
    assert tokens > 0


def test_semantic_core_extraction_preserves_sentences():
    long_content = "Step 1: Initialize database pool. Step 2: Configure 50 workers. Step 3: Run migrations."
    core = MemoryManager._extract_semantic_core(long_content, max_chars=40)
    assert "Step 1" in core
