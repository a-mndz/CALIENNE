"""Regression tests for the honest-metrics fixes (audit 2026-10-01).

Covers:
- Per-role sampling temperatures (creative diverges, judge/breaker don't).
- Retry classification: permanent failures are not retried; transient ones
  are; no sleep jitter before the first attempt.
- max_tokens pass-through on the judge's primary execution path.
- Provider usage recorded on the passport and surfaced as measured tokens.
- Consensus gating: flag-off (default) means no consensus dispatch.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from api_gateway.client import ROLE_TEMPERATURES, _resolve_temperature
from api_gateway.rate_limiter import _is_retryable
from core.passport import ExecutionPassport
from orchestrator.decisions import _consensus_enabled

pytestmark = pytest.mark.unit


# ── Per-role temperature ────────────────────────────────────────────────


def test_role_temperatures_diverge() -> None:
    """Creative must sample hotter than judge/breaker — identical
    temperatures made the diversity signal meaningless."""
    assert ROLE_TEMPERATURES["creative"] > ROLE_TEMPERATURES["judge"]
    assert ROLE_TEMPERATURES["creative"] > ROLE_TEMPERATURES["logician"]
    assert ROLE_TEMPERATURES["judge"] <= 0.1
    assert ROLE_TEMPERATURES["breaker"] == 0.0


def test_unknown_role_uses_default_temperature() -> None:
    assert _resolve_temperature("nonexistent-role") == _resolve_temperature(None)


# ── Retry classification ────────────────────────────────────────────────


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://provider.invalid/v1")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)


@pytest.mark.parametrize(
    "exc,expected",
    [
        (httpx.TimeoutException("boom"), True),
        (httpx.NetworkError("unreachable"), True),
        (_http_status_error(429), True),
        (_http_status_error(503), True),
        (_http_status_error(401), False),
        (_http_status_error(400), False),
        (_http_status_error(413), False),
        (RuntimeError("deterministic failure"), False),
    ],
)
def test_is_retryable_classification(exc: Exception, expected: bool) -> None:
    assert _is_retryable(exc) is expected


@pytest.mark.asyncio
async def test_guarded_call_does_not_retry_permanent_failure() -> None:
    """A 401 must surface immediately — one call, not three."""
    from api_gateway.rate_limiter import AsyncAPIGateway

    gateway = AsyncAPIGateway(client=MagicMock())
    gateway._client.post_request = AsyncMock(side_effect=_http_status_error(401))

    with pytest.raises(httpx.HTTPStatusError):
        await gateway._guarded_call("prov/model", "prompt")

    assert gateway._client.post_request.await_count == 1


@pytest.mark.asyncio
async def test_guarded_call_no_sleep_before_first_attempt(monkeypatch) -> None:
    """The first attempt must fire immediately — no jitter preamble."""
    from api_gateway.rate_limiter import AsyncAPIGateway

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("api_gateway.rate_limiter.asyncio.sleep", _fake_sleep)

    gateway = AsyncAPIGateway(client=MagicMock())
    gateway._client.post_request = AsyncMock(return_value="ok")

    result = await gateway._guarded_call("prov/model", "prompt")
    assert result == "ok"
    assert sleeps == []


@pytest.mark.asyncio
async def test_guarded_call_retries_retryable_failure(monkeypatch) -> None:
    """A 429 must be retried with backoff — disabling all retries silently
    would otherwise pass the suite (only the no-retry direction was covered)."""
    from api_gateway.rate_limiter import AsyncAPIGateway

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("api_gateway.rate_limiter.asyncio.sleep", _fake_sleep)

    gateway = AsyncAPIGateway(client=MagicMock())
    gateway._client.post_request = AsyncMock(
        side_effect=[_http_status_error(429), _http_status_error(503), "recovered"]
    )

    result = await gateway._guarded_call("prov/model", "prompt")
    assert result == "recovered"
    assert gateway._client.post_request.await_count == 3
    assert len(sleeps) == 2  # backoff between attempts 1->2 and 2->3


@pytest.mark.asyncio
async def test_provider_usage_flows_to_passport_and_metrics() -> None:
    """Integration: post_request sets the usage ContextVar; execute_with_fallback
    records it on the passport; execute_with_contracts surfaces measured tokens."""
    from api_gateway.client import _last_provider_usage
    from api_gateway.rate_limiter import AsyncAPIGateway
    from api_gateway.strategy import ProviderStrategy
    from core.runtime import RuntimeEngine

    usage_block = {
        "model": "prov/model",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "latency_s": 0.2,
        "success": True,
        "estimated": False,
    }

    async def _post_with_usage(*args, **kwargs):
        _last_provider_usage.set(usage_block)
        return "answer"

    gateway = AsyncAPIGateway(client=MagicMock())
    gateway._client.post_request = AsyncMock(side_effect=_post_with_usage)

    strategy = ProviderStrategy(mode="FREE")
    strategy.get_model_chain = lambda role: ["prov/model"]  # single-model chain
    pool = MagicMock()
    pool.is_provider_healthy.return_value = True
    pool.report_success.return_value = None

    engine = RuntimeEngine()
    passport = ExecutionPassport()
    await engine.execute_with_contracts(
        prompt="hello world",
        system_prompt="system",
        role="judge",
        passport=passport,
        gateway=gateway,
        strategy=strategy,
        pool=pool,
    )

    assert passport.get_provider_usage("judge")["prompt_tokens"] == 100
    metrics = engine._metrics[("judge", "prov")]
    assert metrics.total_tokens == 150  # measured, not the len//4 estimate


# ── max_tokens pass-through ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_with_contracts_passes_max_tokens() -> None:
    """The judge path must be able to raise the output ceiling: providers'
    default caps truncated live judge JSON mid-final_answer (2026-08-22)."""
    from core.runtime import RuntimeEngine

    engine = RuntimeEngine()
    passport = ExecutionPassport()
    gateway = MagicMock()
    gateway.execute_with_fallback = AsyncMock(return_value="ok")

    await engine.execute_with_contracts(
        prompt="p",
        system_prompt="s",
        role="judge",
        passport=passport,
        gateway=gateway,
        strategy=MagicMock(),
        pool=MagicMock(),
        max_tokens=8192,
    )

    _, kwargs = gateway.execute_with_fallback.await_args
    assert kwargs["max_tokens"] == 8192


# ── Token accounting ────────────────────────────────────────────────────


def test_passport_provider_usage_roundtrip() -> None:
    passport = ExecutionPassport()
    assert passport.get_provider_usage("judge") is None

    passport.record_provider_usage(
        "judge", {"prompt_tokens": 100, "completion_tokens": 50, "estimated": False}
    )
    usage = passport.get_provider_usage("judge")
    assert usage is not None
    assert usage["prompt_tokens"] == 100
    assert usage["completion_tokens"] == 50

    # Malformed input is ignored, not crashed on.
    passport.record_provider_usage("logician", None)  # type: ignore[arg-type]
    assert passport.get_provider_usage("logician") is None


def test_passport_recorded_tokens_reach_metrics() -> None:
    from core.runtime import RuntimeEngine

    engine = RuntimeEngine()
    engine.track_execution_metrics(
        agent="judge", provider="prov", latency_ms=10.0, tokens=150, success=True
    )
    metrics = engine._metrics[("judge", "prov")]
    assert metrics.total_tokens == 150


# ── Consensus gating ────────────────────────────────────────────────────


def test_consensus_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("CALIENNE_ENABLE_CONSENSUS", raising=False)
    assert _consensus_enabled() is False


def test_consensus_enabled_by_flag(monkeypatch) -> None:
    monkeypatch.setenv("CALIENNE_ENABLE_CONSENSUS", "1")
    assert _consensus_enabled() is True
