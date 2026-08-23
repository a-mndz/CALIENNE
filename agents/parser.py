"""
calienne — Adaptive Multi-Model Reasoning Orchestrator
Structural integrity layer for LLM JSON output.

This module sits between raw LLM responses and the typed Pydantic schemas
defined in ``core.schemas``.  It implements a **three-stage** parse pipeline:

1. **Native parse** — ``json.loads`` on the raw string.
2. **Repair parse** — ``json_repair.repair_json`` for malformed JSON
   (unclosed brackets, trailing commas, unquoted keys, etc.).
3. **Safe fallback** — a standardised error dictionary so downstream
   consumers never receive an exception or ``None``.

Every successful parse is validated through the caller-supplied Pydantic
model class, giving full type/constraint enforcement.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from json_repair import repair_json
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# Generic bound so callers get the right return type from their IDE.
T = TypeVar("T", bound=BaseModel)

# ── Sentinel error dictionary ────────────────────────────────────────────
# Mirrors the AgentOutput shape so the pipeline never has to special-case
# a parse failure — it looks like a maximally-uncertain agent response.

_ERROR_TEMPLATE: dict[str, Any] = {
    "reasoning_steps": ["PARSE FAILURE — the raw LLM response could not be "
                        "decoded into valid JSON or repaired into a conformant "
                        "schema instance."],
    "answer": "ERROR: Unable to parse LLM output.",
    "confidence": 0.0,
}


def _build_error_dict(
    *,
    raw: str,
    stage: str,
    exception: Exception,
) -> dict[str, Any]:
    """
    Construct a standardised error dictionary that is safe to pass
    downstream in place of a real agent output.

    Parameters
    ----------
    raw:
        The original (truncated) LLM string, kept for debugging.
    stage:
        Human-readable label for the pipeline stage that failed
        (e.g. ``'json.loads'``, ``'json_repair'``, ``'pydantic'``).
    exception:
        The exception instance that triggered the fallback.

    Returns
    -------
    dict[str, Any]
        A dict matching the ``AgentOutput`` shape with confidence 0.0.
    """
    truncated = raw[:500] if len(raw) > 500 else raw

    error = dict(_ERROR_TEMPLATE)
    error["_parse_error"] = {
        "stage": stage,
        "error_type": type(exception).__name__,
        "error_detail": str(exception)[:300],
        "raw_snippet": truncated,
    }

    logger.error(
        "Parse failure at stage '%s' (%s): %s — raw snippet: %.200s",
        stage,
        type(exception).__name__,
        exception,
        truncated,
    )
    return error


# ── Public API ───────────────────────────────────────────────────────────


def parse_and_repair(
    raw_llm_string: str,
    target_schema_class: type[T],
) -> T | dict[str, Any]:
    """
    Parse raw LLM output into a validated Pydantic model instance.

    Pipeline
    --------
    1. Try ``json.loads(raw_llm_string)``.
    2. On ``JSONDecodeError``, pass the string through
       ``repair_json`` and load the repaired result.
    3. Validate the resulting dict against *target_schema_class*.
    4. On any failure, return a safe error dictionary instead of
       raising — the calienne pipeline must never crash due to
       malformed model output.

    Parameters
    ----------
    raw_llm_string:
        The raw string returned by the LLM (expected to be JSON).
    target_schema_class:
        A Pydantic ``BaseModel`` subclass (e.g. ``AgentOutput``)
        used for structural + type validation.

    Returns
    -------
    T | dict[str, Any]
        A validated model instance on success, or a standardised
        error dictionary on failure.  The error dict always contains
        ``reasoning_steps``, ``answer``, ``confidence`` (0.0), and
        a ``_parse_error`` metadata block for diagnostics.

    Examples
    --------
    >>> from core.schemas import AgentOutput
    >>> result = parse_and_repair('{"reasoning_steps":["step"],"answer":"yes","confidence":0.9}', AgentOutput)
    >>> isinstance(result, AgentOutput)
    True

    >>> bad = parse_and_repair("totally not json", AgentOutput)
    >>> isinstance(bad, dict) and bad["confidence"] == 0.0
    True
    """
    if not isinstance(raw_llm_string, str) or not raw_llm_string.strip():
        return _build_error_dict(
            raw=raw_llm_string if isinstance(raw_llm_string, str) else repr(raw_llm_string),
            stage="pre-check",
            exception=ValueError("Received empty or non-string input."),
        )

    # ── Stage 1: native JSON parse ───────────────────────────────────
    parsed: dict[str, Any] | None = None

    try:
        parsed = json.loads(raw_llm_string)
        logger.debug("Stage 1 (json.loads) succeeded.")
    except json.JSONDecodeError as exc:
        logger.debug("Stage 1 (json.loads) failed: %s — attempting repair.", exc)

        # ── Stage 2: repair malformed JSON ───────────────────────────
        try:
            repaired_string = repair_json(raw_llm_string, return_objects=False)
            parsed = json.loads(repaired_string)
            logger.info("Stage 2 (json_repair) recovered valid JSON.")
        except (json.JSONDecodeError, TypeError, ValueError) as repair_exc:
            return _build_error_dict(
                raw=raw_llm_string,
                stage="json_repair",
                exception=repair_exc,
            )

    # Guard: repair_json might return a non-dict (e.g. a list or scalar).
    if not isinstance(parsed, dict):
        return _build_error_dict(
            raw=raw_llm_string,
            stage="type_check",
            exception=TypeError(
                f"Expected a JSON object (dict), got {type(parsed).__name__}."
            ),
        )

    # ── Stage 3: Pydantic validation ─────────────────────────────────
    try:
        validated = target_schema_class.model_validate(parsed)
        logger.debug(
            "Stage 3 (Pydantic %s) validation passed.", target_schema_class.__name__,
        )
        return validated
    except ValidationError as val_exc:
        return _build_error_dict(
            raw=raw_llm_string,
            stage=f"pydantic ({target_schema_class.__name__})",
            exception=val_exc,
        )
