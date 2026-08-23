"""Prometheus exposition for CALIENNE runtime metrics.

The numbers already exist — ``DecisionEngine`` keeps 100-entry rolling windows
(``decisions.py``) and ``ProviderPool`` tracks per-provider health
(``api_gateway/rate_limiter.py``). This module only *exports* them; it computes
nothing and owns no state beyond the Gauge objects themselves.

Design note — pull, not push: the collectors are refreshed from the live objects
at scrape time by :func:`refresh`, so the hot request path stays free of metric
writes. ``/metrics`` in ``server.py`` calls ``refresh()`` then ``render()``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

try:
    from prometheus_client import CollectorRegistry, Gauge, generate_latest

    PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover - declared dependency
    PROMETHEUS_AVAILABLE = False

# A private registry keeps CALIENNE series out of the process-global default,
# so importing this module twice (or under pytest) cannot raise "Duplicated
# timeseries" and a scrape returns only our metrics.
if PROMETHEUS_AVAILABLE:
    REGISTRY = CollectorRegistry()

    BREAKER_PASS_RATE = Gauge(
        "calienne_breaker_pass_rate",
        "Fraction of the last 100 requests the breaker gate let through.",
        registry=REGISTRY,
    )
    JUDGE_AGREEMENT_RATE = Gauge(
        "calienne_judge_agreement_rate",
        "Fraction of the last 100 judgements scoring at or above the agreement threshold.",
        registry=REGISTRY,
    )
    SYNTHESIS_QUALITY_AVG = Gauge(
        "calienne_synthesis_quality_avg",
        "Mean judge validation score (0-10) over the last 100 syntheses.",
        registry=REGISTRY,
    )
    TOTAL_DECISIONS = Gauge(
        "calienne_total_decisions",
        "Decisions executed since process start.",
        registry=REGISTRY,
    )
    PROVIDER_HEALTH = Gauge(
        "calienne_provider_health",
        "1 when the provider is in this status, 0 otherwise.",
        ["provider", "status"],
        registry=REGISTRY,
    )
    PROVIDER_CONSECUTIVE_FAILURES = Gauge(
        "calienne_provider_consecutive_failures",
        "Consecutive failures on a provider; the circuit breaker trips at 3.",
        ["provider"],
        registry=REGISTRY,
    )
    PROVIDER_AVAILABLE = Gauge(
        "calienne_provider_available",
        "1 when the provider is currently eligible for routing, 0 otherwise.",
        ["provider"],
        registry=REGISTRY,
    )

# Every status a provider can report, so the series that do *not* apply are
# emitted as 0 rather than vanishing. A disappearing series looks identical to a
# dead scrape target in Prometheus, which makes `status="dead"` alerts unfireable.
_ALL_STATUSES = ("healthy", "degraded", "dead")


def refresh(
    decision_engine: Any | None = None,
    pool: Any | None = None,
) -> None:
    """Pull current values out of the live objects into the Gauges.

    Both arguments are optional and independently skippable — a scrape during
    startup, before ``lifespan`` has built the components, reports the metrics it
    can and leaves the rest at their previous values instead of erroring.
    """
    if not PROMETHEUS_AVAILABLE:
        return

    if decision_engine is not None:
        try:
            metrics = decision_engine.get_metrics()
            BREAKER_PASS_RATE.set(metrics.breaker_pass_rate)
            JUDGE_AGREEMENT_RATE.set(metrics.judge_agreement_rate)
            SYNTHESIS_QUALITY_AVG.set(metrics.synthesis_quality_avg)
            TOTAL_DECISIONS.set(metrics.total_decisions)
        except Exception as exc:  # noqa: BLE001
            # A scrape must never take down the endpoint it is scraping.
            logger.warning("Decision metrics refresh failed: %s", exc)

    if pool is not None:
        try:
            for status_dict in pool.get_all_statuses():
                if not status_dict:
                    continue
                name = status_dict["provider"]
                current = status_dict["status"]
                for status in _ALL_STATUSES:
                    PROVIDER_HEALTH.labels(provider=name, status=status).set(
                        1 if status == current else 0
                    )
                PROVIDER_CONSECUTIVE_FAILURES.labels(provider=name).set(
                    status_dict.get("consecutive_failures", 0)
                )
                PROVIDER_AVAILABLE.labels(provider=name).set(
                    1 if status_dict.get("is_available") else 0
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Provider health refresh failed: %s", exc)


def render() -> bytes:
    """Serialise the registry in Prometheus text exposition format."""
    if not PROMETHEUS_AVAILABLE:
        return b"# prometheus_client is not installed\n"
    return generate_latest(REGISTRY)


def demo() -> None:
    """Self-check: fake a decision engine and pool, assert the series render."""
    assert PROMETHEUS_AVAILABLE, "prometheus_client missing — it is in requirements.txt"

    class _Metrics:
        breaker_pass_rate = 0.92
        judge_agreement_rate = 0.75
        synthesis_quality_avg = 8.25
        total_decisions = 143

    class _Engine:
        def get_metrics(self) -> _Metrics:
            return _Metrics()

    class _Pool:
        def get_all_statuses(self) -> list[dict]:
            return [
                {
                    "provider": "groq/llama3",
                    "status": "healthy",
                    "consecutive_failures": 0,
                    "is_available": True,
                },
                {
                    "provider": "openrouter/gpt-4o",
                    "status": "dead",
                    "consecutive_failures": 3,
                    "is_available": False,
                },
                None,  # get_status returns None for unknown names
            ]

    refresh(decision_engine=_Engine(), pool=_Pool())
    text = render().decode()

    assert "calienne_breaker_pass_rate 0.92" in text
    assert "calienne_synthesis_quality_avg 8.25" in text
    assert "calienne_total_decisions 143.0" in text
    # The live status reads 1 and every other status is present at 0, so a
    # `status="dead"` alert has a series to evaluate even while healthy.
    assert 'calienne_provider_health{provider="groq/llama3",status="healthy"} 1.0' in text
    assert 'calienne_provider_health{provider="groq/llama3",status="dead"} 0.0' in text
    assert 'calienne_provider_health{provider="openrouter/gpt-4o",status="dead"} 1.0' in text
    assert 'calienne_provider_available{provider="openrouter/gpt-4o"} 0.0' in text
    assert 'calienne_provider_consecutive_failures{provider="openrouter/gpt-4o"} 3.0' in text

    # Missing components must degrade, not raise.
    refresh(decision_engine=None, pool=None)

    class _Broken:
        def get_metrics(self) -> None:
            raise RuntimeError("engine exploded")

    refresh(decision_engine=_Broken(), pool=None)
    assert "calienne_breaker_pass_rate 0.92" in render().decode()

    print("orchestrator/metrics.py OK")


if __name__ == "__main__":
    demo()
