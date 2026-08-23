"""Tests for the Smart RAG layer (Step 15, RFC-004 §3)."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest

from core.schemas import TaskProfile
from orchestrator.retrieval import (
    DEFAULT_RANKING_WEIGHTS,
    ROUTE_GATING,
    DeterministicRetrievalProvider,
    InMemoryRetrievalProvider,
    RetrievalProvider,
    RetrievalRequest,
    RetrievalResult,
    RetrievalService,
    SourceCandidate,
    StaticOverrideProvider,
    load_route_gating,
    load_routing_weights,
    rank_sources,
    score_candidate,
    should_retrieve,
)

# ── Fixtures ─────────────────────────────────────────────────────────────


def _candidate(
    *,
    url: str = "https://example.test",
    title: str = "Untitled",
    excerpt: str = "Excerpt text.",
    credibility: float = 0.5,
    freshness: float = 0.5,
    relevance: float = 0.5,
    consensus: float = 0.5,
) -> SourceCandidate:
    return SourceCandidate(
        url=url,
        title=title,
        excerpt=excerpt,
        credibility_score=credibility,
        freshness_score=freshness,
        relevance_score=relevance,
        consensus_score=consensus,
    )


def _scratch_file(name: str) -> Path:
    root = Path("C:/Users/amand/AppData/Local/Temp/opencode")
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{uuid.uuid4()}-{name}"


def _research_profile() -> TaskProfile:
    return TaskProfile(task_type="research", complexity="high", requires_rag=True)


def _general_profile(*, requires_rag: bool = False) -> TaskProfile:
    return TaskProfile(task_type="general", complexity="medium", requires_rag=requires_rag)


def _coding_profile() -> TaskProfile:
    return TaskProfile(task_type="coding", complexity="medium", requires_code_context=True)


def _math_profile() -> TaskProfile:
    return TaskProfile(task_type="math", complexity="medium", requires_math_check=True)


def _creative_profile() -> TaskProfile:
    return TaskProfile(task_type="creative", complexity="medium", requires_creativity=True)


# ── score_candidate / rank_sources ──────────────────────────────────────


def test_score_candidate_applies_rfc004_ranking_formula() -> None:
    candidate = _candidate(relevance=1.0, credibility=1.0, freshness=1.0, consensus=1.0)
    scored = score_candidate(candidate)
    # 1.0 * 0.4 + 1.0 * 0.25 + 1.0 * 0.15 + 1.0 * 0.2 == 1.0
    assert scored.final_score == pytest.approx(1.0)


def test_score_candidate_clamps_subscores_into_unit_interval() -> None:
    candidate = _candidate(relevance=2.0, credibility=-1.0, freshness=0.5, consensus=0.5)
    scored = score_candidate(candidate).clamped()
    assert 0.0 <= scored.relevance_score <= 1.0
    assert 0.0 <= scored.credibility_score <= 1.0
    # 0.4 + 0 + 0.15*0.5 + 0.2*0.5 == 0.575
    assert scored.final_score == pytest.approx(0.575)


def test_rank_sources_sorts_by_final_score_descending() -> None:
    candidates = [
        _candidate(title="low", relevance=0.2, credibility=0.2, freshness=0.2, consensus=0.2),
        _candidate(title="high", relevance=0.9, credibility=0.9, freshness=0.9, consensus=0.9),
        _candidate(title="mid", relevance=0.5, credibility=0.5, freshness=0.5, consensus=0.5),
    ]
    ranked = rank_sources(candidates, limit=10)
    assert [c.title for c in ranked] == ["high", "mid", "low"]


def test_rank_sources_does_not_invent_sources_to_fill_limit() -> None:
    candidates = [_candidate(title="only", relevance=1.0, credibility=1.0, freshness=1.0, consensus=1.0)]
    ranked = rank_sources(candidates, limit=10)
    assert len(ranked) == 1
    assert ranked[0].title == "only"


def test_rank_sources_uses_configured_weights_when_supplied() -> None:
    # Boost consensus by making it the heaviest weight.
    weights = {"relevance": 0.1, "credibility": 0.1, "freshness": 0.1, "consensus": 0.7}
    high_consensus = _candidate(title="consensus", relevance=0.4, credibility=0.4, freshness=0.4, consensus=1.0)  # noqa: E501
    high_relevance = _candidate(title="relevance", relevance=1.0, credibility=0.0, freshness=0.0, consensus=0.0)  # noqa: E501
    ranked = rank_sources([high_relevance, high_consensus], limit=5, weights=weights)
    assert ranked[0].title == "consensus"


# ── should_retrieve (route gating) ──────────────────────────────────────


def test_should_retrieve_research_is_required() -> None:
    should, mode, _reason = should_retrieve(_research_profile())
    assert should is True
    assert mode == "required"


def test_should_retrieve_general_is_optional_and_requires_flag() -> None:
    should_off, mode_off, _ = should_retrieve(_general_profile(requires_rag=False))
    assert should_off is False
    assert mode_off == "optional"

    should_on, mode_on, _ = should_retrieve(_general_profile(requires_rag=True))
    assert should_on is True
    assert mode_on == "optional"


@pytest.mark.parametrize("factory", [_coding_profile, _math_profile, _creative_profile])
def test_should_retrieve_coding_math_creative_are_off_by_default(factory) -> None:
    should, mode, _ = should_retrieve(factory())
    assert should is False
    assert mode == "off"


@pytest.mark.parametrize("factory", [_coding_profile, _math_profile, _creative_profile])
def test_uncertainty_engine_can_force_retrieval_on_off_routes(factory) -> None:
    should, mode, reason = should_retrieve(factory(), uncertainty_triggered=True)
    assert should is True
    assert mode == "off"
    assert "uncertainty engine" in reason.lower()


# ── RetrievalService.retrieve ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieval_service_skips_when_route_gated_off_and_not_forced() -> None:
    service = RetrievalService(provider=StaticOverrideProvider([_candidate(title="ignored")]))
    result = await service.retrieve(
        RetrievalRequest(query="fix the bug", task_profile=_coding_profile())
    )
    assert result.retrieval_attempted is False
    assert result.sources == []
    assert result.route_gating == "off"
    assert result.retrieval_skipped_reason is not None


@pytest.mark.asyncio
async def test_retrieval_service_runs_for_research_and_returns_ranked_sources() -> None:
    sources = [
        _candidate(title="low", relevance=0.2, credibility=0.2, freshness=0.2, consensus=0.2),
        _candidate(title="high", relevance=0.9, credibility=0.9, freshness=0.9, consensus=0.9),
    ]
    service = RetrievalService(provider=StaticOverrideProvider(sources))
    result = await service.retrieve(
        RetrievalRequest(query="research tradeoffs", task_profile=_research_profile(), limit=5)
    )
    assert result.retrieval_attempted is True
    assert [source.title for source in result.sources] == ["high", "low"]
    assert result.evidence_bump == 2
    assert result.route_gating == "required"
    assert result.weights == DEFAULT_RANKING_WEIGHTS


@pytest.mark.asyncio
async def test_retrieval_service_provider_failure_does_not_raise() -> None:
    class _Boom(RetrievalProvider):
        async def retrieve(self, request: RetrievalRequest):  # type: ignore[override]
            raise RuntimeError("backend unavailable")

    service = RetrievalService(provider=_Boom())
    result = await service.retrieve(
        RetrievalRequest(query="research tradeoffs", task_profile=_research_profile())
    )
    assert result.retrieval_attempted is True
    assert result.sources == []
    assert result.retrieval_skipped_reason is not None
    assert "provider_error" in result.retrieval_skipped_reason
    assert result.telemetry.get("outcome") == "error"
    assert result.telemetry.get("error_type") == "RuntimeError"


@pytest.mark.asyncio
async def test_retrieval_service_uncertainty_trigger_overrides_off_route() -> None:
    service = RetrievalService(provider=StaticOverrideProvider([_candidate(title="forced")]))
    result = await service.retrieve(
        RetrievalRequest(
            query="verify this",
            task_profile=_coding_profile(),
            uncertainty_triggered=True,
        )
    )
    assert result.retrieval_attempted is True
    assert [s.title for s in result.sources] == ["forced"]
    assert result.route_gating == "off"


@pytest.mark.asyncio
async def test_retrieval_service_clamps_overflowing_subscores() -> None:
    bad = SourceCandidate(
        url="https://example.test",
        title="bad",
        excerpt="ok",
        credibility_score=2.0,
        freshness_score=-0.5,
        relevance_score=1.5,
        consensus_score=10.0,
    )
    service = RetrievalService(provider=StaticOverrideProvider([bad]))
    result = await service.retrieve(
        RetrievalRequest(query="research", task_profile=_research_profile())
    )
    assert 0.0 <= result.sources[0].credibility_score <= 1.0
    assert 0.0 <= result.sources[0].freshness_score <= 1.0
    assert 0.0 <= result.sources[0].relevance_score <= 1.0
    assert 0.0 <= result.sources[0].consensus_score <= 1.0
    assert 0.0 <= result.sources[0].final_score <= 1.0


@pytest.mark.asyncio
async def test_retrieval_service_missing_task_profile_returns_disabled() -> None:
    service = RetrievalService(provider=StaticOverrideProvider([_candidate(title="x")]))
    result = await service.retrieve(RetrievalRequest(query="anything", task_profile=None))
    assert result.retrieval_attempted is False
    assert result.sources == []
    assert result.telemetry.get("reason") == "missing_task_profile"


# ── In-memory / deterministic providers ─────────────────────────────────


@pytest.mark.asyncio
async def test_in_memory_provider_returns_records_as_candidates() -> None:
    provider = InMemoryRetrievalProvider(
        records=[
            {
                "url": "https://example.test/a",
                "title": "A",
                "excerpt": "Excerpt A",
                "credibility_score": 0.7,
                "freshness_score": 0.6,
                "relevance_score": 0.9,
                "consensus_score": 0.8,
            },
            {
                "content": "Excerpt B (content key)",
                "credibility_score": 0.4,
                "relevance_score": 0.5,
            },
        ]
    )
    candidates = await provider.retrieve(
        RetrievalRequest(query="research", task_profile=_research_profile())
    )
    assert len(candidates) == 2
    assert candidates[0].excerpt == "Excerpt A"
    assert candidates[1].excerpt == "Excerpt B (content key)"


@pytest.mark.asyncio
async def test_in_memory_provider_defaults_missing_scores_to_zero() -> None:
    provider = InMemoryRetrievalProvider(
        records=[{"excerpt": "no scores supplied"}]
    )
    candidates = await provider.retrieve(
        RetrievalRequest(query="research", task_profile=_research_profile())
    )
    assert candidates[0].credibility_score == 0.0
    assert candidates[0].freshness_score == 0.0
    assert candidates[0].relevance_score == 0.0
    assert candidates[0].consensus_score == 0.0


@pytest.mark.asyncio
async def test_deterministic_provider_returns_empty_list() -> None:
    provider = DeterministicRetrievalProvider()
    candidates = await provider.retrieve(
        RetrievalRequest(query="research", task_profile=_research_profile())
    )
    assert candidates == []


# ── Config loaders ───────────────────────────────────────────────────────


def test_load_routing_weights_falls_back_to_defaults_when_no_config() -> None:
    missing = _scratch_file("missing-routing.json")
    weights = load_routing_weights(config_path=missing)
    assert weights == DEFAULT_RANKING_WEIGHTS


def test_load_routing_weights_reads_repo_routing_defaults_file() -> None:
    weights = load_routing_weights()
    # When the repo routing_defaults.json lacks a retrieval block, the
    # loader returns the default weights unchanged.
    assert set(weights.keys()) == set(DEFAULT_RANKING_WEIGHTS.keys())
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_load_routing_weights_honors_env_json_override() -> None:
    payload = json.dumps({"relevance": 0.5, "credibility": 0.2, "freshness": 0.2, "consensus": 0.1})
    weights = load_routing_weights(
        config_path=_scratch_file("missing.json"),
        env={"CALIENNE_RETRIEVAL_WEIGHTS_JSON": payload},
    )
    expected = {"relevance": 0.5, "credibility": 0.2, "freshness": 0.2, "consensus": 0.1}
    assert weights == pytest.approx(expected)


def test_load_routing_weights_normalizes_misbalanced_weights() -> None:
    payload = json.dumps({"relevance": 0.8, "credibility": 0.8, "freshness": 0.4, "consensus": 0.0})
    weights = load_routing_weights(
        config_path=_scratch_file("missing.json"),
        env={"CALIENNE_RETRIEVAL_WEIGHTS_JSON": payload},
    )
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_load_routing_weights_invalid_env_falls_back_to_defaults() -> None:
    weights = load_routing_weights(
        config_path=_scratch_file("missing.json"),
        env={"CALIENNE_RETRIEVAL_WEIGHTS_JSON": "{not-json"},
    )
    assert weights == DEFAULT_RANKING_WEIGHTS


def test_load_routing_weights_reads_path_override() -> None:
    override = _scratch_file("weights.json")
    override.write_text(
        json.dumps({"retrieval": {"source_ranking_weights": {"relevance": 0.7, "credibility": 0.1, "freshness": 0.1, "consensus": 0.1}}}),  # noqa: E501
        encoding="utf-8",
    )
    weights = load_routing_weights(
        config_path=_scratch_file("missing.json"),
        env={"CALIENNE_RETRIEVAL_WEIGHTS_PATH": str(override)},
    )
    assert weights["relevance"] == pytest.approx(0.7)


def test_load_route_gating_falls_back_to_defaults_when_missing() -> None:
    gating = load_route_gating(config_path=_scratch_file("missing-route.json"))
    assert gating == ROUTE_GATING


def test_load_route_gating_reads_repo_file() -> None:
    gating = load_route_gating()
    # Repo file currently has no retrieval block, so gating should
    # exactly match the module defaults.
    assert gating["research"] == "required"
    assert gating["general"] == "optional"
    assert gating["coding"] == "off"


# ── Schema invariants ────────────────────────────────────────────────────


def test_source_candidate_inherits_extra_ignore_policy() -> None:
    candidate = _candidate()
    payload = candidate.model_dump()
    assert "excerpt" in payload
    assert payload["credibility_score"] == pytest.approx(0.5)


def test_retrieval_result_default_state_is_empty() -> None:
    result = RetrievalResult()
    assert result.sources == []
    assert result.selected_count == 0
    assert result.retrieval_attempted is False
    assert result.weights == {}


# ── Async-safety smoke test ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieval_service_is_awaitable_from_event_loop() -> None:
    service = RetrievalService(provider=StaticOverrideProvider([_candidate(title="x")]))
    coros = [
        service.retrieve(RetrievalRequest(query=f"q{i}", task_profile=_research_profile()))
        for i in range(5)
    ]
    results = await asyncio.gather(*coros)
    assert len(results) == 5
    assert all(r.retrieval_attempted for r in results)
