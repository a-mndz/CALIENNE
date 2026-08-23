"""
calienne — Adaptive Multi-Model Reasoning Orchestrator
Capability configuration loader (RFC-002 §5, ADR-005).

Capability configuration lives under ``config/capabilities/`` and is **never**
hardcoded in orchestration logic. This module is the single reader for the five
JSON files:

    model_capabilities.json   — per-model ``max_concurrency`` + per-task_type weights
    provider_limits.json       — per-provider ``parallel_limit`` / rpm / tpm
    pricing.json               — per-model usd_per_million_tokens (input/output)
    routing_defaults.json      — runtime-tunable thresholds (early exit, budget, …)
    prediction_calibration.json — cold-start priors for the Prediction layer

Loading contract (RFC-002 §5):
    * Override the directory with ``CALIENNE_CAPABILITIES_PATH=/abs/path/to/dir``.
    * On load failure (missing file, malformed JSON, bad value) → log a warning,
      fall back to a neutral default (``0.5`` for weights, documented defaults
      elsewhere), and record a ``capability_load_failed`` marker.
    * **Never** raise into the request path (ADR-007 — deterministic fallback).
    * ``_``-prefixed keys (e.g. ``_meta``) are metadata and are ignored.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field, ValidationError

from core.base import CalienneBaseModel

logger = logging.getLogger(__name__)

# ── Locations ────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CAPABILITIES_DIR = _REPO_ROOT / "config" / "capabilities"
_ENV_OVERRIDE = "CALIENNE_CAPABILITIES_PATH"

# ── Neutral fallbacks (RFC-002 §5) ───────────────────────────────────────
NEUTRAL_WEIGHT = 0.5
DEFAULT_MAX_CONCURRENCY = 5  # mirrors rate_limiter._DEFAULT_MAX_CONCURRENCY
DEFAULT_PROVIDER_LIMIT: dict[str, int] = {
    "parallel_limit": 5,
    "requests_per_minute": 30,
    "tokens_per_minute": 200_000,
}
DEFAULT_PRICING: dict[str, float] = {"input": 1.0, "output": 3.0}

# The five capability files, keyed by the short name used in accessors.
_CAPABILITY_FILES: dict[str, str] = {
    "model_capabilities": "model_capabilities.json",
    "provider_limits": "provider_limits.json",
    "pricing": "pricing.json",
    "routing_defaults": "routing_defaults.json",
    "prediction_calibration": "prediction_calibration.json",
}


class ProviderConfig(CalienneBaseModel):
    """Strict external provider-limit contract (RFC-001 §4)."""

    model_config = ConfigDict(extra="forbid")

    parallel_limit: int = Field(default=5, ge=0)
    requests_per_minute: int = Field(default=30, ge=0)
    tokens_per_minute: int = Field(default=200_000, ge=0)


def _strip_meta(data: dict[str, Any]) -> dict[str, Any]:
    """Drop ``_``-prefixed metadata keys (``_meta`` etc.) per RFC-008 §8."""
    return {k: v for k, v in data.items() if not k.startswith("_")}


class CapabilityRegistry:
    """
    Fail-safe reader for ``config/capabilities/*.json``.

    Files are loaded once at construction and cached. Any file that is missing
    or malformed simply yields an empty section plus an entry in
    :pyattr:`load_errors`; accessors then return the documented neutral
    fallback. Construction itself never raises.
    """

    def __init__(self, *, capabilities_dir: str | Path | None = None) -> None:
        if capabilities_dir is not None:
            self._dir = Path(capabilities_dir)
        else:
            override = os.environ.get(_ENV_OVERRIDE)
            self._dir = Path(override) if override else _DEFAULT_CAPABILITIES_DIR

        self._sections: dict[str, dict[str, Any]] = {}
        self._load_errors: dict[str, str] = {}
        for key, filename in _CAPABILITY_FILES.items():
            self._sections[key] = self._load_file(self._dir / filename, key)

    # ── Loading ──────────────────────────────────────────────────────────

    def _load_file(self, path: Path, key: str) -> dict[str, Any]:
        """Load one JSON file; on any failure log + record + return ``{}``."""
        if not path.is_file():
            reason = f"missing file: {path}"
            logger.warning("capability_load_failed (%s): %s", key, reason)
            self._load_errors[key] = reason
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            logger.warning("capability_load_failed (%s): %s", key, reason)
            self._load_errors[key] = reason
            return {}
        if not isinstance(data, dict):
            reason = f"expected object, got {type(data).__name__}"
            logger.warning("capability_load_failed (%s): %s", key, reason)
            self._load_errors[key] = reason
            return {}
        return _strip_meta(data)

    @property
    def load_errors(self) -> dict[str, str]:
        """``{section: reason}`` for every file that failed to load (the
        ``capability_load_failed`` metric surface). Empty when all five load."""
        return dict(self._load_errors)

    @property
    def capability_load_failed(self) -> bool:
        """True if any capability file failed to load."""
        return bool(self._load_errors)

    # ── model_capabilities.json ──────────────────────────────────────────

    def model_weight(self, model: str, task_type: str) -> float:
        """Per-model capability weight for a task type in ``[0, 1]``.

        Falls back to :data:`NEUTRAL_WEIGHT` (0.5) for unknown models, unknown
        task types, or a load failure (RFC-002 §5).
        """
        info = self._sections.get("model_capabilities", {}).get("models", {}).get(model)
        if not isinstance(info, dict):
            return NEUTRAL_WEIGHT
        weight = info.get("weights", {}).get(task_type)
        if isinstance(weight, (int, float)) and 0.0 <= weight <= 1.0:
            return float(weight)
        return NEUTRAL_WEIGHT

    def max_concurrency(self, model: str) -> int:
        """Per-model ``max_concurrency`` (embedded in model_capabilities.json,
        RFC-002 §6). Falls back to :data:`DEFAULT_MAX_CONCURRENCY`."""
        info = self._sections.get("model_capabilities", {}).get("models", {}).get(model)
        if isinstance(info, dict):
            value = info.get("max_concurrency")
            if isinstance(value, int) and value > 0:
                return value
        return DEFAULT_MAX_CONCURRENCY

    def model_weights_for_task(self, task_type: str) -> dict[str, float]:
        """All model→weight pairs for a task type (valid range only)."""
        models = self._sections.get("model_capabilities", {}).get("models", {})
        weights: dict[str, float] = {}
        for model_id, info in models.items():
            if not isinstance(info, dict):
                continue
            weight = info.get("weights", {}).get(task_type)
            if isinstance(weight, (int, float)) and 0.0 <= weight <= 1.0:
                weights[model_id] = float(weight)
        return weights

    # ── provider_limits.json ─────────────────────────────────────────────

    def provider_limit(self, provider: str) -> dict[str, int]:
        """Per-provider limit block (``parallel_limit`` / rpm / tpm).

        Falls back to the file's own ``default`` block, then to
        :data:`DEFAULT_PROVIDER_LIMIT`."""
        section = self._sections.get("provider_limits", {})
        providers = section.get("providers", {})
        block = providers.get(provider)
        if not isinstance(block, dict):
            block = section.get("default")
        if not isinstance(block, dict):
            return dict(DEFAULT_PROVIDER_LIMIT)
        try:
            return ProviderConfig(**{**DEFAULT_PROVIDER_LIMIT, **block}).model_dump()
        except ValidationError:
            return dict(DEFAULT_PROVIDER_LIMIT)

    def provider_parallel_limit(self, provider: str) -> int:
        """Convenience: ``provider_limit(provider)['parallel_limit']``."""
        return self.provider_limit(provider)["parallel_limit"]

    # ── pricing.json ─────────────────────────────────────────────────────

    def pricing(self, model: str) -> dict[str, float]:
        """Per-model input/output price (usd per million tokens).

        Falls back to the file's ``default`` block, then
        :data:`DEFAULT_PRICING`."""
        section = self._sections.get("pricing", {})
        models = section.get("models", {})
        block = models.get(model)
        if not isinstance(block, dict):
            block = section.get("default")
        if not isinstance(block, dict):
            return dict(DEFAULT_PRICING)
        merged = dict(DEFAULT_PRICING)
        for field in ("input", "output"):
            value = block.get(field)
            if isinstance(value, (int, float)) and value >= 0:
                merged[field] = float(value)
        return merged

    # ── routing_defaults.json ────────────────────────────────────────────

    def routing_defaults(self) -> dict[str, Any]:
        """The full routing-defaults block (empty dict on load failure)."""
        return dict(self._sections.get("routing_defaults", {}))

    # ── prediction_calibration.json ──────────────────────────────────────

    def prediction_calibration(self) -> dict[str, Any]:
        """The full prediction-calibration block (empty dict on load failure)."""
        return dict(self._sections.get("prediction_calibration", {}))


# ── Module-level default (constructed once, like versioning.git_commit) ──
_DEFAULT_REGISTRY: CapabilityRegistry | None = None


def get_capability_registry(*, refresh: bool = False) -> CapabilityRegistry:
    """Return a process-wide :class:`CapabilityRegistry`.

    Pass ``refresh=True`` to rebuild (e.g. after changing
    ``CALIENNE_CAPABILITIES_PATH`` in a test)."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None or refresh:
        _DEFAULT_REGISTRY = CapabilityRegistry()
    return _DEFAULT_REGISTRY
