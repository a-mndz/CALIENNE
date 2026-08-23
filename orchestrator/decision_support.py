"""Shared support for the decision layer: task safety, strategy enum, metrics.

Extracted from decisions.py (god-object decomposition, ISSUES_AND_FIXES
CRITICAL item): everything here is pure infrastructure with no pipeline
knowledge, so it can be tested and reused without the DecisionEngine.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable

from api_gateway.rate_limiter import AsyncAPIGateway, ProviderPool
from api_gateway.strategy import ProviderStrategy
from core.passport import ExecutionPassport

logger = logging.getLogger(__name__)

METRICS_WINDOW_SIZE: int = 100


def _log_task_exception(context: str) -> "callable":
    """Return an ``add_done_callback`` that logs exceptions from fire-and-forget tasks."""

    def _callback(task: asyncio.Task) -> None:
        if task.cancelled():
            logger.debug("Streaming task cancelled: %s", context)
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "Streaming task failed: %s — %s: %s",
                context,
                type(exc).__name__,
                exc,
                exc_info=exc,
            )

    return _callback


def safe_create_task_broadcast(
    coro: Awaitable[Any],
    *,
    name: str = "broadcast",
) -> asyncio.Task:
    """Schedule ``coro`` with an error-logging ``add_done_callback``.

    HIGH-011 audit finding: ``asyncio.create_task`` calls in DecisionEngine
    streaming paths silently swallowed exceptions, masking pipeline
    regressions in production.  This wrapper attaches a logging callback
    while preserving the original fire-and-forget semantics.
    """
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(_log_task_exception(name))
    return task


class DecisionStrategy(str, Enum):
    """Decision gate execution strategies."""

    PARALLEL = "parallel"  # Logician and Creative run concurrently
    SEQUENTIAL = "sequential"  # Logician runs first, Creative only if needed
    CONDITIONAL = "conditional"  # Creative only if Logician confidence < 0.7


@dataclass
class DecisionMetrics:
    """Rolling-window metrics for the decision engine."""

    breaker_pass_rate: float = 0.0
    judge_agreement_rate: float = 0.0
    synthesis_quality_avg: float = 0.0
    total_decisions: int = 0


@dataclass
class DecisionMetricsCollector:
    """Owns the rolling windows and derives DecisionMetrics from them."""

    window_size: int = METRICS_WINDOW_SIZE
    metrics: DecisionMetrics = field(default_factory=DecisionMetrics)
    breaker_history: deque = field(default_factory=lambda: deque(maxlen=METRICS_WINDOW_SIZE))
    judge_history: deque = field(default_factory=lambda: deque(maxlen=METRICS_WINDOW_SIZE))
    synthesis_scores: deque = field(default_factory=lambda: deque(maxlen=METRICS_WINDOW_SIZE))

    def __post_init__(self) -> None:
        self.breaker_history = deque(maxlen=self.window_size)
        self.judge_history = deque(maxlen=self.window_size)
        self.synthesis_scores = deque(maxlen=self.window_size)

    def update(self) -> DecisionMetrics:
        """Recalculate metrics from the rolling windows."""
        if len(self.breaker_history) > 0:
            self.metrics.breaker_pass_rate = sum(self.breaker_history) / len(self.breaker_history)
        if len(self.judge_history) > 0:
            self.metrics.judge_agreement_rate = sum(self.judge_history) / len(self.judge_history)
        if len(self.synthesis_scores) > 0:
            self.metrics.synthesis_quality_avg = (
                sum(self.synthesis_scores) / len(self.synthesis_scores)
            )
        self.metrics.total_decisions = len(self.breaker_history)
        return self.metrics


async def dispatch_provider_call(
    runtime_engine: Any,
    *,
    prompt: str,
    system_prompt: str,
    role: str,
    gateway: AsyncAPIGateway,
    strategy: ProviderStrategy,
    pool: ProviderPool,
    passport: ExecutionPassport,
    history: list[dict[str, str]] | None,
) -> str:
    """HIGH-009 — route provider call through RuntimeEngine when configured.

    When ``runtime_engine`` is supplied, every provider call is wrapped in
    ``RuntimeEngine.execute_with_contracts`` so that security validation,
    streaming events, rate limiting, and per-agent metrics are enforced.
    When no runtime engine is provided we fall back to the historical
    direct ``gateway.execute_with_fallback`` path so callers that do not
    opt in still function.
    """
    if runtime_engine is not None:
        return await runtime_engine.execute_with_contracts(
            prompt=prompt,
            system_prompt=system_prompt,
            role=role,
            passport=passport,
            gateway=gateway,
            strategy=strategy,
            pool=pool,
            history=history,
        )
    return await gateway.execute_with_fallback(
        prompt=prompt,
        system_prompt=system_prompt,
        role=role,
        strategy=strategy,
        pool=pool,
        history=history,
    )
