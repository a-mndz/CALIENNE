"""Unit tests for Hybrid Reciprocal Rank Fusion (RRF) & Reranking (P1-05)."""

from __future__ import annotations

import pytest

from orchestrator.retrieval import (
    SourceCandidate,
    reciprocal_rank_fusion,
    rerank_candidates,
)


def test_reciprocal_rank_fusion_empty():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[]]) == []


def test_reciprocal_rank_fusion_combines_ranks():
    # Candidate A appears 1st in dense, 2nd in sparse
    cand_a = SourceCandidate(url="http://a.com", title="Doc A", excerpt="First document")
    # Candidate B appears 2nd in dense, 1st in sparse
    cand_b = SourceCandidate(url="http://b.com", title="Doc B", excerpt="Second document")
    # Candidate C appears only in dense at rank 3
    cand_c = SourceCandidate(url="http://c.com", title="Doc C", excerpt="Third document")

    dense_ranking = [cand_a, cand_b, cand_c]
    sparse_ranking = [cand_b, cand_a]

    fused = reciprocal_rank_fusion([dense_ranking, sparse_ranking], k=60)

    assert len(fused) == 3
    urls = [c.url for c in fused]
    assert "http://a.com" in urls[:2]
    assert "http://b.com" in urls[:2]
    assert urls[2] == "http://c.com"
    assert fused[2].final_score < fused[0].final_score


def test_reciprocal_rank_fusion_respects_limit():
    cand_a = SourceCandidate(url="http://a.com", title="Doc A", excerpt="First")
    cand_b = SourceCandidate(url="http://b.com", title="Doc B", excerpt="Second")
    cand_c = SourceCandidate(url="http://c.com", title="Doc C", excerpt="Third")

    fused = reciprocal_rank_fusion([[cand_a, cand_b, cand_c]], limit=2)
    assert len(fused) == 2


def test_rerank_candidates_boosts_relevant_tokens():
    cand_1 = SourceCandidate(url="http://1.com", title="Postgres database configuration", excerpt="Setting up connection pools", final_score=0.5)
    cand_2 = SourceCandidate(url="http://2.com", title="Machine learning pipelines", excerpt="Training neural network models", final_score=0.6)

    query = "postgres database connection pools"
    reranked = rerank_candidates([cand_2, cand_1], query=query)

    assert len(reranked) == 2
    assert reranked[0].url == "http://1.com"
