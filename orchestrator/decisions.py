"""
calienne — Adaptive Multi-Model Reasoning Orchestrator
Decision Engine facade: Breaker → Logician/Creative → Judge gate architecture.

God-object decomposition (ISSUES_AND_FIXES CRITICAL item, 2026-08-22): the
single-responsibility pieces now live in their own modules and this class is
the thin orchestrating facade CRIT-001 requires to stay the sole decision path —

- ``orchestrator/breaker_gate.py``     — knowledge-absence pre-filter
- ``orchestrator/generation_runner.py`` — Logician/Creative execution strategies
- ``orchestrator/decision_support.py``  — metrics collector, task safety, dispatch

Timing specifications (from Requirement 9):
- Breaker timeout: CALIENNE_BREAKER_TIMEOUT_MS (default 100ms — simulation;
  live round-trips need ~5-8s); fails OPEN on expiry.
- Parallel agent timeout: 30 seconds
- Conditional threshold: 0.7 (Creative runs only if Logician < 0.7)
- Judge agreement threshold: validation_score >= 7.0
- Rolling metrics window: 100 executions
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from api_gateway.rate_limiter import AsyncAPIGateway, ProviderPool
from api_gateway.strategy import ProviderStrategy
from core.passport import ExecutionPassport
from core.schemas import AgentOutput, calienneOutput
from orchestrator.breaker_gate import BreakerGate
from orchestrator.decision_support import (  # noqa: F401  (re-export)
    DecisionMetrics,
    DecisionMetricsCollector,
    DecisionStrategy,
    safe_create_task_broadcast,
)
from orchestrator.evaluation import arbitrate_and_synthesize
from orchestrator.generation_runner import GenerationRunner
from orchestrator.streaming import EventType, StreamEvent

logger = logging.getLogger(__name__)


class DecisionEngine:
    """Orchestrating facade over BreakerGate + GenerationRunner + judge call.

    Public surface is unchanged from the pre-decomposition engine: the same
    three ``execute_*`` methods, the same metrics attributes, the same
    constants — so callers (pipelines.py, ExecutionManager, tests) are
    untouched.
    """

    # ── Timing Constants (kept for API compatibility; owned by the parts) ──
    BREAKER_TIMEOUT_MS: int = 100
    KNOWLEDGE_ABSENCE_THRESHOLD: float = 0.3
    KNOWLEDGE_ABSENCE_SENTINEL: str = "KNOWLEDGE ABSENCE DETECTED"
    ABORT_DELAY_MS: int = 10
    PARALLEL_AGENT_TIMEOUT_SEC: int = 30
    CONDITIONAL_CONFIDENCE_THRESHOLD: float = 0.7
    JUDGE_AGREEMENT_THRESHOLD: float = 7.0
    METRICS_WINDOW_SIZE: int = 100

    def __init__(
        self,
        strategy: DecisionStrategy = DecisionStrategy.PARALLEL,
        streaming_manager: Any = None,
        runtime_engine: Any = None,
    ) -> None:
        self.strategy = strategy
        self.streaming_manager = streaming_manager
        # HIGH-009: When supplied, agent execution funnels through the
        # RuntimeEngine.execute_with_contracts path which enforces security,
        # rate-limiting, and metrics tracking on every provider call.
        self.runtime_engine = runtime_engine

        self._metrics_collector = DecisionMetricsCollector(window_size=self.METRICS_WINDOW_SIZE)
        self.metrics = self._metrics_collector.metrics

        self._breaker = BreakerGate(
            runtime_engine=runtime_engine,
            streaming_manager=streaming_manager,
        )
        # Live round-trips cannot fit the 100ms simulation-era default; the
        # budget is configurable without touching the class contract.
        try:
            from core.config import get_settings

            self.BREAKER_TIMEOUT_MS = int(get_settings().BREAKER_TIMEOUT_MS)
        except Exception:  # pragma: no cover - settings unavailable in tests
            pass
        self._breaker.BREAKER_TIMEOUT_MS = self.BREAKER_TIMEOUT_MS

        self._generation = GenerationRunner(
            strategy=strategy,
            runtime_engine=runtime_engine,
            streaming_manager=streaming_manager,
        )

    # Rolling-window history attributes, backed by the collector so external
    # readers (and any stragglers appending directly) keep working.
    @property
    def _breaker_history(self):
        return self._metrics_collector.breaker_history

    @property
    def _judge_history(self):
        return self._metrics_collector.judge_history

    @property
    def _synthesis_scores(self):
        return self._metrics_collector.synthesis_scores

    # ── Public API ────────────────────────────────────────────────────

    async def execute_breaker_gate(
        self,
        query: str,
        gateway: AsyncAPIGateway,
        strategy: ProviderStrategy,
        pool: ProviderPool,
        passport: ExecutionPassport,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[bool, AgentOutput | None]:
        """Delegate to the BreakerGate and record the outcome.

        Returns ``(should_continue, breaker_output)``. Fails OPEN on timeout
        or error (see BreakerGate docstring).
        """
        should_continue, breaker_output = await self._breaker.execute(
            query, gateway, strategy, pool, passport, history
        )
        self._breaker_history.append(should_continue)
        return should_continue, breaker_output

    async def execute_generation_agents(
        self,
        query: str,
        gateway: AsyncAPIGateway,
        strategy: ProviderStrategy,
        pool: ProviderPool,
        passport: ExecutionPassport,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[Optional[AgentOutput], Optional[AgentOutput]]:
        """Delegate to the GenerationRunner (30-second budget).

        Returns ``(logician_output, creative_output)`` where ``None``
        indicates a failed agent. Partial failures degrade to one output.
        """
        return await self._generation.execute(query, gateway, strategy, pool, passport, history)

    async def execute_judge_synthesis(
        self,
        query: str,
        logician_output: Optional[AgentOutput],
        creative_output: Optional[AgentOutput],
        gateway: AsyncAPIGateway,
        strategy: ProviderStrategy,
        pool: ProviderPool,
        passport: ExecutionPassport,
        lessons: str = "",
        history: list[dict[str, str]] | None = None,
    ) -> calienneOutput:
        """
        Execute the Judge agent to synthesize outputs.

        Failed agents receive placeholders with ``confidence=0.0``.
        Tracks ``_judge_history`` and ``_synthesis_scores``.
        """
        if logician_output is None:
            logician_output = AgentOutput(
                reasoning_steps=["[Agent execution failed]"],
                answer="[Logician output unavailable due to execution failure]",
                confidence=0.0,
            )
        if creative_output is None:
            creative_output = AgentOutput(
                reasoning_steps=["[Agent execution failed]"],
                answer="[Creative output unavailable due to execution failure]",
                confidence=0.0,
            )

        judge_output = await arbitrate_and_synthesize(
            query=query,
            answer_a=logician_output.answer,
            answer_b=creative_output.answer,
            gateway=gateway,
            strategy=strategy,
            pool=pool,
            lessons=lessons,
            history=history,
        )

        if isinstance(judge_output, dict):
            # Parse failure — wrap in a safe calienneOutput
            logger.error("Judge returned raw dict, wrapping: %s", judge_output)
            judge_output = calienneOutput(
                final_answer=judge_output.get("final_answer", "Judge synthesis failed"),
                overall_confidence="Low",
                overall_bias_risk="High",
                disagreement_notes=["Judge output was not a valid calienneOutput"],
                validation_score=0.0,
            )

        # Track metrics
        self._judge_history.append(
            judge_output.validation_score >= self.JUDGE_AGREEMENT_THRESHOLD
        )
        self._synthesis_scores.append(judge_output.validation_score)

        logger.info(
            "Judge synthesis complete — validation_score=%.2f, confidence=%s",
            judge_output.validation_score,
            judge_output.overall_confidence,
            extra={"stage": "judge", "score": judge_output.validation_score, "confidence": judge_output.overall_confidence}  # noqa: E501
        )

        if self.streaming_manager:
            safe_create_task_broadcast(
                self.streaming_manager.emit_event(
                    request_id=passport.request_id,
                    event=StreamEvent(
                        event=EventType.JUDGE_SYNTHESIZED,
                        data={"score": judge_output.validation_score, "confidence": judge_output.overall_confidence}  # noqa: E501
                    )
                ),
                name="judge-synthesized-broadcast",
            )

        return judge_output

    def update_metrics(self) -> None:
        """Recalculate metrics from the rolling windows."""
        self._metrics_collector.update()

    def get_metrics(self) -> DecisionMetrics:
        """Return current decision metrics calculated over rolling window."""
        return self._metrics_collector.update()

    # ── Private delegates (kept: tests exercise the wrappers directly) ──

    def _execute_breaker(self, *args: Any, **kwargs: Any) -> Any:
        return self._breaker._execute(*args, **kwargs)

    def _execute_logician(self, *args: Any, **kwargs: Any) -> Any:
        return self._generation._execute_logician(*args, **kwargs)

    def _execute_creative(self, *args: Any, **kwargs: Any) -> Any:
        return self._generation._execute_creative(*args, **kwargs)

    def _dispatch_provider_call(self, *args: Any, **kwargs: Any) -> Any:
        from orchestrator.decision_support import dispatch_provider_call

        return dispatch_provider_call(self.runtime_engine, *args, **kwargs)
