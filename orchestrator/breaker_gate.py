"""The Breaker Gate: a lightweight answerability pre-filter.

Extracted from decisions.py (god-object decomposition). Decides whether the
pipeline has enough knowledge to attempt an answer: general-knowledge
questions proceed (trained knowledge counts as knowledge); only queries
depending on context that is not present abstain.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from agents.parser import parse_and_repair
from agents.prompt_utils import assemble_breaker_prompt, safe_parse_agent_output
from api_gateway.rate_limiter import AsyncAPIGateway, ProviderPool
from api_gateway.strategy import ProviderStrategy
from core.error_handlers import log_and_record_error
from core.passport import ExecutionPassport
from core.schemas import AgentOutput
from orchestrator.decision_support import dispatch_provider_call, safe_create_task_broadcast
from orchestrator.streaming import EventType, StreamEvent

logger = logging.getLogger(__name__)


class BreakerGate:
    """Knowledge-absence detection within a configurable time budget.

    Timing: AETHERIS_BREAKER_TIMEOUT_MS (default 100ms — enough for
    simulation mode; live LLM round-trips need ~5-8s). On timeout or error
    the gate FAILS OPEN: a slow or erroring breaker is an infrastructure
    artifact, not knowledge absence, so the pipeline continues and pays the
    calls it would have made without a breaker.
    """

    BREAKER_TIMEOUT_MS: int = 100
    KNOWLEDGE_ABSENCE_THRESHOLD: float = 0.3
    KNOWLEDGE_ABSENCE_SENTINEL: str = "KNOWLEDGE ABSENCE DETECTED"

    def __init__(
        self,
        runtime_engine: Any = None,
        streaming_manager: Any = None,
        timeout_ms: Optional[int] = None,
    ) -> None:
        self.runtime_engine = runtime_engine
        self.streaming_manager = streaming_manager
        if timeout_ms is not None:
            self.BREAKER_TIMEOUT_MS = int(timeout_ms)

    async def execute(
        self,
        query: str,
        gateway: AsyncAPIGateway,
        strategy: ProviderStrategy,
        pool: ProviderPool,
        passport: ExecutionPassport,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[bool, Optional[AgentOutput]]:
        """Run the gate; returns ``(should_continue, breaker_output)``.

        Knowledge absence is detected when the output's confidence is below
        the threshold or the answer carries the sentinel string. Timeout and
        infrastructure errors fail open (pipeline continues).
        """
        try:
            breaker_output = await asyncio.wait_for(
                self._execute(query, gateway, strategy, pool, passport, history),
                timeout=self.BREAKER_TIMEOUT_MS / 1000.0,
            )
        except asyncio.TimeoutError:
            passport.record_error(
                "breaker",
                f"Breaker execution timeout exceeded {self.BREAKER_TIMEOUT_MS}ms "
                "(failing open: pipeline continues)",
            )
            logger.warning(
                "Breaker gate timed out after %dms — failing open.", self.BREAKER_TIMEOUT_MS
            )
            return True, None
        except Exception as exc:
            log_and_record_error(passport, "breaker", exc, logger_instance=logger)
            logger.warning("Breaker gate errored — failing open.")
            return True, None

        is_absent = (
            breaker_output.confidence < self.KNOWLEDGE_ABSENCE_THRESHOLD
            or self.KNOWLEDGE_ABSENCE_SENTINEL in breaker_output.answer
        )

        if is_absent and self.streaming_manager:
            safe_create_task_broadcast(
                self.streaming_manager.emit_event(
                    request_id=passport.request_id,
                    event=StreamEvent(
                        event=EventType.BREAKER_FAILED,
                        data={"confidence": breaker_output.confidence}
                    )
                ),
                name="breaker-failed-broadcast",
            )
        elif not is_absent and self.streaming_manager:
            safe_create_task_broadcast(
                self.streaming_manager.emit_event(
                    request_id=passport.request_id,
                    event=StreamEvent(
                        event=EventType.BREAKER_PASSED,
                        data={"confidence": breaker_output.confidence}
                    )
                ),
                name="breaker-passed-broadcast",
            )
        return not is_absent, breaker_output

    async def _execute(
        self,
        query: str,
        gateway: AsyncAPIGateway,
        strategy: ProviderStrategy,
        pool: ProviderPool,
        passport: ExecutionPassport,
        history: list[dict[str, str]] | None = None,
    ) -> AgentOutput:
        """Assemble the Breaker prompt, call the gateway, parse into AgentOutput."""
        passport.update_stage("breaker")
        system_prompt = assemble_breaker_prompt(strategy.mode.value)
        raw = await dispatch_provider_call(
            self.runtime_engine,
            prompt=query,
            system_prompt=system_prompt,
            role="breaker",
            gateway=gateway,
            strategy=strategy,
            pool=pool,
            passport=passport,
            history=history,
        )
        return safe_parse_agent_output(raw, "Breaker", parse_and_repair, AgentOutput)
