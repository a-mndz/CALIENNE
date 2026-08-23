"""Stage 2 regression tests — every reported number traces to a measurement.

Covers the remediation-plan Stage 2 fixes:

- Provider latency recorded into the pool's rolling metrics (mean_latency_ms
  was structurally 0, which is what made the UI's "1.1s" fallback permanent).
- DAG validation score derived from the measured supported-claim ratio, not
  the old hardcoded 7.5/9.0 constants.
- Cost estimation from the refreshed pricing table (substring match order:
  gpt-4o-mini must win over gpt-4o).
- Usage contextvar defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from api_gateway.client import get_last_provider_usage
from api_gateway.rate_limiter import ProviderPool
from orchestrator.validation_layer import ValidationLayer
from telemetry.observer import estimate_cost_usd

# ── Pool latency metrics ─────────────────────────────────────────────────


class TestPoolLatencyRecording:
    def test_report_success_without_latency_leaves_mean_zero(self) -> None:
        pool = ProviderPool()
        pool.register_provider("groq")
        pool.report_success("groq")
        metrics = pool.get_health_metrics("groq")
        assert metrics is not None
        assert metrics.mean_latency_ms == 0.0

    def test_report_success_with_latency_feeds_mean(self) -> None:
        pool = ProviderPool()
        pool.register_provider("groq")
        pool.report_success("groq", latency_ms=250.0)
        pool.report_success("groq", latency_ms=350.0)
        metrics = pool.get_health_metrics("groq")
        assert metrics is not None
        assert metrics.mean_latency_ms == 300.0

    def test_zero_latency_not_recorded_as_measurement(self) -> None:
        pool = ProviderPool()
        pool.register_provider("openai")
        pool.report_success("openai", latency_ms=0.0)
        assert pool.get_health_metrics("openai").mean_latency_ms == 0.0


# ── Usage contextvar ─────────────────────────────────────────────────────


def test_last_provider_usage_defaults_to_none() -> None:
    assert get_last_provider_usage() is None


# ── DAG validation score from measured support ratio ─────────────────────


@dataclass
class _FakeEnum:
    value: str = "factual"


@dataclass
class _FakeClaim:
    content: str = "claim"
    claim_id: str = "c1"
    claim_type: Any = field(default_factory=_FakeEnum)
    confidence: float = 0.5
    source_agent: str = "final"
    validation_status: Any = field(default_factory=_FakeEnum)
    provenance: dict = field(default_factory=dict)


@dataclass
class _FakeFirewall:
    original_text: str = "original"
    sanitized_text: str = "sanitized"
    removed_or_qualified_count: int = 0
    claims: list[Any] = field(default_factory=list)


class _StubClaimManager:
    """Deterministic claim manager: first `unsupported_count` claims fail."""

    def __init__(self, total: int, unsupported_count: int) -> None:
        self._claims = [_FakeClaim(content=f"claim {i}") for i in range(total)]
        self._unsupported_count = unsupported_count

    def build_evidence(self, **_kwargs: Any) -> list[Any]:
        return []

    def apply_firewall(self, text: str, **_kwargs: Any) -> _FakeFirewall:
        return _FakeFirewall(
            sanitized_text=text,
            removed_or_qualified_count=self._unsupported_count,
            claims=list(self._claims),
        )

    def get_unverified_claims(self, claims: list[Any]) -> list[Any]:
        return claims[: self._unsupported_count]


def _dag_output(total: int, unsupported: int) -> Any:
    from core.schemas import TaskProfile

    layer = ValidationLayer(_StubClaimManager(total, unsupported))
    output, _firewall = layer.validate_dag_output(
        user_query="q",
        history=None,
        task_profile=TaskProfile(),
        strategic_plan=None,
        results={"final": {"final_response": "text"}},
    )
    return output


class TestDagValidationScoreMeasured:
    def test_all_supported_scores_full(self) -> None:
        output = _dag_output(total=4, unsupported=0)
        assert output.validation_score == 10.0
        assert output.overall_confidence == "High"

    def test_half_supported_scores_five(self) -> None:
        output = _dag_output(total=2, unsupported=1)
        assert output.validation_score == 5.0
        assert output.overall_confidence == "Medium"

    def test_minority_supported_scores_low_confidence(self) -> None:
        output = _dag_output(total=4, unsupported=3)
        assert output.validation_score == 2.5
        assert output.overall_confidence == "Low"

    def test_no_claims_is_labelled_vacuous(self) -> None:
        output = _dag_output(total=0, unsupported=0)
        assert output.validation_score == 10.0
        assert any("vacuous" in note.lower() for note in output.disagreement_notes)

    def test_score_is_never_the_old_constants(self) -> None:
        # The old fabrication was exactly 7.5 (unsupported) / 9.0 (supported).
        # A 1-of-3-unsupported ratio must not collide with either constant
        # except by genuine arithmetic.
        output = _dag_output(total=3, unsupported=1)
        assert output.validation_score == round(10.0 * 2 / 3, 1)


# ── Cost estimation from refreshed pricing ───────────────────────────────


class TestCostEstimation:
    def test_gpt_4o_mini_wins_over_gpt_4o_substring(self) -> None:
        # "gpt-4o" is a substring of "gpt-4o-mini"; the mini card must match.
        cost = estimate_cost_usd("openai/gpt-4o-mini", 1_000_000, 1_000_000)
        assert cost == 0.15 + 0.60

    def test_claude_sonnet_5_verified_rate(self) -> None:
        cost = estimate_cost_usd("anthropic/claude-sonnet-5", 1_000_000, 0)
        assert cost == 2.00

    def test_gemini_flash_verified_rate(self) -> None:
        cost = estimate_cost_usd("google/gemini-3.5-flash-lite", 1_000_000, 1_000_000)
        assert cost == 0.30 + 2.50

    def test_gpt_oss_120b_groq_rate(self) -> None:
        cost = estimate_cost_usd("openai/gpt-oss-120b", 1_000_000, 1_000_000)
        assert cost == 0.15 + 0.60

    def test_unknown_model_uses_default_card(self) -> None:
        cost = estimate_cost_usd("totally-unknown-model", 1_000_000, 1_000_000)
        assert cost == 0.10 + 0.20
