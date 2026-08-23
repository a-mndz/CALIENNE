"""
calienne — Adaptive Multi-Model Reasoning Orchestrator
ResourceManager — the sole owner of concurrency, ceilings, and rate-limit
state (RFC-002 §4, ADR-004, DEC-011).

The scheduler (RFC-003) is a *client* of this module; nothing else computes
parallelism ceilings. This class **composes** the lower-level network-boundary
rate limiter in ``api_gateway/rate_limiter.py`` (health tracking, token buckets,
the global concurrency semaphore) with the declarative capability config in
``config/capabilities/*.json`` (via ``api_gateway/capabilities.py``) and derives
the runtime ``effective_parallel`` ceiling (RFC-002 §6).

Both layers are honored (ADR-004): configuration provides *limits*, this manager
computes *effective concurrency* at runtime as::

    effective_parallel = min(
        provider.parallel_limit,   # provider_limits.json
        model.max_concurrency,     # model_capabilities.json
        system.cpu_limit,
        system.memory_limit,
        budget.parallel_limit,
        rate_limit.remaining,
    )

Scope (RFC-002 §4.3): global with per-route overrides; **no per-tenant in v1**.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from api_gateway.capabilities import CapabilityRegistry, get_capability_registry
from api_gateway.rate_limiter import (
    ProviderResourceManager as RateLimiter,
)
from api_gateway.rate_limiter import (
    extract_provider_key,
)

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────────────────────────
# System ceilings default generously in v1 so the declarative provider/model
# config is the binding constraint. Real host-derived CPU/RAM throttling lands
# with Step 19's HostPrimitives (RFC-005 §3) — until then these are wide.
_CPU_PARALLEL_FACTOR = 4
_MIN_CPU_PARALLEL = 4
_DEFAULT_MEMORY_PARALLEL_CEILING = 32
_DEFAULT_BUDGET_PARALLEL = 32
# When a node carries no explicit model, resolve one from its coarse tier.
_TIER_MODEL_DEFAULTS: dict[str, str] = {
    "default": "google/gemini-2.5-flash",
    "cheap": "groq/llama-3.1-8b-instant",
    "standard": "groq/llama-3.3-70b-versatile",
    "strong": "openrouter/anthropic/claude-3.5-sonnet",
    "critical": "openrouter/anthropic/claude-3.5-sonnet",
}


@dataclass
class Reservation:
    """A granted concurrency slot returned by :meth:`ResourceManager.acquire`."""

    node_id: str
    provider: str
    model: str
    parallel_limit: int
    granted: bool = True
    reason: str = ""


@dataclass
class ResourceState:
    """Immutable-ish snapshot fed to metrics / dashboard / predictions
    (RFC-002 §4.2 ``snapshot()``)."""

    effective_parallel: int
    concurrency_active: int
    connection_pool_size: int
    cpu_count: int
    cpu_parallel_ceiling: int
    memory_parallel_ceiling: int
    rate_limit_remaining: int | None
    capability_load_failed: bool
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "effective_parallel": self.effective_parallel,
            "concurrency_active": self.concurrency_active,
            "connection_pool_size": self.connection_pool_size,
            "cpu_count": self.cpu_count,
            "cpu_parallel_ceiling": self.cpu_parallel_ceiling,
            "memory_parallel_ceiling": self.memory_parallel_ceiling,
            "rate_limit_remaining": self.rate_limit_remaining,
            "capability_load_failed": self.capability_load_failed,
            **self.extra,
        }


class ResourceManager:
    """Owns concurrency ceilings; the scheduler pulls its cap from here."""

    def __init__(
        self,
        *,
        capabilities: CapabilityRegistry | None = None,
        rate_limiter: RateLimiter | None = None,
        cpu_parallel_ceiling: int | None = None,
        memory_parallel_ceiling: int = _DEFAULT_MEMORY_PARALLEL_CEILING,
        default_budget_parallel: int = _DEFAULT_BUDGET_PARALLEL,
    ) -> None:
        self._capabilities = capabilities or get_capability_registry()
        # Compose the network-boundary rate limiter (health, token buckets,
        # the global concurrency semaphore) rather than duplicating it.
        self._rate_limiter = rate_limiter or RateLimiter()
        self._cpu_count = os.cpu_count() or _MIN_CPU_PARALLEL
        if cpu_parallel_ceiling is not None:
            self._cpu_parallel_ceiling = max(1, cpu_parallel_ceiling)
        else:
            self._cpu_parallel_ceiling = max(
                _MIN_CPU_PARALLEL, self._cpu_count * _CPU_PARALLEL_FACTOR
            )
        self._memory_parallel_ceiling = max(1, memory_parallel_ceiling)
        self._default_budget_parallel = max(1, default_budget_parallel)
        self._active: int = 0

    # ── effective_parallel (RFC-002 §6) ──────────────────────────────────

    def effective_parallel(
        self,
        *,
        provider: str,
        model: str,
        budget_parallel: int | None = None,
        rate_limit_remaining: int | None = None,
    ) -> int:
        """Compute the runtime concurrency ceiling for one (provider, model).

        Honors **all six** terms of the RFC-002 §6 formula; the smallest wins.
        A neutral capability-load failure falls back to config defaults, never
        raising (ADR-007). Explicit zero headroom remains zero.
        """
        provider_limit = self._capabilities.provider_parallel_limit(provider)
        model_limit = self._capabilities.max_concurrency(model)
        budget_limit = (
            budget_parallel if budget_parallel is not None else self._default_budget_parallel
        )
        rl_remaining = (
            rate_limit_remaining
            if rate_limit_remaining is not None
            else self._rate_limit_remaining(provider)
        )

        candidates = [
            provider_limit,
            model_limit,
            self._cpu_parallel_ceiling,
            self._memory_parallel_ceiling,
            budget_limit,
            rl_remaining,
        ]
        if any(c == 0 for c in candidates):
            return 0
        positive = [c for c in candidates if isinstance(c, int) and c > 0]
        return max(1, min(positive)) if positive else 1

    def _rate_limit_remaining(self, provider: str) -> int:
        """Remaining request headroom for a provider from the token bucket.

        Uses the underlying rate limiter's bucket if one is configured; else a
        wide default so the config limits dominate (v1)."""
        bucket = self._rate_limiter.provider_limits.get(provider)
        if bucket is not None:
            try:
                return max(0, int(bucket.tokens))
            except (TypeError, ValueError):
                return self._default_budget_parallel
        # No bucket configured yet → treat as unconstrained relative to config.
        return self._default_budget_parallel

    # ── Node resolution helpers ──────────────────────────────────────────

    @staticmethod
    def _resolve_model(node: Any) -> str:
        """Best-effort model id for a node. Nodes carry a coarse ``model_tier``
        in v1; explicit per-node models arrive with later provider wiring."""
        explicit = getattr(node, "model", None)
        if isinstance(explicit, str) and explicit:
            return explicit
        tier = getattr(node, "model_tier", "default") or "default"
        return _TIER_MODEL_DEFAULTS.get(tier, _TIER_MODEL_DEFAULTS["default"])

    # ── Public API (RFC-002 §4.2) ────────────────────────────────────────

    async def acquire(self, node: Any) -> Reservation:
        """Reserve a concurrency slot for ``node``. Never raises; a rejection
        is expressed as ``Reservation(granted=False, reason=...)``."""
        model = self._resolve_model(node)
        provider = extract_provider_key(model)
        parallel = self.effective_parallel(provider=provider, model=model)
        node_id = getattr(node, "task_id", "") or ""
        if self._active >= parallel:
            return Reservation(
                node_id=node_id,
                provider=provider,
                model=model,
                parallel_limit=parallel,
                granted=False,
                reason=f"effective_parallel={parallel} reached (active={self._active})",
            )
        self._active += 1
        return Reservation(
            node_id=node_id, provider=provider, model=model, parallel_limit=parallel
        )

    async def release(self, reservation: Reservation | None) -> None:
        """Release a previously granted reservation. Idempotent / safe."""
        if reservation is None or not reservation.granted:
            return
        if self._active <= 0:
            logger.warning("release() called with no active reservations — ignoring.")
            return
        self._active -= 1

    def snapshot(self) -> ResourceState:
        """Current resource state (RFC-002 §4.2). Fed to dashboard metrics."""
        return ResourceState(
            effective_parallel=self._cpu_parallel_ceiling,
            concurrency_active=self._active,
            connection_pool_size=self._rate_limiter.GLOBAL_CONCURRENCY_LIMIT,
            cpu_count=self._cpu_count,
            cpu_parallel_ceiling=self._cpu_parallel_ceiling,
            memory_parallel_ceiling=self._memory_parallel_ceiling,
            rate_limit_remaining=None,
            capability_load_failed=self._capabilities.capability_load_failed,
        )

    def recompute_plan(self, graph: Any, prediction: Any = None) -> str:
        """Decide whether ``graph`` can run as-is (RFC-002 §4.2).

        Returns ``"ok"``, ``"downgrade"``, or ``"reject"`` — deterministic and
        conservative. A predicted token upper bound above the memory ceiling
        triggers a downgrade; a zero effective ceiling triggers a reject.
        """
        nodes = getattr(graph, "nodes", []) or []
        if not nodes:
            return "reject"

        # If any node's effective parallel collapses to zero the graph cannot
        # make progress (e.g. a dead provider zeroed the rate limit).
        for node in nodes:
            model = self._resolve_model(node)
            provider = extract_provider_key(model)
            if self.effective_parallel(provider=provider, model=model) < 1:
                return "reject"

        upper = self._prediction_token_upper_bound(prediction)
        if upper is not None and upper > self._memory_token_ceiling():
            return "downgrade"
        return "ok"

    def scheduler_concurrency_limit(self, graph: Any) -> int:
        """The semaphore cap the scheduler (RFC-003 §4) should use for ``graph``.

        Grounded in the system CPU ceiling and the underlying global limit, then
        capped by the node count (a graph never needs more workers than nodes).
        Preserves the ``_StubResourceManager`` contract it replaces (floor 1).
        """
        nodes = getattr(graph, "nodes", []) or []
        node_limits = []
        for node in nodes:
            model = self._resolve_model(node)
            provider = extract_provider_key(model)
            node_limits.append(self.effective_parallel(provider=provider, model=model))
        if node_limits and min(node_limits) == 0:
            return 1
        base = min(
            self._cpu_parallel_ceiling,
            self._rate_limiter.GLOBAL_CONCURRENCY_LIMIT,
            *(node_limits or [self._default_budget_parallel]),
        )
        return max(1, min(base, max(1, len(nodes))))

    # ── Internal ─────────────────────────────────────────────────────────

    def _memory_token_ceiling(self) -> int:
        """Coarse token ceiling used by :meth:`recompute_plan`. Derived from the
        default budget so a request far above the seeded budget downgrades."""
        defaults = self._capabilities.routing_defaults().get("token_budget", {})
        total = defaults.get("default_total_tokens")
        if isinstance(total, int) and total > 0:
            # Allow a generous multiple before forcing a downgrade.
            return total * 8
        return 120_000

    @staticmethod
    def _prediction_token_upper_bound(prediction: Any) -> int | None:
        """Extract a token upper bound (value + std_dev) from a Prediction, if
        present. Tolerant of shape — returns ``None`` when unavailable."""
        if prediction is None:
            return None
        interval = getattr(prediction, "expected_tokens", None)
        if interval is None:
            return None
        upper = getattr(interval, "upper_bound", None)
        if isinstance(upper, (int, float)) and upper > 0:
            return int(upper)
        value = getattr(interval, "value", None)
        std = getattr(interval, "std_dev", 0) or 0
        if isinstance(value, (int, float)):
            return int(value + std)
        return None
