"""Generation execution: Logician + Creative under three dispatch strategies.

Extracted from decisions.py (god-object decomposition). Owns the agent
wrappers, the provider dispatch, and the PARALLEL / SEQUENTIAL /
CONDITIONAL strategies. Partial failures are handled: one agent failing
degrades to the other's output; both failing returns ``(None, None)``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

from agents.parser import parse_and_repair
from agents.prompt_utils import (
    assemble_creative_prompt,
    assemble_logician_prompt,
    safe_parse_agent_output,
)
from api_gateway.rate_limiter import AsyncAPIGateway, ProviderPool
from api_gateway.strategy import ProviderStrategy
from core.error_handlers import execute_with_passport_logging
from core.passport import ExecutionPassport
from core.schemas import AgentOutput
from orchestrator.decision_support import (
    DecisionStrategy,
    dispatch_provider_call,
    safe_create_task_broadcast,
)
from orchestrator.streaming import EventType, StreamEvent

logger = logging.getLogger(__name__)


class GenerationRunner:
    PARALLEL_AGENT_TIMEOUT_SEC: int = 30
    CONDITIONAL_CONFIDENCE_THRESHOLD: float = 0.7

    def __init__(
        self,
        strategy: DecisionStrategy = DecisionStrategy.PARALLEL,
        runtime_engine: Any = None,
        streaming_manager: Any = None,
    ) -> None:
        self.strategy = strategy
        self.runtime_engine = runtime_engine
        self.streaming_manager = streaming_manager
        # CALIENNE_GENERATION_TIMEOUT_SEC: per-agent generation budget override.
        # Free-tier models can have long generation tails; the previous shared
        # 30s wall cancelled a FINISHED agent because its sibling was slow
        # (live-fired 2026-09-19).
        env_timeout = os.environ.get("CALIENNE_GENERATION_TIMEOUT_SEC", "").strip()
        if env_timeout.isdigit() and int(env_timeout) > 0:
            self.PARALLEL_AGENT_TIMEOUT_SEC = int(env_timeout)

    async def execute(
        self,
        query: str,
        gateway: AsyncAPIGateway,
        strategy: ProviderStrategy,
        pool: ProviderPool,
        passport: ExecutionPassport,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[Optional[AgentOutput], Optional[AgentOutput]]:
        """Execute Logician and Creative agents within 30 seconds.

        Returns ``(logician_output, creative_output)`` where ``None``
        indicates a failed agent.
        """
        if self.strategy == DecisionStrategy.SEQUENTIAL:
            res = await self._execute_sequential(query, gateway, strategy, pool, passport, history)
        elif self.strategy == DecisionStrategy.CONDITIONAL:
            res = await self._execute_conditional(query, gateway, strategy, pool, passport, history)
        else:
            res = await self._execute_parallel(query, gateway, strategy, pool, passport, history)

        if self.streaming_manager:
            safe_create_task_broadcast(
                self.streaming_manager.emit_event(
                    request_id=passport.request_id,
                    event=StreamEvent(
                        event=EventType.GENERATION_COMPLETED,
                        data={"strategy": self.strategy.value}
                    )
                ),
                name="generation-completed-broadcast",
            )
        return res

    # ── Agent wrappers ────────────────────────────────────────────────

    async def _execute_logician(
        self,
        query: str,
        gateway: AsyncAPIGateway,
        strategy: ProviderStrategy,
        pool: ProviderPool,
        passport: ExecutionPassport,
        history: list[dict[str, str]] | None = None,
    ) -> AgentOutput:
        """Assemble Logician prompt, call gateway, parse into AgentOutput."""
        system_prompt = assemble_logician_prompt(strategy.mode.value)
        raw = await dispatch_provider_call(
            self.runtime_engine,
            prompt=query,
            system_prompt=system_prompt,
            role="logician",
            gateway=gateway,
            strategy=strategy,
            pool=pool,
            passport=passport,
            history=history,
        )
        return safe_parse_agent_output(raw, "Logician", parse_and_repair, AgentOutput)

    async def _execute_creative(
        self,
        query: str,
        gateway: AsyncAPIGateway,
        strategy: ProviderStrategy,
        pool: ProviderPool,
        passport: ExecutionPassport,
        history: list[dict[str, str]] | None = None,
    ) -> AgentOutput:
        """Assemble Creative prompt, call gateway, parse into AgentOutput."""
        system_prompt = assemble_creative_prompt(strategy.mode.value)
        raw = await dispatch_provider_call(
            self.runtime_engine,
            prompt=query,
            system_prompt=system_prompt,
            role="creative",
            gateway=gateway,
            strategy=strategy,
            pool=pool,
            passport=passport,
            history=history,
        )
        return safe_parse_agent_output(raw, "Creative", parse_and_repair, AgentOutput)

    # ── Execution strategies ──────────────────────────────────────────

    async def _execute_parallel(
        self,
        query: str,
        gateway: AsyncAPIGateway,
        strategy: ProviderStrategy,
        pool: ProviderPool,
        passport: ExecutionPassport,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[Optional[AgentOutput], Optional[AgentOutput]]:
        """Execute Logician and Creative in parallel, each with its own timeout.

        A slow agent is abandoned individually while the sibling's finished
        output survives: the previous shared ``wait_for(gather(...))``
        cancelled BOTH tasks on one wall clock, discarding a completed result
        because the other agent was slow (live-fired 2026-09-19 — a finished
        Logician was thrown away when Creative hung).
        """
        timeout = self.PARALLEL_AGENT_TIMEOUT_SEC

        async def _guarded(coro: Any, name: str) -> Optional[AgentOutput]:
            try:
                return await asyncio.wait_for(coro, timeout=timeout)
            except asyncio.TimeoutError:
                passport.record_error("generation", f"{name} timed out after {timeout}s")
                logger.error("%s timed out after %ds", name, timeout)
                return None

        results = await asyncio.gather(
            _guarded(
                self._execute_logician(query, gateway, strategy, pool, passport, history),
                "Logician",
            ),
            _guarded(
                self._execute_creative(query, gateway, strategy, pool, passport, history),
                "Creative",
            ),
            return_exceptions=True,
        )

        logician_output: Optional[AgentOutput] = None
        creative_output: Optional[AgentOutput] = None

        # Unpack results — exceptions become None
        for idx, result in enumerate(results):
            if isinstance(result, BaseException):
                name = "Logician" if idx == 0 else "Creative"
                logger.error("%s generation failed: %s", name, result)
            else:
                if idx == 0:
                    logician_output = result
                else:
                    creative_output = result

        # Handle partial failures
        if logician_output is None and creative_output is not None:
            passport.record_warning("Logician agent failed but Creative succeeded")
            logger.warning("Logician failed; using Creative output only.")
        elif creative_output is None and logician_output is not None:
            passport.record_warning("Creative agent failed but Logician succeeded")
            logger.warning("Creative failed; using Logician output only.")
        elif logician_output is None and creative_output is None:
            passport.record_error("generation", "Both Logician and Creative agents failed")
            logger.error("Both generation agents failed.")

        return logician_output, creative_output

    async def _execute_sequential(
        self,
        query: str,
        gateway: AsyncAPIGateway,
        strategy: ProviderStrategy,
        pool: ProviderPool,
        passport: ExecutionPassport,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[Optional[AgentOutput], Optional[AgentOutput]]:
        """Execute Logician first, then Creative only if needed."""
        logician_output = await execute_with_passport_logging(
            self._execute_logician(query, gateway, strategy, pool, passport, history),
            passport,
            "generation",
            "Sequential Logician",
            logger_instance=logger,
        )
        if logician_output is None:
            return None, None

        creative_output = await execute_with_passport_logging(
            self._execute_creative(query, gateway, strategy, pool, passport, history),
            passport,
            "generation",
            "Sequential Creative",
            logger_instance=logger,
            on_error_return=None,
        )

        return logician_output, creative_output

    async def _execute_conditional(
        self,
        query: str,
        gateway: AsyncAPIGateway,
        strategy: ProviderStrategy,
        pool: ProviderPool,
        passport: ExecutionPassport,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[Optional[AgentOutput], Optional[AgentOutput]]:
        """Run Logician first; if confidence < 0.7, also run Creative."""
        logician_output = await execute_with_passport_logging(
            self._execute_logician(query, gateway, strategy, pool, passport, history),
            passport,
            "generation",
            "Conditional Logician",
            logger_instance=logger,
        )
        if logician_output is None:
            return None, None

        if logician_output.confidence >= self.CONDITIONAL_CONFIDENCE_THRESHOLD:
            logger.info(
                "Logician confidence %.2f >= %.2f — skipping Creative.",
                logician_output.confidence,
                self.CONDITIONAL_CONFIDENCE_THRESHOLD,
            )
            return logician_output, None

        logger.info(
            "Logician confidence %.2f < %.2f — executing Creative.",
            logician_output.confidence,
            self.CONDITIONAL_CONFIDENCE_THRESHOLD,
        )
        creative_output = await execute_with_passport_logging(
            self._execute_creative(query, gateway, strategy, pool, passport, history),
            passport,
            "generation",
            "Conditional Creative",
            logger_instance=logger,
            on_error_return=None,
        )

        return logician_output, creative_output
