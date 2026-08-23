"""
calienne — Adaptive Multi-Model Reasoning Orchestrator
Absolute Network Boundary (The Shield) - Rate Limiter & Health tracking.

This module enforces rate-limiting (concurrency limits), dynamic pre-request
jitter, retry-with-backoff, and provider circuit breaking/cooldown.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Optional

from api_gateway.client import AsyncHTTPClient, get_last_provider_usage
from api_gateway.strategy import ProviderStrategy
from core.passport import ExecutionPassport
from core.security import (
    SecurityValidationError,
    SecurityValidator,
)

logger = logging.getLogger(__name__)

# ── Type aliases ─────────────────────────────────────────────────────────
AsyncModelCaller = Callable[
    [str, str, Optional[str], list[dict[str, str]] | None],
    Coroutine[Any, Any, str],
]

# ── Defaults ─────────────────────────────────────────────────────────────
_DEFAULT_MAX_CONCURRENCY = 5
_DEFAULT_JITTER_MIN_SEC = 0.05
_DEFAULT_JITTER_MAX_SEC = 0.50


def extract_provider_key(model: str) -> str:
    """
    Derive a circuit-breaker key from a model identifier.

    Uses up to the first two path segments so that models behind the same
    gateway but served by different upstream providers get independent
    health tracking.  For example:

    * ``'openrouter/anthropic/claude-sonnet-4.6'`` → ``'openrouter/anthropic'``
    * ``'openrouter/openai/gpt-4o-mini'``          → ``'openrouter/openai'``
    * ``'nvidia/meta/llama-3.1-70b-instruct'``     → ``'nvidia/meta'``
    * ``'local/phi-3'``                            → ``'local/phi-3'``
    * ``'unknown'``                                → ``'unknown'``
    """
    parts = model.split("/")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


# ── Provider Health Tracking & Cooldown ─────────────────────────────────

class ProviderStatus(str, Enum):
    """Possible health states for an LLM provider."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DEAD = "dead"


class CircuitBreakerState(str, Enum):
    """Circuit breaker states for provider fault tolerance."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class ProviderCapabilities:
    """Provider capability metadata for routing decisions."""
    supported_roles: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    pricing_tier: str = "standard"
    max_tokens: int = 4096
    supports_streaming: bool = False
    supports_function_calling: bool = False


@dataclass
class HealthMetrics:
    """Aggregated health metrics for a provider over a rolling window."""
    success_rate: float = 1.0
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0
    mean_latency_ms: float = 0.0
    error_count_24h: int = 0
    last_success_timestamp: Optional[float] = None
    last_failure_timestamp: Optional[float] = None


@dataclass
class ProviderState:
    """Mutable health record for a single provider with circuit breaker."""
    status: ProviderStatus = ProviderStatus.HEALTHY
    error_count: int = 0
    last_failure_timestamp: Optional[float] = None
    cooldown_until: Optional[float] = None
    roles: list[str] = field(default_factory=list)
    circuit_breaker_state: CircuitBreakerState = CircuitBreakerState.CLOSED
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    backoff_delay: float = 1.0
    last_success_timestamp: Optional[float] = None
    probe_timestamp: Optional[float] = None
    latency_history: deque = field(default_factory=lambda: deque(maxlen=100))
    request_history: deque = field(default_factory=lambda: deque(maxlen=100))

    def is_circuit_breaker_cooldown_expired(self) -> bool:
        """Check if the circuit breaker cooldown period has elapsed."""
        if self.cooldown_until is None:
            return True
        return time.time() >= self.cooldown_until

    @property
    def is_available(self) -> bool:
        """
        True when the provider can accept requests right now.

        Checks circuit breaker state: OPEN state blocks all requests.
        DEAD providers become available after cooldown expires (probe mode).
        """
        if self.circuit_breaker_state is CircuitBreakerState.OPEN:
            if self.is_circuit_breaker_cooldown_expired():
                return True
            return False
        if self.status is ProviderStatus.DEAD:
            if self.cooldown_until and time.time() >= self.cooldown_until:
                return True
            return False
        return True


class ProviderPool:
    """
    Tracks health, error counts, cooldowns, circuit breaker state, and
    recovery for providers with comprehensive health metrics.
    """

    # Circuit breaker parameters
    CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
    CIRCUIT_BREAKER_COOLDOWN_SEC = 60.0
    CIRCUIT_BREAKER_SUCCESS_THRESHOLD = 3

    # Health status thresholds
    HEALTHY_ERROR_RATE_THRESHOLD = 0.20
    DEGRADED_ERROR_RATE_THRESHOLD = 0.50

    # Recovery parameters
    RECOVERY_BACKOFF_BASE_SEC = 1.0
    RECOVERY_BACKOFF_MAX_SEC = 300.0
    RECOVERY_BACKOFF_MULTIPLIER = 2.0

    # Metrics calculation
    METRICS_ROLLING_WINDOW_SIZE = 100
    ERROR_RATE_WINDOW_SEC = 60

    def __init__(self, degrade_threshold: int = 3) -> None:
        self._providers: dict[str, ProviderState] = {}
        self._degrade_threshold = degrade_threshold
        self._priority_order: list[str] = []
        self._capabilities: dict[str, ProviderCapabilities] = {}

    def register_provider(
        self,
        name: str,
        roles: list[str] | None = None,
        capabilities: Optional[ProviderCapabilities] = None,
    ) -> None:
        """Register a new provider with roles and optional capabilities."""
        if name in self._providers:
            return
        self._providers[name] = ProviderState(roles=roles or [])
        self._priority_order.append(name)
        if capabilities is not None:
            self._capabilities[name] = capabilities
        logger.info("Registered provider '%s' with roles %s.", name, roles or [])

    def report_success(self, provider_name: str, latency_ms: Optional[float] = None) -> None:
        """Reset errors, restore health, and update circuit breaker on success.

        *latency_ms*, when provided, feeds the rolling-window mean latency
        surfaced by ``get_health_metrics`` — without it the metric stays 0
        forever and consumers fall back to fabricated display values.
        """
        state = self._get_state(provider_name)
        if not state:
            return
        state.error_count = 0
        state.consecutive_failures = 0
        state.last_success_timestamp = time.time()
        state.consecutive_successes += 1

        # Record request outcome for metrics
        outcome: dict[str, Any] = {"success": True, "timestamp": time.time()}
        if latency_ms is not None and latency_ms > 0:
            outcome["latency_ms"] = latency_ms
        state.request_history.append(outcome)

        if state.circuit_breaker_state is CircuitBreakerState.HALF_OPEN:
            if state.consecutive_successes >= self.CIRCUIT_BREAKER_SUCCESS_THRESHOLD:
                state.circuit_breaker_state = CircuitBreakerState.CLOSED
                state.consecutive_successes = 0
                state.backoff_delay = self.RECOVERY_BACKOFF_BASE_SEC
                logger.info(
                    "Provider '%s' circuit breaker CLOSED (recovered after %d successes).",
                    provider_name,
                    self.CIRCUIT_BREAKER_SUCCESS_THRESHOLD,
                )
        elif state.status is not ProviderStatus.HEALTHY:
            logger.info("Provider '%s' recovered → HEALTHY.", provider_name)

        state.status = ProviderStatus.HEALTHY
        state.cooldown_until = None

    def report_failure(self, provider_name: str) -> None:
        """Record a failure, auto-degrade, and update circuit breaker state."""
        state = self._get_state(provider_name)
        if not state:
            return
        state.error_count += 1
        state.last_failure_timestamp = time.time()

        # Record request outcome for metrics
        state.request_history.append({"success": False, "timestamp": time.time()})

        logger.warning(
            "Provider '%s' failure #%d.",
            provider_name,
            state.error_count,
        )

        # Auto-degrade if threshold breached
        if state.error_count >= self._degrade_threshold and state.status is ProviderStatus.HEALTHY:
            state.status = ProviderStatus.DEGRADED
            logger.warning("Provider '%s' auto-degraded to DEGRADED.", provider_name)

        # Update circuit breaker (handles consecutive_failures internally)
        self.update_circuit_breaker(provider_name, success=False)

    def update_circuit_breaker(self, provider_name: str, success: bool) -> None:
        """Update circuit breaker state based on success or failure."""
        state = self._get_state(provider_name)
        if not state:
            return

        if success:
            state.consecutive_failures = 0
            state.consecutive_successes += 1
            if state.circuit_breaker_state is CircuitBreakerState.HALF_OPEN:
                if state.consecutive_successes >= self.CIRCUIT_BREAKER_SUCCESS_THRESHOLD:
                    state.circuit_breaker_state = CircuitBreakerState.CLOSED
                    state.backoff_delay = self.RECOVERY_BACKOFF_BASE_SEC
                    logger.info(
                        "Provider '%s' circuit breaker CLOSED (recovered).",
                        provider_name,
                    )
        else:
            state.consecutive_successes = 0
            state.consecutive_failures += 1

            if state.circuit_breaker_state is CircuitBreakerState.CLOSED:
                if state.consecutive_failures >= self.CIRCUIT_BREAKER_FAILURE_THRESHOLD:
                    state.circuit_breaker_state = CircuitBreakerState.OPEN
                    state.cooldown_until = time.time() + self.CIRCUIT_BREAKER_COOLDOWN_SEC
                    logger.warning(
                        "Provider '%s' circuit breaker OPENED after %d consecutive failures.",
                        provider_name,
                        state.consecutive_failures,
                    )
            elif state.circuit_breaker_state is CircuitBreakerState.HALF_OPEN:
                state.circuit_breaker_state = CircuitBreakerState.OPEN
                state.cooldown_until = time.time() + self.CIRCUIT_BREAKER_COOLDOWN_SEC
                state.consecutive_successes = 0
                logger.warning(
                    "Provider '%s' circuit breaker reverted to OPEN (probe failed).",
                    provider_name,
                )

        # Transition OPEN → HALF_OPEN when cooldown expires
        if state.circuit_breaker_state is CircuitBreakerState.OPEN:
            if state.is_circuit_breaker_cooldown_expired():
                state.circuit_breaker_state = CircuitBreakerState.HALF_OPEN
                state.consecutive_successes = 0
                state.probe_timestamp = time.time()
                logger.info("Provider '%s' circuit breaker → HALF_OPEN (cooldown expired).", provider_name)

    def mark_provider_dead(self, provider_name: str, cooldown_seconds: float = 60.0) -> None:
        """Immediately mark a provider as DEAD for a cooldown window."""
        state = self._get_state(provider_name)
        if not state:
            return
        state.status = ProviderStatus.DEAD
        state.circuit_breaker_state = CircuitBreakerState.OPEN
        state.cooldown_until = time.time() + cooldown_seconds
        logger.error(
            "Provider '%s' marked DEAD — cooldown %.0fs (until %.2f).",
            provider_name,
            cooldown_seconds,
            state.cooldown_until,
        )

    def is_provider_healthy(self, provider_name: str) -> bool:
        """Check if provider is available or has outlived its cooldown."""
        state = self._providers.get(provider_name)
        if not state:
            return True
        return state.is_available

    def is_provider_available(self, provider_name: str) -> bool:
        """Check if provider is available for routing (circuit breaker + health)."""
        state = self._providers.get(provider_name)
        if not state:
            return True
        if state.circuit_breaker_state is CircuitBreakerState.OPEN:
            if state.is_circuit_breaker_cooldown_expired():
                return True
            return False
        if state.status is ProviderStatus.DEAD:
            return False
        return state.is_available

    def _get_state(self, provider_name: str) -> Optional[ProviderState]:
        return self._providers.get(provider_name)

    def get_provider_state(self, provider_name: str) -> Optional[ProviderState]:
        """Public method to get provider state for external access."""
        return self._providers.get(provider_name)

    def calculate_health_status(self, provider_name: str) -> str:
        """Calculate provider health status based on error rate over the past 60 seconds."""
        state = self._get_state(provider_name)
        if not state:
            return "healthy"

        # Circuit breaker OPEN = unavailable
        if state.circuit_breaker_state is CircuitBreakerState.OPEN:
            if not state.is_circuit_breaker_cooldown_expired():
                return "dead"

        # Calculate error rate over ERROR_RATE_WINDOW_SEC
        now = time.time()
        window_requests = [
            r for r in state.request_history
            if now - r["timestamp"] <= self.ERROR_RATE_WINDOW_SEC
        ]

        if not window_requests:
            return state.status.value

        total = len(window_requests)
        failures = sum(1 for r in window_requests if not r["success"])
        error_rate = failures / total if total > 0 else 0.0

        if error_rate >= self.DEGRADED_ERROR_RATE_THRESHOLD:
            state.status = ProviderStatus.DEAD
            return "dead"
        elif error_rate >= self.HEALTHY_ERROR_RATE_THRESHOLD:
            state.status = ProviderStatus.DEGRADED
            return "degraded"
        else:
            if state.status is ProviderStatus.DEAD and state.is_circuit_breaker_cooldown_expired():
                state.status = ProviderStatus.DEGRADED
                state.error_count = 0
                logger.info("Resurrected expired provider '%s' to DEGRADED.", provider_name)
                return "degraded"
            return state.status.value

    def get_health_metrics(self, provider_name: str) -> Optional[HealthMetrics]:
        """Retrieve provider health metrics over a rolling window of 100 requests."""
        state = self._get_state(provider_name)
        if not state:
            return None

        window = list(state.request_history)[-self.METRICS_ROLLING_WINDOW_SIZE:]
        if not window:
            return HealthMetrics()

        total = len(window)
        successes = sum(1 for r in window if r["success"])
        failures = total - successes
        latencies = [r.get("latency_ms", 0.0) for r in window if "latency_ms" in r]

        error_rate = failures / total if total > 0 else 0.0
        success_rate = successes / total if total > 0 else 1.0
        mean_latency = sum(latencies) / len(latencies) if latencies else 0.0

        # Count errors in last 24 hours
        cutoff_24h = time.time() - 86400
        error_count_24h = sum(
            1 for r in state.request_history
            if not r["success"] and r["timestamp"] >= cutoff_24h
        )

        return HealthMetrics(
            success_rate=success_rate,
            avg_latency_ms=mean_latency,
            error_rate=error_rate,
            mean_latency_ms=mean_latency,
            error_count_24h=error_count_24h,
            last_success_timestamp=state.last_success_timestamp,
            last_failure_timestamp=state.last_failure_timestamp,
        )

    def attempt_recovery(self, provider_name: str) -> bool:
        """Attempt to recover a DEAD provider with exponential backoff."""
        state = self._get_state(provider_name)
        if not state:
            return False

        if state.status is not ProviderStatus.DEAD:
            return True

        # Check if we should attempt recovery based on backoff
        now = time.time()
        if state.cooldown_until and now < state.cooldown_until:
            return False

        # Attempt recovery
        state.status = ProviderStatus.DEGRADED
        state.cooldown_until = None
        logger.info(
            "Provider '%s' recovery attempt — status → DEGRADED (backoff: %.1fs).",
            provider_name,
            state.backoff_delay,
        )

        # Increase backoff for next failure
        state.backoff_delay = min(
            state.backoff_delay * self.RECOVERY_BACKOFF_MULTIPLIER,
            self.RECOVERY_BACKOFF_MAX_SEC,
        )
        return True

    def get_fallback_chain(self, role: str, primary_provider: str) -> list[str]:
        """Get ordered fallback chain for role, excluding primary provider."""
        candidates = [
            name for name in self._priority_order
            if name != primary_provider
            and role in self._providers[name].roles
            and self.is_provider_available(name)
        ]

        # Order: healthy first, then degraded
        healthy = [n for n in candidates if self._providers[n].status is ProviderStatus.HEALTHY]
        degraded = [n for n in candidates if self._providers[n].status is ProviderStatus.DEGRADED]

        chain = healthy + degraded
        if not chain:
            logger.error("No healthy providers available for role '%s'.", role)
        return chain

    def get_healthy_provider(self, role: str) -> Optional[str]:
        """Find the best available provider for a role."""
        candidates = [name for name in self._priority_order if role in self._providers[name].roles]

        # 1. Prefer healthy
        for name in candidates:
            if self._providers[name].status is ProviderStatus.HEALTHY:
                return name

        # 2. Allow degraded
        for name in candidates:
            if self._providers[name].status is ProviderStatus.DEGRADED:
                return name

        # 3. Resurrect dead if cooldown expired
        for name in candidates:
            state = self._providers[name]
            if state.status is ProviderStatus.DEAD and state.is_available:
                state.status = ProviderStatus.DEGRADED
                state.error_count = 0
                logger.info("Resurrected expired provider '%s' to DEGRADED.", name)
                return name

        return None

    def get_status(self, provider_name: str) -> Optional[dict]:
        state = self._providers.get(provider_name)
        if not state:
            return None
        return {
            "provider": provider_name,
            "status": state.status.value,
            "error_count": state.error_count,
            "last_failure_timestamp": state.last_failure_timestamp,
            "cooldown_until": state.cooldown_until,
            "roles": state.roles,
            "is_available": state.is_available,
            "circuit_breaker_state": state.circuit_breaker_state.value,
            "consecutive_failures": state.consecutive_failures,
        }

    def get_all_statuses(self) -> list[dict]:
        return [self.get_status(name) for name in self._priority_order if name in self._providers]


# ── Resource Manager ────────────────────────────────────────────────────

@dataclass
class RateLimitConfig:
    """Configuration for rate limiting per provider or user."""
    requests_per_minute: int
    tokens_per_minute: int
    concurrent_requests: int


class TokenBucket:
    """Token bucket algorithm for rate limiting."""

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_rate = refill_rate
        self.last_refill = time.time()

    def consume(self, tokens: int = 1) -> bool:
        """Attempt to consume tokens, return True if allowed."""
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def time_until_tokens(self, tokens: int = 1) -> float:
        """Calculate seconds until enough tokens are available."""
        self._refill()
        if self.tokens >= tokens:
            return 0.0
        needed = tokens - self.tokens
        return needed / self.refill_rate


class ProviderResourceManager:
    """
    Enforces rate limits at provider, user, and global levels with dynamic
    adjustment based on provider health status.

    Specifications from Requirement 12:
    - Per-provider rate limit: 100 requests/minute with 10-token bucket capacity
    - Global concurrency limit: 100 concurrent requests across all providers
    - Per-user rate limit: 50 requests/minute
    - Queue capacity: 1000 requests
    - Metrics: requests_per_second (60s rolling average), tokens_per_minute (60s rolling sum),
      concurrent_connections (current count)
    - Dynamic adjustment: 50% reduction for degraded providers, 0 for dead providers
    """

    # Rate limits (Requirement 12.1, 12.3)
    DEFAULT_PROVIDER_RATE_LIMIT = 100  # requests per minute per provider
    TOKEN_BUCKET_CAPACITY = 10  # 10 tokens bucket capacity
    DEFAULT_USER_RATE_LIMIT = 50  # requests per minute per user
    GLOBAL_CONCURRENCY_LIMIT = 100  # 100 concurrent requests globally
    QUEUE_CAPACITY = 1000  # 1000 requests max in queue

    # Metrics calculation (Requirement 12.7-12.8)
    METRICS_WINDOW_SEC = 60  # 60-second rolling window

    def __init__(self) -> None:
        self.provider_limits: dict[str, TokenBucket] = {}
        self.user_limits: dict[str, TokenBucket] = {}
        self.global_semaphore: asyncio.Semaphore = asyncio.Semaphore(self.GLOBAL_CONCURRENCY_LIMIT)
        self.request_queue: deque = deque(maxlen=self.QUEUE_CAPACITY)
        self.request_history: deque = deque()  # Track requests for metrics
        self._provider_base_rates: dict[str, float] = {}  # Store base rates for dynamic adjustment
        self._held_permits: int = 0

    def configure_provider_limit(self, provider: str, config: RateLimitConfig) -> None:
        """Configure rate limits for a specific provider (Requirement 12.1)."""
        refill_rate = config.requests_per_minute / 60.0
        self.provider_limits[provider] = TokenBucket(
            capacity=config.tokens_per_minute,
            refill_rate=refill_rate,
        )
        self._provider_base_rates[provider] = refill_rate
        logger.info(
            "Configured rate limit for provider '%s': %d req/min, %d tokens/min.",
            provider,
            config.requests_per_minute,
            config.tokens_per_minute,
        )

    def configure_user_limit(self, user_id: str, config: RateLimitConfig) -> None:
        """Configure rate limits for a specific user (Requirement 12.3)."""
        refill_rate = config.requests_per_minute / 60.0
        self.user_limits[user_id] = TokenBucket(
            capacity=config.tokens_per_minute,
            refill_rate=refill_rate,
        )
        logger.info(
            "Configured rate limit for user '%s': %d req/min.",
            user_id,
            config.requests_per_minute,
        )

    def _ensure_provider_bucket(self, provider: str) -> TokenBucket:
        """Get or create a token bucket for a provider with default limits."""
        if provider not in self.provider_limits:
            refill_rate = self.DEFAULT_PROVIDER_RATE_LIMIT / 60.0
            self.provider_limits[provider] = TokenBucket(
                capacity=self.TOKEN_BUCKET_CAPACITY,
                refill_rate=refill_rate,
            )
            self._provider_base_rates[provider] = refill_rate
        return self.provider_limits[provider]

    def _ensure_user_bucket(self, user_id: str) -> TokenBucket:
        """Get or create a token bucket for a user with default limits."""
        if user_id not in self.user_limits:
            refill_rate = self.DEFAULT_USER_RATE_LIMIT / 60.0
            self.user_limits[user_id] = TokenBucket(
                capacity=self.TOKEN_BUCKET_CAPACITY,
                refill_rate=refill_rate,
            )
        return self.user_limits[user_id]

    async def acquire_resources(
        self,
        provider: str,
        user_id: Optional[str] = None,
        tokens: int = 1,
    ) -> bool:
        """
        Acquire resources (rate limit tokens), return True if allowed.

        Checks provider TokenBucket, user TokenBucket (if user_id provided),
        and acquires global_semaphore to enforce concurrency limit.
        """
        # Check provider rate limit
        provider_bucket = self._ensure_provider_bucket(provider)
        if not provider_bucket.consume(tokens):
            return False

        # Check user rate limit if user_id provided
        if user_id is not None:
            user_bucket = self._ensure_user_bucket(user_id)
            if not user_bucket.consume(tokens):
                # Refund provider tokens
                provider_bucket.tokens += tokens
                return False

        # Try to acquire global semaphore (non-blocking)
        try:
            await asyncio.wait_for(self.global_semaphore.acquire(), timeout=0.001)
        except (asyncio.TimeoutError, RuntimeError):
            # Could not acquire concurrency slot - refund tokens
            provider_bucket.tokens += tokens
            if user_id is not None:
                user_bucket = self.user_limits.get(user_id)
                if user_bucket:
                    user_bucket.tokens += tokens
            return False

        # Record request in history for metrics
        self._held_permits += 1
        self.request_history.append({"timestamp": time.time(), "tokens": tokens})

        return True

    async def queue_request(
        self,
        request_id: str,
        provider: str,
        user_id: Optional[str] = None,
    ) -> Optional[float]:
        """
        Queue a request when rate limits are exceeded (Requirement 12.4-12.5).

        Returns:
            - None if request was queued successfully
            - retry_after (float seconds) if request was rejected (queue full)
        """
        # Calculate retry-after time based on provider bucket
        provider_bucket = self._ensure_provider_bucket(provider)
        retry_after = provider_bucket.time_until_tokens(1)

        if len(self.request_queue) < self.QUEUE_CAPACITY:
            self.request_queue.append({
                "request_id": request_id,
                "provider": provider,
                "user_id": user_id,
                "queued_at": time.time(),
            })
            logger.info(
                "Request '%s' queued for provider '%s' (queue size: %d).",
                request_id,
                provider,
                len(self.request_queue),
            )
            return None
        else:
            logger.warning(
                "Request '%s' rejected — queue full (%d requests), retry-after: %.2fs.",
                request_id,
                len(self.request_queue),
                retry_after,
            )
            return retry_after

    def release_resources(self, provider: str, user_id: Optional[str] = None) -> None:
        """Release global concurrency slot after request completes."""
        if self._held_permits <= 0:
            logger.warning(
                "release_resources called without balanced acquire (provider=%s) — semaphore permit NOT returned.",  # noqa: E501
                provider,
            )
            return
        try:
            self.global_semaphore.release()
            self._held_permits -= 1
        except RuntimeError:
            logger.warning("Attempted to release semaphore without holding it.")

    def get_resource_metrics(self) -> dict[str, Any]:
        """
        Return resource usage metrics (Requirement 12.7-12.8).

        Returns:
            - requests_per_second: rolling average over 60 seconds
            - tokens_per_minute: rolling sum over 60 seconds
            - concurrent_connections: current active count (semaphore waiters)
        """
        now = time.time()
        window_cutoff = now - self.METRICS_WINDOW_SEC

        # Filter requests within the metrics window
        window_requests = [
            r for r in self.request_history
            if r["timestamp"] >= window_cutoff
        ]

        # Calculate requests_per_second (Requirement 12.8)
        requests_per_second = len(window_requests) / self.METRICS_WINDOW_SEC if window_requests else 0.0

        # Calculate tokens_per_minute (rolling sum over 60 seconds)
        tokens_per_minute = sum(r.get("tokens", 1) for r in window_requests)

        # Calculate concurrent connections (currently acquired semaphore slots)
        # semaphore._value is the number of remaining permits
        concurrent_connections = self.GLOBAL_CONCURRENCY_LIMIT - (
            self.GLOBAL_CONCURRENCY_LIMIT - self.global_semaphore._value
            if hasattr(self.global_semaphore, '_value')
            else 0
        )

        # Clean up old request history
        self.request_history = deque(
            [r for r in self.request_history if r["timestamp"] >= window_cutoff],
            maxlen=self.QUEUE_CAPACITY,
        )

        return {
            "requests_per_second": requests_per_second,
            "tokens_per_minute": tokens_per_minute,
            "concurrent_connections": concurrent_connections,
            "queue_size": len(self.request_queue),
        }

    def adjust_limits_dynamic(self, provider: str, health_status: str) -> None:
        """
        Dynamically adjust rate limits based on provider health (Requirement 12.9).

        Adjustments:
        - healthy: 100% of configured limit
        - degraded: 50% of configured limit
        - dead: 0 (no requests allowed)
        """
        base_rate = self._provider_base_rates.get(provider)
        if base_rate is None:
            # Use default base rate if not configured
            base_rate = self.DEFAULT_PROVIDER_RATE_LIMIT / 60.0
            self._provider_base_rates[provider] = base_rate

        if health_status == "healthy":
            new_rate = base_rate
        elif health_status == "degraded":
            new_rate = base_rate * 0.5  # 50% reduction
        elif health_status == "dead":
            new_rate = 0.0  # Block all requests
        else:
            logger.warning("Unknown health status '%s' for provider '%s'.", health_status, provider)
            return

        # Update existing bucket or create new one
        if provider in self.provider_limits:
            self.provider_limits[provider].refill_rate = new_rate
        else:
            self.provider_limits[provider] = TokenBucket(
                capacity=self.TOKEN_BUCKET_CAPACITY,
                refill_rate=new_rate,
            )

        logger.info(
            "Adjusted rate limit for provider '%s' to %.2f req/s (health: %s).",
            provider,
            new_rate,
            health_status,
        )

# ── Async API Gateway ───────────────────────────────────────────────────

class AsyncAPIGateway:
    """
    Concurrency-limited, jitter-aware API gateway with retry-with-backoff
    and fallback chain execution.
    """

    def __init__(
        self,
        client: AsyncHTTPClient | None = None,
        call_fn: AsyncModelCaller | None = None,
        *,
        max_concurrency: int = _DEFAULT_MAX_CONCURRENCY,
        jitter_range: tuple[float, float] = (
            _DEFAULT_JITTER_MIN_SEC,
            _DEFAULT_JITTER_MAX_SEC,
        ),
    ) -> None:
        self._client = client or AsyncHTTPClient()
        self._call_fn = call_fn
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._jitter_min, self._jitter_max = jitter_range
        self._default_pool = ProviderPool()

        logger.info(
            "AsyncAPIGateway initialized — concurrency=%d, jitter=%.2f-%.2fs.",
            max_concurrency,
            self._jitter_min,
            self._jitter_max,
        )

    async def close(self) -> None:
        """Shut down the underlying HTTP client and release connection pool."""
        await self._client.close()

    async def execute_with_fallback(
        self,
        prompt: str,
        role: str,
        strategy: ProviderStrategy,
        pool: ProviderPool | None = None,
        system_prompt: Optional[str] = None,
        history: list[dict[str, str]] | None = None,
        passport: Optional[Any] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Execute a prompt against the model chain for role, falling back
        on subsequent models upon failure.
        """
        if pool is None:
            pool = self._default_pool
            for model in strategy.get_model_chain(role):
                provider_name = extract_provider_key(model)
                pool.register_provider(provider_name, roles=[role])

        chain = strategy.get_model_chain(role)
        logger.info("Executing prompt for role '%s' — chain: %s", role, chain)

        errors: list[tuple[str, Exception]] = []

        for index, model in enumerate(chain):
            provider_name = extract_provider_key(model)

            if not pool.is_provider_healthy(provider_name):
                logger.warning(
                    "Skipping model '%s' because provider '%s' is dead or cooling down.",
                    model,
                    provider_name,
                )
                continue

            is_fallback = index > 0
            if is_fallback:
                logger.warning(
                    "Falling back to model '%s' (position %d/%d) for role '%s'.",
                    model,
                    index + 1,
                    len(chain),
                    role,
                )

            try:
                response = await self._guarded_call(
                    model, prompt, system_prompt, history, max_tokens=max_tokens
                )
                usage = get_last_provider_usage()
                latency_ms = (
                    float(usage.get("latency_s", 0.0)) * 1000.0
                    if usage and usage.get("latency_s")
                    else None
                )
                pool.report_success(provider_name, latency_ms=latency_ms)
                logger.info(
                    "Model '%s' succeeded for role '%s' (attempt %d/%d).",
                    model,
                    role,
                    index + 1,
                    len(chain),
                )
                return response
            except Exception as exc:
                logger.error(
                    "Model '%s' failed for role '%s': %s: %s",
                    model,
                    role,
                    type(exc).__name__,
                    exc,
                )
                pool.report_failure(provider_name)
                # HIGH-004 audit fix: replaced private ``pool._get_state`` access
                # with the public ``pool.get_provider_state`` accessor.  The
                # public method returns the same ProviderState snapshot without
                # crossing the encapsulation boundary.
                state = pool.get_provider_state(provider_name)
                if state and state.error_count >= pool._degrade_threshold:
                    pool.mark_provider_dead(provider_name)
                errors.append((model, exc))

        raise AllModelsExhaustedError(role=role, chain=chain, errors=errors)

    async def _guarded_call(self, model: str, prompt: str, system_prompt: Optional[str] = None, history: list[dict[str, str]] | None = None, max_tokens: Optional[int] = None) -> str:  # noqa: E501
        """
        Execute a single call using retry-with-backoff, semaphore, and jitter.
        """
        max_retries = 3
        backoff_base = 1.5

        for attempt in range(max_retries):
            # Dynamic Jitter
            jitter = random.uniform(self._jitter_min, self._jitter_max)
            if attempt > 0:
                # Exponential backoff + jitter
                delay = (backoff_base ** attempt) + jitter
                logger.warning(
                    "Attempt %d failed for model %s. Retrying in %.2fs...",
                    attempt,
                    model,
                    delay,
                )
                await asyncio.sleep(delay)
            elif jitter > 0:
                await asyncio.sleep(jitter)

            async with self._semaphore:
                try:
                    start = time.monotonic()
                    logger.debug(
                        "Semaphore acquired — calling model '%s' (attempt %d).",
                        model,
                        attempt + 1,
                    )

                    if self._call_fn:
                        response = await self._call_fn(model, prompt, system_prompt, history)
                    else:
                        response = await self._client.post_request(
                            model, prompt, system_prompt, history, max_tokens=max_tokens
                        )

                    elapsed = time.monotonic() - start
                    logger.debug("Model '%s' responded in %.2fs.", model, elapsed)
                    return response
                except Exception as exc:
                    if attempt == max_retries - 1:
                        raise
                    logger.warning(
                        "Exception on model '%s' attempt %d: %s",
                        model,
                        attempt + 1,
                        exc,
                    )

        raise RuntimeError("Retry loop exhausted without raising or returning.")


# ── Exceptions ───────────────────────────────────────────────────────────

class AllModelsExhaustedError(Exception):
    """Raised when every model in a fallback chain has failed."""

    def __init__(
        self,
        role: str,
        chain: list[str],
        errors: list[tuple[str, Exception]],
    ) -> None:
        self.role = role
        self.chain = chain
        self.errors = errors
        error_summary = "; ".join(
            f"{model}: {type(exc).__name__}({exc})" for model, exc in errors
        )
        super().__init__(
            f"All {len(chain)} models exhausted for role '{role}'. Errors: [{error_summary}]"
        )


# Legacy alias removed — use AsyncAPIGateway directly.
# (Previously: RateLimitingGateway = AsyncAPIGateway)
