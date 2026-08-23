"""
calienne — Adaptive Multi-Model Reasoning Orchestrator
Provider strategy: mode-aware model selection with per-role fallback chains.

This module maps each system *role* (generation, breaker, judge) to a
prioritised list of LLM model identifiers.  Three operating modes govern
which models are considered:

* **FREE**   — community / open-weight models only (no API credit cost).
* **HYBRID** — prefers paid models but falls back to free alternatives.
* **PAID**   — premium, commercial-grade models with the highest quality.

The orchestrator calls :meth:`ProviderStrategy.get_model_chain` to obtain
an ordered list of models to attempt for a given role.  The first element
is the *primary* pick; subsequent elements are fallbacks tried in order
if an upstream call fails or times out.

RFC-002 §7 note: the capability matrix (``MODEL_CAPABILITY_WEIGHTS``) is **not**
inlined here.  It lives in ``config/capabilities/model_capabilities.json`` and is
read through ``api_gateway/capabilities.py`` (per ADR-005 — capability files are
never hardcoded).  :meth:`ProviderStrategy.get_model_chain_for_plan` consults that
loader to re-rank a role's chain by the plan's ``task_type`` weights and to widen
the chain for ``high`` / ``critical`` complexity.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List

from api_gateway.capabilities import CapabilityRegistry, get_capability_registry

logger = logging.getLogger(__name__)

# ── Route-aware role aliases (RFC-002 §7) ────────────────────────────────
# Map the seven route-aware role names onto the three underlying model-map
# roles so ``get_model_chain`` keeps working while callers can request a
# route-specific role. Generation routes → ``generation``; judges → ``judge``.
ROUTE_ROLE_ALIASES: Dict[str, str] = {
    "coding_generation": "generation",
    "research_generation": "generation",
    "math_generation": "generation",
    "creative_generation": "generation",
    "cheap_judge": "judge",
    "standard_judge": "judge",
    "critical_judge": "judge",
}

# Which generation role a task_type maps to (for get_model_chain_for_plan).
_TASK_TYPE_TO_GENERATION_ROLE: Dict[str, str] = {
    "coding": "coding_generation",
    "research": "research_generation",
    "math": "math_generation",
    "creative": "creative_generation",
    "general": "generation",
}

# Complexity → how many models the plan chain should carry (primary + fallbacks).
_COMPLEXITY_CHAIN_DEPTH: Dict[str, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


# ── Operating Modes ──────────────────────────────────────────────────────


class StrategyMode(str, Enum):
    """Supported provider-strategy operating modes."""

    FREE = "FREE"
    HYBRID = "HYBRID"
    PAID = "PAID"


# ── Model Maps ───────────────────────────────────────────────────────────
# Each map is a ``{role: [primary, fallback_1, …]}`` dictionary.
# Models are specified as OpenRouter-style identifiers so the downstream
# ``provider_pool`` can route them to the correct gateway.

# Verified alive 2026-08-21 (research/CALIENNE_RESEARCH_2026-08-21.md, Tier 0.3):
# - github/* routes retired 30 Jul 2026 — removed.
# - Groq's production list contains no Llama models; llama-3.3-70b-versatile and
#   llama-3.1-8b-instant 404. Replaced with Groq-hosted openai/gpt-oss-*,
#   which are also the only Groq models eligible for the 50% cached-input
#   discount (min 128–1,024 token prefix, 2h TTL).
# - openrouter/anthropic/claude-3.5-sonnet retired 28 Oct 2025. PAID primary
#   repointed to claude-sonnet-5 (generation/breaker) and claude-opus-5 (judge).
# Live-verified 2026-08-22 (first live capture attempt — see
# research/AUDIT_2026-08-22-live-capture notes):
# - google/gemini-2.5-* is "no longer available to new users" per the API;
#   this key's live text models are the 3.x line (verified via /v1beta/models).
# - unli/* returns HTTP 401 on every model (stale key) — dropped everywhere.
# - openai/gpt-4o-mini returned HTTP 429 (quota) on the same night; kept only
#   as a PAID breaker middle hop.
# - Groq accepts ~20KB request bodies but rejects ~30KB (HTTP 413): the
#   per-call runtime-contract layer was slimmed to the output-shaping
#   contracts (agents/prompt_manager.py) so Groq stays a viable fallback.
# - Google endpoints accept the full layered prompt.
FREE_MODELS: Dict[str, List[str]] = {
    "generation": [
        "google/gemini-3.5-flash-lite",
        "groq/openai/gpt-oss-120b",
        "groq/openai/gpt-oss-20b",
    ],
    "breaker": [
        "google/gemini-3.5-flash-lite",
        "groq/openai/gpt-oss-20b",
    ],
    "judge": [
        "google/gemini-3.5-flash-lite",
        "groq/openai/gpt-oss-120b",
    ],
}

HYBRID_MODELS: Dict[str, List[str]] = {
    "generation": [
        "google/gemini-3.7-flash",
        "groq/openai/gpt-oss-120b",
        "google/gemini-3.5-flash-lite",
    ],
    "breaker": [
        "google/gemini-3.5-flash-lite",
        "groq/openai/gpt-oss-20b",
    ],
    "judge": [
        "google/gemini-3.7-flash",
        "groq/openai/gpt-oss-120b",
        "google/gemini-3.5-flash-lite",
    ],
}

PAID_MODELS: Dict[str, List[str]] = {
    "generation": [
        "openrouter/anthropic/claude-sonnet-5",
        "google/gemini-pro-latest",
        "google/gemini-3.7-flash",
    ],
    "breaker": [
        "google/gemini-3.5-flash-lite",
        "openai/gpt-4o-mini",
        "openrouter/anthropic/claude-sonnet-5",
    ],
    "judge": [
        "openrouter/anthropic/claude-opus-5",
        "google/gemini-pro-latest",
        "google/gemini-3.7-flash",
    ],
}

# ── Lookup Table ─────────────────────────────────────────────────────────

_MODE_TO_MAP: Dict[StrategyMode, Dict[str, List[str]]] = {
    StrategyMode.FREE: FREE_MODELS,
    StrategyMode.HYBRID: HYBRID_MODELS,
    StrategyMode.PAID: PAID_MODELS,
}


# ── Strategy Class ───────────────────────────────────────────────────────


class ProviderStrategy:
    """
    Mode-aware model selector with per-role fallback chains.

    Parameters
    ----------
    mode:
        One of ``'FREE'``, ``'HYBRID'``, or ``'PAID'`` (case-insensitive).

    Raises
    ------
    ValueError
        If *mode* is not a recognised :class:`StrategyMode`.

    Examples
    --------
    >>> strategy = ProviderStrategy("HYBRID")
    >>> strategy.get_model_chain("generation")
    ['openrouter/anthropic/claude-sonnet-4.6', 'openrouter/openai/gpt-4o-mini', 'openrouter/meta-llama/llama-3-8b-instruct']
    """  # noqa: E501

    def __init__(self, mode: str, *, capabilities: CapabilityRegistry | None = None) -> None:
        try:
            self._mode = StrategyMode(mode.upper())
        except ValueError:
            valid = ", ".join(m.value for m in StrategyMode)
            raise ValueError(
                f"Unknown strategy mode '{mode}'. Must be one of: {valid}."
            ) from None

        self._model_map = {
            role: list(models) for role, models in _MODE_TO_MAP[self._mode].items()
        }
        self._disabled_models: set[str] = set()
        self._capabilities = capabilities or get_capability_registry()
        logger.info("ProviderStrategy initialised in %s mode.", self._mode.value)

    def set_mode(self, mode: str) -> None:
        """Switch the active operating mode."""
        try:
            self._mode = StrategyMode(mode.upper())
            self._model_map = {
                role: list(models) for role, models in _MODE_TO_MAP[self._mode].items()
            }
            self._disabled_models.clear()
            logger.info("ProviderStrategy switched to %s mode.", self._mode.value)
        except ValueError:
            raise ValueError(f"Unknown strategy mode '{mode}'.") from None

    def add_model(self, model: str, role: str = "generation") -> bool:
        """Dynamically register a model into the active strategy chain for *role*."""
        chain = self._model_map.setdefault(role, [])
        if model not in chain:
            chain.append(model)
            logger.info("Added model '%s' to role '%s' in %s mode.", model, role, self._mode.value)
            return True
        return False

    def set_primary_model(self, role: str, model: str) -> bool:
        """Designate *model* as the primary (index 0) model for *role* fallback chain."""
        role = ROUTE_ROLE_ALIASES.get(role, role)
        chain = self._model_map.setdefault(role, [])
        if model in chain:
            chain.remove(model)
        chain.insert(0, model)
        self._disabled_models.discard(model)
        logger.info("Set '%s' as primary model for role '%s'.", model, role)
        return True

    def set_model_chain(self, role: str, chain: list[str]) -> bool:
        """Replace the ordered model fallback chain for a given role."""
        actual_r = ROUTE_ROLE_ALIASES.get(role, role)
        self._model_map[actual_r] = [m.strip() for m in chain if m.strip()]
        logger.info("Updated model chain for role '%s': %s", role, self._model_map[actual_r])
        return True

    def remove_model(self, model: str, role: str | None = None) -> bool:
        """Remove a model from a specific role chain, or all role chains if role is None."""
        removed = False
        roles_to_check = [role] if role else list(self._model_map.keys())
        for r in roles_to_check:
            actual_r = ROUTE_ROLE_ALIASES.get(r, r)
            chain = self._model_map.get(actual_r, [])
            if model in chain:
                chain.remove(model)
                removed = True
        self._disabled_models.discard(model)
        return removed

    def set_model_roles(self, model: str, roles: list[str]) -> bool:
        """Ensure *model* is in chains for the given roles and removed from others."""
        target_roles = {ROUTE_ROLE_ALIASES.get(r, r) for r in roles}
        for role_key in list(self._model_map.keys()):
            chain = self._model_map[role_key]
            if role_key in target_roles:
                if model not in chain:
                    chain.append(model)
            else:
                if model in chain:
                    chain.remove(model)
        return True

    def get_model_roles(self, model: str) -> list[str]:
        """Return list of roles currently containing *model*."""
        roles = []
        for role_key, chain in self._model_map.items():
            if model in chain:
                roles.append(role_key)
        return roles

    def set_model_enabled(self, model: str, enabled: bool) -> bool:
        """Enable or disable one exact model identifier across role chains."""
        if not any(model in chain for chain in self._model_map.values()):
            return False
        if enabled:
            self._disabled_models.discard(model)
        else:
            self._disabled_models.add(model)
        return True

    def is_model_enabled(self, model: str) -> bool:
        return model not in self._disabled_models

    # ── Public Properties ────────────────────────────────────────────

    @property
    def mode(self) -> StrategyMode:
        """The active operating mode."""
        return self._mode

    @property
    def supported_roles(self) -> list[str]:
        """Roles for which model chains are defined in the active mode."""
        return list(self._model_map.keys())

    def get_configured_model_chain(self, role: str) -> list[str]:
        """Return configured models including temporarily disabled entries."""
        role = ROUTE_ROLE_ALIASES.get(role, role)
        return list(self._model_map.get(role, []))

    # ── Core API ─────────────────────────────────────────────────────

    def get_model_chain(self, role: str) -> list[str]:
        """
        Return a fallback-ordered list of models for *role*.

        The first element is the primary model; subsequent elements are
        fallbacks tried in sequence if earlier candidates fail.

        The returned list always contains **at least two** entries
        (primary + ≥1 fallback).  If the active mode's map for a role
        somehow contains fewer than two models, models from lower-cost
        tiers are appended automatically.

        Parameters
        ----------
        role:
            System role identifier — typically ``'generation'``,
            ``'breaker'``, or ``'judge'``.

        Returns
        -------
        list[str]
            Non-empty, ordered list of model identifiers.

        Raises
        ------
        ValueError
            If *role* is not defined in **any** mode's model map.
        """
        # Route-aware role names (RFC-002 §7) alias onto the underlying
        # generation/judge roles so callers can request e.g. 'critical_judge'.
        role = ROUTE_ROLE_ALIASES.get(role, role)
        chain = [
            model
            for model in self._model_map.get(role, [])
            if model not in self._disabled_models
        ]

        # If the role is entirely absent from the active map, try to pull
        # models from another tier so the system degrades gracefully.
        if not chain:
            chain = self._cross_tier_fallback(role)

        if not chain:
            available = ", ".join(
                sorted(
                    {r for m in _MODE_TO_MAP.values() for r in m}
                )
            )
            raise ValueError(
                f"Role '{role}' is not defined in any strategy mode. "
                f"Available roles: {available}."
            )

        # Guarantee at least two entries (primary + fallback).
        if len(chain) < 2:
            extras = self._cross_tier_fallback(role, exclude=chain)
            chain.extend(extras[: 2 - len(chain)])

        logger.debug(
            "Model chain for role '%s' (%s mode): %s",
            role,
            self._mode.value,
            chain,
        )
        return chain

    def get_model_chain_for_plan(self, plan: Any) -> list[str]:
        """
        Return a plan-aware, capability-ranked model chain (RFC-002 §7).

        Unlike :meth:`get_model_chain` (role-only), this consults the plan's
        ``task_type`` and ``complexity`` to:

        * pick the route-specific generation role
          (``coding_generation`` / ``research_generation`` / …),
        * **re-rank** the candidate models best-first by their per-``task_type``
          capability weight from ``model_capabilities.json`` (via
          ``api_gateway/capabilities.py``), so a coding request prefers the
          strongest coding model available in the active tier, and
        * **size** the chain by complexity — ``low`` requests get a single
          cheap primary, ``critical`` requests get the full fallback depth.

        ``plan`` is duck-typed: any object exposing ``task_type`` and
        ``complexity`` attributes (e.g. a ``TaskProfile``) works. Missing
        attributes fall back to ``general`` / ``medium``. Never raises — an
        unknown route degrades to the plain ``generation`` chain.
        """
        task_type = getattr(plan, "task_type", "general") or "general"
        complexity = getattr(plan, "complexity", "medium") or "medium"

        role = _TASK_TYPE_TO_GENERATION_ROLE.get(task_type, "generation")
        chain = self.get_model_chain(role)

        # Re-rank by capability weight for this task_type (stable: unknown
        # models keep the neutral 0.5 and hold their relative order).
        weights = {m: self._capabilities.model_weight(m, task_type) for m in chain}
        ranked = sorted(chain, key=lambda m: weights[m], reverse=True)

        depth = _COMPLEXITY_CHAIN_DEPTH.get(complexity, 2)
        # Always keep at least the primary; never exceed what the chain holds.
        depth = max(1, min(depth, len(ranked)))
        selected = ranked[:depth]

        logger.debug(
            "Plan chain for task_type=%s complexity=%s (%s mode): %s",
            task_type,
            complexity,
            self._mode.value,
            selected,
        )
        return selected

    # ── Private Helpers ──────────────────────────────────────────────

    def _cross_tier_fallback(
        self,
        role: str,
        exclude: list[str] | None = None,
    ) -> list[str]:
        """
        Collect models for *role* from **other** tiers (FREE → PAID order)
        that are not already in *exclude*.

        This ensures a fallback chain can always be constructed even when
        the active mode has a thin mapping for a particular role.
        """
        exclude_set = set(exclude or [])

        # Walk tiers in cheapest-first order so free models are preferred
        # as ultimate fallbacks regardless of the active mode.
        tier_order = [StrategyMode.FREE, StrategyMode.HYBRID, StrategyMode.PAID]

        result: list[str] = []
        for tier in tier_order:
            if tier is self._mode:
                continue  # Already consumed.
            for model in _MODE_TO_MAP[tier].get(role, []):
                if (
                    model not in exclude_set
                    and model not in result
                    and model not in self._disabled_models
                ):
                    result.append(model)
        return result
