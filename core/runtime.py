"""
aetheris — Runtime Engine with contract enforcement.

The RuntimeEngine orchestrates prompt execution with full contract enforcement
for security, streaming, and resource management. It validates contracts before
execution, enforces timeouts, tracks metrics, and emits telemetry events.

Specifications from Requirement 5 and Design Document Component 4:
- Contract validation before execution
- Security contract enforcement (prompt injection prevention, secret scrubbing)
- Streaming contract enforcement (SSE event emission)
- Resource contract enforcement (timeout limits, token limits, concurrent requests)
- Execution metrics tracking per agent and provider
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from core.passport import ExecutionPassport
from core.schemas import AgentOutput

logger = logging.getLogger(__name__)


# ── Runtime Contract ─────────────────────────────────────────────────────


@dataclass
class RuntimeContract:
    """Runtime execution contract enforcing operational constraints.

    Attributes:
        max_timeout_sec: Maximum execution timeout in seconds.
        max_tokens: Maximum token count per request.
        max_concurrent_requests: Maximum concurrent requests allowed.
        require_security_validation: Whether security validation is required.
        require_streaming: Whether streaming events must be emitted.
        rate_limit_per_minute: Rate limit for this execution context.
    """

    max_timeout_sec: int = 120
    max_tokens: int = 4096
    max_concurrent_requests: int = 10
    require_security_validation: bool = True
    require_streaming: bool = True
    rate_limit_per_minute: int = 60


# ── Execution Metrics ────────────────────────────────────────────────────


@dataclass
class AgentExecutionMetrics:
    """Aggregated metrics for a specific agent-provider combination."""

    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    total_latency_ms: float = 0.0
    total_tokens: int = 0
    last_execution_timestamp: Optional[datetime] = None

    @property
    def mean_latency_ms(self) -> float:
        """Calculate mean latency in milliseconds."""
        if self.total_executions == 0:
            return 0.0
        return self.total_latency_ms / self.total_executions

    @property
    def success_rate(self) -> float:
        """Calculate success rate (0.0 to 1.0)."""
        if self.total_executions == 0:
            return 0.0
        return self.successful_executions / self.total_executions

    @property
    def error_rate(self) -> float:
        """Calculate error rate (0.0 to 1.0)."""
        if self.total_executions == 0:
            return 0.0
        return self.failed_executions / self.total_executions

    def to_dict(self) -> dict[str, Any]:
        """Serialize metrics for reporting."""
        return {
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "mean_latency_ms": round(self.mean_latency_ms, 2),
            "total_tokens": self.total_tokens,
            "success_rate": round(self.success_rate, 4),
            "error_rate": round(self.error_rate, 4),
            "last_execution_timestamp": (
                self.last_execution_timestamp.isoformat()
                if self.last_execution_timestamp
                else None
            ),
        }


# ── Runtime Engine ───────────────────────────────────────────────────────


class RuntimeEngine:
    """Execute prompts with full contract enforcement.

    Integrates SecurityValidator, StreamingManager, and ResourceManager
    to provide a unified execution interface with contract validation,
    metrics tracking, and telemetry emission.

    Specifications from Requirement 5:
    - Validate all execution requests against runtime contracts
    - Enforce security contracts (prompt injection prevention, secret scrubbing)
    - Enforce streaming contracts and emit SSE events for all agent activities
    - Enforce resource contracts (timeout limits, token limits, concurrent request limits)
    - Reject requests on contract violations
    - Track execution metrics per agent and provider
    """

    DEFAULT_CONTRACT = RuntimeContract()

    def __init__(
        self,
        security_validator: Any = None,
        streaming_manager: Any = None,
        resource_manager: Any = None,
    ) -> None:
        """Initialize the RuntimeEngine with dependency injection.

        Args:
            security_validator: SecurityValidator instance for input validation.
            streaming_manager: StreamingManager instance for SSE event emission.
            resource_manager: ResourceManager instance for rate limiting.
        """
        self.security_validator = security_validator
        self.streaming_manager = streaming_manager
        self.resource_manager = resource_manager
        self.contracts: dict[str, RuntimeContract] = {}
        self._metrics: dict[tuple[str, str], AgentExecutionMetrics] = defaultdict(
            AgentExecutionMetrics
        )
        logger.info("RuntimeEngine initialized.")

    # ── Contract Management ────────────────────────────────────────────

    def register_contract(self, name: str, contract: RuntimeContract) -> None:
        """Register a runtime contract for a specific execution context.

        Args:
            name: Name identifier for the contract.
            contract: RuntimeContract instance with execution constraints.
        """
        if not isinstance(contract, RuntimeContract):
            raise TypeError("contract must be a RuntimeContract instance")
        self.contracts[name] = contract
        logger.info(
            "Registered runtime contract '%s' (timeout=%ds, tokens=%d).",
            name,
            contract.max_timeout_sec,
            contract.max_tokens,
        )

    def get_contract(self, name: str) -> RuntimeContract:
        """Retrieve a registered contract by name.

        Args:
            name: Name of the contract to retrieve.

        Returns:
            RuntimeContract if found, otherwise the default contract.
        """
        return self.contracts.get(name, self.DEFAULT_CONTRACT)

    # ── Contract Validation ────────────────────────────────────────────

    def validate_contracts(
        self,
        passport: ExecutionPassport,
        contract_name: Optional[str] = None,
    ) -> tuple[bool, list[str]]:
        """Validate all contract requirements against the passport state.

        Args:
            passport: The ExecutionPassport to validate.
            contract_name: Optional contract name to validate against.
                          If None, uses the default contract.

        Returns:
            Tuple of (is_valid, list_of_violation_descriptions).
        """
        contract = self.get_contract(contract_name or "default")
        violations: list[str] = []

        # Verify security validation: no injection attempts recorded
        if contract.require_security_validation:
            if passport.security_metadata.injection_attempts > 0:
                violations.append(
                    f"Security violation: {passport.security_metadata.injection_attempts} "
                    "injection attempt(s) detected"
                )

        # Verify timeout: execution duration must be less than contract timeout
        elapsed = passport.elapsed_seconds()
        if elapsed > contract.max_timeout_sec:
            violations.append(
                f"Timeout violation: execution duration {elapsed:.1f}s exceeds "
                f"contract limit of {contract.max_timeout_sec}s"
            )

        # Verify token limit: token count must be less than contract max_tokens
        # (Token count tracked in agent outputs if available)
        total_tokens = sum(
            getattr(output, "token_count", 0)
            for output in passport.execution_state.agent_outputs.values()
            if hasattr(output, "token_count")
        )
        if total_tokens > contract.max_tokens:
            violations.append(
                f"Token limit violation: {total_tokens} tokens exceeds "
                f"contract limit of {contract.max_tokens}"
            )

        is_valid = len(violations) == 0
        return is_valid, violations

    # ── Execution with Contracts ───────────────────────────────────────

    async def execute_with_contracts(
        self,
        prompt: str,
        system_prompt: str,
        role: str,
        passport: ExecutionPassport,
        gateway: Any,
        strategy: Any,
        pool: Any,
        history: Optional[list[dict[str, str]]] = None,
        contract_name: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """Execute a prompt with full contract enforcement.

        Steps:
        1. Validate security contracts (input validation)
        2. Acquire rate limiting resources
        3. Emit AGENT_STARTED streaming event
        4. Execute agent with timeout enforcement
        5. Emit AGENT_COMPLETED streaming event on success

        Args:
            prompt: User prompt to execute.
            system_prompt: System prompt for the agent.
            role: Agent role (breaker, logician, creative, judge).
            passport: ExecutionPassport for request tracking.
            gateway: AsyncAPIGateway for model execution.
            strategy: ProviderStrategy for model selection.
            pool: ProviderPool for health tracking.
            history: Optional conversation history.
            contract_name: Optional contract name. Uses default if None.
            user_id: Optional user identifier for rate limiting.

        Returns:
            Agent response string.

        Raises:
            SecurityValidationError: If security validation fails.
            RuntimeError: If contract violation detected or execution fails.
        """
        contract = self.get_contract(contract_name or "default")
        request_id = passport.request_id

        # Step 1: Security validation
        if contract.require_security_validation and self.security_validator is not None:
            is_valid, violations = self.security_validator.validate_input(prompt)
            if not is_valid:
                for violation in violations:
                    passport.record_validation_failure(violation.description)
                    if violation.violation_type == "prompt_injection":
                        passport.record_injection_attempt()

                # Emit events via StreamingManager
                if contract.require_streaming and self.streaming_manager is not None:
                    from orchestrator.streaming import EventType, StreamEvent

                    if any(v.violation_type == "prompt_injection" for v in violations):
                        passport.record_injection_attempt()
                        asyncio.create_task(self.streaming_manager.emit_event(
                            request_id,
                            StreamEvent(
                                event=EventType.INJECTION_DETECTED,
                                data={
                                    "request_id": request_id,
                                    "violations": [v.to_dict() for v in violations],
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                            )
                        ))
                    else:
                        asyncio.create_task(self.streaming_manager.emit_event(
                            request_id,
                            StreamEvent(
                                event=EventType.VALIDATION_FAILED,
                                data={
                                    "request_id": request_id,
                                    "violations": [v.to_dict() for v in violations],
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                            )
                        ))

                logger.warning(
                    "Security validation failed for prompt execution.",
                    extra={"request_id": request_id, "session_id": passport.session_id, "agent_name": role, "stage": "security_validation"}  # noqa: E501
                )
                from core.security import SecurityValidationError

                raise SecurityValidationError(violations)

        # Step 2: Rate limiting
        # Tier 0.4: provider identity was hardcoded to "default" and user_id
        # was never populated, so every token bucket shared one anonymous
        # key and limiting never actually bound anyone. Derive the provider
        # from the strategy's primary model for this role and fall back to
        # the passport's authenticated user when the caller passed none.
        provider_name = "default"
        try:
            chain = strategy.get_model_chain(role)
            if chain:
                provider_name = str(chain[0]).split("/", 1)[0]
        except Exception:  # noqa: BLE001 — unknown role/strategy shape keeps legacy key
            pass
        effective_user_id = user_id or (passport.user_id if passport is not None else None)
        acquired = False
        if self.resource_manager is not None:
            acquired = await self.resource_manager.acquire_resources(
                provider=provider_name, user_id=effective_user_id
            )
            if not acquired:
                if contract.require_streaming and self.streaming_manager is not None:
                    from orchestrator.streaming import EventType, StreamEvent
                    await self.streaming_manager.emit_event(
                        request_id,
                        StreamEvent(
                            event=EventType.RATE_LIMIT_EXCEEDED,
                            data={
                                "request_id": request_id,
                                "provider": provider_name,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        ),
                    )
                logger.warning(
                    "Rate or concurrency limit exceeded.",
                    extra={"request_id": request_id, "session_id": passport.session_id, "agent_name": role, "stage": "rate_limiting"},  # noqa: E501
                )
                raise RuntimeError("Rate or concurrency limit exceeded")

        # Step 3: Emit AGENT_STARTED event
        if contract.require_streaming and self.streaming_manager is not None:
            from orchestrator.streaming import EventType, StreamEvent

            await self.streaming_manager.emit_event(
                request_id,
                StreamEvent(
                    event=EventType.AGENT_STARTED,
                    data={
                        "agent_name": role,
                        "request_id": request_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                ),
            )

        # Step 4: Execute agent with timeout enforcement
        start_time = time.monotonic()
        try:
            response = await asyncio.wait_for(
                gateway.execute_with_fallback(
                    prompt=prompt,
                    role=role,
                    strategy=strategy,
                    pool=pool,
                    system_prompt=system_prompt,
                    history=history,
                    passport=passport,
                ),
                timeout=contract.max_timeout_sec,
            )

            elapsed_ms = (time.monotonic() - start_time) * 1000

            # Track successful execution
            self.track_execution_metrics(
                agent=role,
                provider=provider_name,
                latency_ms=elapsed_ms,
                tokens=0,  # Token count tracked elsewhere
                success=True,
            )

            passport.update_stage(f"{role}_completed")

            # Step 5: Emit AGENT_COMPLETED event
            if contract.require_streaming and self.streaming_manager is not None:
                from orchestrator.streaming import EventType, StreamEvent

                await self.streaming_manager.emit_event(
                    request_id,
                    StreamEvent(
                        event=EventType.AGENT_COMPLETED,
                        data={
                            "agent_name": role,
                            "request_id": request_id,
                            "latency_ms": round(elapsed_ms, 2),
                            "success": True,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    ),
                )

            return response

        except asyncio.TimeoutError as timeout_exc:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "Agent execution timeout exceeded %ds", contract.max_timeout_sec,
                extra={"request_id": request_id, "session_id": passport.session_id, "agent_name": role, "stage": "execution"}  # noqa: E501
            )
            passport.record_error(
                role,
                f"Agent execution timeout exceeded {contract.max_timeout_sec}s",
                {"timeout_seconds": contract.max_timeout_sec},
            )
            self.track_execution_metrics(
                agent=role,
                provider=provider_name,
                latency_ms=elapsed_ms,
                tokens=0,
                success=False,
            )

            # Emit ERROR event
            if contract.require_streaming and self.streaming_manager is not None:
                from orchestrator.streaming import EventType, StreamEvent

                await self.streaming_manager.emit_event(
                    request_id,
                    StreamEvent(
                        event=EventType.ERROR,
                        data={
                            "agent_name": role,
                            "request_id": request_id,
                            "error": f"Timeout after {contract.max_timeout_sec}s",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    ),
                )

            raise RuntimeError(
                f"Agent '{role}' execution timed out after {contract.max_timeout_sec}s"
            ) from timeout_exc

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.exception(
                "Agent execution failed: %s", exc,
                extra={"request_id": request_id, "session_id": passport.session_id, "agent_name": role, "stage": "execution"}  # noqa: E501
            )
            passport.record_error(role, f"Agent execution failed: {exc}")
            self.track_execution_metrics(
                agent=role,
                provider=provider_name,
                latency_ms=elapsed_ms,
                tokens=0,
                success=False,
            )

            # Emit ERROR event
            if contract.require_streaming and self.streaming_manager is not None:
                from orchestrator.streaming import EventType, StreamEvent

                await self.streaming_manager.emit_event(
                    request_id,
                    StreamEvent(
                        event=EventType.ERROR,
                        data={
                            "agent_name": role,
                            "request_id": request_id,
                            "error": str(exc),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    ),
                )

            raise

        finally:
            # Release rate limiting resources
            if self.resource_manager is not None and acquired:
                self.resource_manager.release_resources(
                    provider=provider_name, user_id=user_id
                )

    # ── Metrics Tracking ───────────────────────────────────────────────

    def track_execution_metrics(
        self,
        agent: str,
        provider: str,
        latency_ms: float,
        tokens: int,
        success: bool,
    ) -> None:
        """Track execution metrics per agent and provider.

        Args:
            agent: Agent role name (breaker, logician, creative, judge).
            provider: Provider identifier.
            latency_ms: Execution latency in milliseconds.
            tokens: Number of tokens consumed.
            success: Whether execution was successful.
        """
        key = (agent, provider)
        metrics = self._metrics[key]
        metrics.total_executions += 1
        metrics.total_latency_ms += latency_ms
        metrics.total_tokens += tokens
        metrics.last_execution_timestamp = datetime.now(timezone.utc)

        if success:
            metrics.successful_executions += 1
        else:
            metrics.failed_executions += 1

        logger.debug(
            "Tracked execution: agent=%s, provider=%s, latency=%.1fms, "
            "tokens=%d, success=%s",
            agent,
            provider,
            latency_ms,
            tokens,
            success,
        )

    def get_metrics_report(self) -> dict[str, Any]:
        """Return aggregated metrics by agent and provider.

        Returns:
            Dictionary structure:
            {
                "agent_name": {
                    "provider_name": {
                        "mean_latency_ms": float,
                        "total_tokens": int,
                        "success_rate": float,
                        "error_rate": float,
                        "total_executions": int,
                    }
                }
            }
        """
        report: dict[str, dict[str, dict[str, Any]]] = {}

        for (agent, provider), metrics in self._metrics.items():
            if agent not in report:
                report[agent] = {}
            report[agent][provider] = {
                "mean_latency_ms": round(metrics.mean_latency_ms, 2),
                "total_tokens": metrics.total_tokens,
                "success_rate": round(metrics.success_rate, 4),
                "error_rate": round(metrics.error_rate, 4),
                "total_executions": metrics.total_executions,
            }

        return report

    def get_agent_metrics(self, agent: str) -> dict[str, dict[str, Any]]:
        """Return metrics for a specific agent across all providers.

        Args:
            agent: Agent role name.

        Returns:
            Dictionary mapping provider names to their metrics.
        """
        return {
            provider: metrics.to_dict()
            for (a, provider), metrics in self._metrics.items()
            if a == agent
        }

    def get_provider_metrics(self, provider: str) -> dict[str, dict[str, Any]]:
        """Return metrics for a specific provider across all agents.

        Args:
            provider: Provider identifier.

        Returns:
            Dictionary mapping agent names to their metrics.
        """
        return {
            agent: metrics.to_dict()
            for (agent, p), metrics in self._metrics.items()
            if p == provider
        }

    def reset_metrics(self) -> None:
        """Reset all collected metrics."""
        self._metrics.clear()
        logger.info("RuntimeEngine metrics reset.")
