"""Smart RAG — source ranking and route-gated retrieval (RFC-004 §3).

The v1 retrieval layer is deterministic and contract-driven:

* Every retrieved record is shaped as a :class:`SourceCandidate` whose
  ``final_score`` is a weighted sum of four sub-scores, computed with the
  formula mandated by RFC-004 §3.2:

      ``final = relevance*0.4 + credibility*0.25 + freshness*0.15 + consensus*0.2``

* Retrieval is **route-gated** (RFC-004 §3.2): required for ``research``,
  optional for ``general``, off for ``coding`` / ``math`` / ``creative`` —
  unless the uncertainty engine explicitly triggered retrieval for that
  request.

* The actual backend is a pluggable ``RetrievalProvider``. v1 ships a
  :class:`DeterministicRetrievalProvider` (test-only; never queries the
  network) and a :class:`InMemoryRetrievalProvider` for local development.
  All providers are async-first; sync providers must be wrapped in
  :func:`asyncio.to_thread` by the provider itself.

* The retrieval pipeline never raises into the request path. A failing
  provider logs and returns an empty list — the
  :class:`~orchestrator.context_manager.ContextManager` and
  :class:`~orchestrator.execution_manager.ExecutionManager` degrade
  gracefully (no snippets, no telemetry claim). This is the ADR-007
  "LLM → Validation → Fallback" discipline applied to retrieval.

* The whole module is gated by :class:`~orchestrator.feature_flags.FeatureFlags.rag`
  (``AETHERIS_ENABLE_RAG``). When the flag is off, callers receive an empty
  :class:`RetrievalResult` regardless of the request's route — keeping the
  default behaviour identical to the Step 7 contract.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime, timezone
from typing import Any

from pydantic import Field

from core.base import AetherisBaseModel
from core.schemas import TaskProfile

LOGGER = logging.getLogger(__name__)


# Default weights pinned to RFC-004 §3.2. The loader prefers these and
# falls back to ``config/capabilities/routing_defaults.json`` values when
# present (see :func:`load_routing_defaults`).
DEFAULT_RANKING_WEIGHTS: dict[str, float] = {
    "relevance": 0.40,
    "credibility": 0.25,
    "freshness": 0.15,
    "consensus": 0.20,
}

# RFC-004 §3.2: route gating table. "required" always triggers retrieval;
# "optional" only triggers when the task profile asks for it; "off" never
# triggers unless the uncertainty engine forces it.
ROUTE_GATING: dict[str, str] = {
    "research": "required",
    "general": "optional",
    "coding": "off",
    "math": "off",
    "creative": "off",
}

# When a ``StageAssessment.evidence_count`` should bump up because the
# retrieval layer selected a source, this is the bump size. Step 15 keeps
# the public StageAssessment surface read-only (no schema change) — the
# value is reported in the retrieval result and consumed by callers.
EVIDENCE_BUMP_PER_SOURCE: int = 1


# ── Schemas ──────────────────────────────────────────────────────────────


class SourceCandidate(AetherisBaseModel):
    """A retrieved source scored on four axes (RFC-004 §3.1)."""

    url: str | None = None
    title: str | None = None
    excerpt: str = ""
    credibility_score: float = 0.0
    freshness_score: float = 0.0
    relevance_score: float = 0.0
    consensus_score: float = 0.0
    final_score: float = 0.0

    def clamped(self) -> "SourceCandidate":
        """Return a copy with every score clamped into ``[0.0, 1.0]``."""

        return self.model_copy(
            update={
                "credibility_score": _clamp01(self.credibility_score),
                "freshness_score": _clamp01(self.freshness_score),
                "relevance_score": _clamp01(self.relevance_score),
                "consensus_score": _clamp01(self.consensus_score),
                "final_score": _clamp01(self.final_score),
            }
        )


class RetrievalRequest(AetherisBaseModel):
    """A retrieval request shaped per RFC-004 §3 contract."""

    query: str = ""
    task_profile: TaskProfile | None = None
    node_id: str | None = None
    limit: int = 5
    uncertainty_triggered: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(AetherisBaseModel):
    """The deterministic shape returned to callers (RFC-004 §3)."""

    sources: list[SourceCandidate] = Field(default_factory=list)
    selected_count: int = 0
    retrieval_attempted: bool = False
    retrieval_skipped_reason: str | None = None
    route_gating: str = "off"
    weights: dict[str, float] = Field(default_factory=dict)
    evidence_bump: int = 0
    telemetry: dict[str, Any] = Field(default_factory=dict)


# ── Provider protocol ────────────────────────────────────────────────────


RetrievalProviderCallable = Callable[[RetrievalRequest], Awaitable[Iterable[dict[str, Any] | SourceCandidate]]]  # noqa: E501


class RetrievalProvider:
    """Async interface every retrieval backend must implement."""

    async def retrieve(self, request: RetrievalRequest) -> list[SourceCandidate]:
        raise NotImplementedError


# ── Built-in providers ──────────────────────────────────────────────────


class InMemoryRetrievalProvider(RetrievalProvider):
    """Local, deterministic provider used for v1 development and tests.

    Each record is a ``dict`` with at least ``content``/``excerpt`` and the
    four score axes. If the scores are missing, the provider computes
    deterministic defaults (zero) — the caller is expected to populate the
    scores upstream of the scorer.
    """

    def __init__(self, records: Iterable[dict[str, Any]] | None = None) -> None:
        self._records: list[dict[str, Any]] = list(records or [])

    def add(self, record: dict[str, Any]) -> None:
        self._records.append(record)

    async def retrieve(self, request: RetrievalRequest) -> list[SourceCandidate]:
        candidates: list[SourceCandidate] = []
        for record in self._records:
            candidates.append(_record_to_candidate(record))
        return candidates


class DeterministicRetrievalProvider(RetrievalProvider):
    """Provider that never returns anything — the "no retrieval" baseline.

    This is the default v1 provider. It exists so the retrieval layer can
    be wired in tests, in shadow mode, and in environments that do not have
    a configured RAG backend, without injecting fabricated evidence.
    """

    async def retrieve(self, request: RetrievalRequest) -> list[SourceCandidate]:
        return []


class StaticOverrideProvider(RetrievalProvider):
    """Provider that returns a fixed list — handy for unit tests."""

    def __init__(self, sources: Iterable[SourceCandidate | dict[str, Any]]) -> None:
        self._sources: list[SourceCandidate] = [
            source if isinstance(source, SourceCandidate) else _record_to_candidate(source)
            for source in sources
        ]

    async def retrieve(self, request: RetrievalRequest) -> list[SourceCandidate]:
        return list(self._sources)


# ── Scoring ──────────────────────────────────────────────────────────────


def score_candidate(
    candidate: SourceCandidate,
    *,
    weights: dict[str, float] | None = None,
) -> SourceCandidate:
    """Apply the RFC-004 §3.2 ranking formula to a candidate.

    The returned candidate is the input with ``final_score`` rewritten. The
    four sub-scores are clamped into ``[0.0, 1.0]`` defensively, then the
    weighted sum is computed. The result is clamped into ``[0.0, 1.0]``.
    """

    resolved_weights = dict(weights or DEFAULT_RANKING_WEIGHTS)
    relevance = _clamp01(candidate.relevance_score)
    credibility = _clamp01(candidate.credibility_score)
    freshness = _clamp01(candidate.freshness_score)
    consensus = _clamp01(candidate.consensus_score)
    final = (
        relevance * resolved_weights.get("relevance", DEFAULT_RANKING_WEIGHTS["relevance"])
        + credibility * resolved_weights.get("credibility", DEFAULT_RANKING_WEIGHTS["credibility"])
        + freshness * resolved_weights.get("freshness", DEFAULT_RANKING_WEIGHTS["freshness"])
        + consensus * resolved_weights.get("consensus", DEFAULT_RANKING_WEIGHTS["consensus"])
    )
    return candidate.model_copy(update={"final_score": _clamp01(final)})


def rank_sources(
    candidates: Iterable[SourceCandidate],
    *,
    limit: int | None = None,
    weights: dict[str, float] | None = None,
) -> list[SourceCandidate]:
    """Score every candidate, sort by ``final_score`` desc, return top-N.

    ``limit`` is **not** a fixed cap of 3-5 (per RFC-004 §3.2): it is a
    maximum only. A caller that asks for ``limit=10`` against two valid
    sources receives two sources — never fabricated ones.
    """

    scored = [score_candidate(candidate, weights=weights).clamped() for candidate in candidates]
    scored.sort(
        key=lambda candidate: (
            candidate.final_score,
            candidate.relevance_score,
            candidate.credibility_score,
        ),
        reverse=True,
    )
    if limit is not None and limit >= 0:
        scored = scored[:limit]
    return scored


# ── Route gating ─────────────────────────────────────────────────────────


def should_retrieve(
    task_profile: TaskProfile,
    *,
    uncertainty_triggered: bool = False,
    route_gating: dict[str, str] | None = None,
) -> tuple[bool, str, str]:
    """Decide whether retrieval should run for this request.

    Returns ``(should_run, gating_mode, reason)`` where ``gating_mode`` is
    the resolved entry from the route-gating table (``required`` /
    ``optional`` / ``off``) and ``reason`` is a short human-readable
    explanation suitable for telemetry.
    """

    resolved_gating = dict(route_gating or ROUTE_GATING)
    task_type = (task_profile.task_type or "general").lower()
    mode = resolved_gating.get(task_type, "off")

    if mode == "required":
        return True, mode, f"route '{task_type}' requires retrieval"
    if mode == "optional":
        if task_profile.requires_rag or uncertainty_triggered:
            return True, mode, f"route '{task_type}' opted in (requires_rag={task_profile.requires_rag})"
        return False, mode, f"route '{task_type}' optional, not opted in"
    # mode == "off" (or unknown route → defaults to off)
    if uncertainty_triggered:
        return True, mode, f"route '{task_type}' normally off; uncertainty engine forced retrieval"
    return False, mode, f"route '{task_type}' gated off"


# ── Public entry point ──────────────────────────────────────────────────


class RetrievalService:
    """Coordinates a provider, scoring, and the route-gating decision.

    The service owns a single async :class:`RetrievalProvider`. Callers
    pass a :class:`RetrievalRequest` and receive a :class:`RetrievalResult`
    — never raise. Failure modes degrade to an empty result with a
    descriptive ``retrieval_skipped_reason``.
    """

    def __init__(
        self,
        *,
        provider: RetrievalProvider | None = None,
        weights: dict[str, float] | None = None,
        route_gating: dict[str, str] | None = None,
        evidence_bump_per_source: int = EVIDENCE_BUMP_PER_SOURCE,
    ) -> None:
        self._provider: RetrievalProvider = provider or DeterministicRetrievalProvider()
        self._weights: dict[str, float] = dict(weights or DEFAULT_RANKING_WEIGHTS)
        self._route_gating: dict[str, str] = dict(route_gating or ROUTE_GATING)
        self._evidence_bump_per_source = max(0, int(evidence_bump_per_source))

    @property
    def weights(self) -> dict[str, float]:
        return dict(self._weights)

    @property
    def route_gating(self) -> dict[str, str]:
        return dict(self._route_gating)

    def should_retrieve(
        self,
        task_profile: TaskProfile,
        *,
        uncertainty_triggered: bool = False,
    ) -> tuple[bool, str, str]:
        return should_retrieve(
            task_profile,
            uncertainty_triggered=uncertainty_triggered,
            route_gating=self._route_gating,
        )

    async def retrieve(
        self,
        request: RetrievalRequest,
        *,
        weights: dict[str, float] | None = None,
    ) -> RetrievalResult:
        """Run the retrieval pipeline. Never raises.

        Returns a :class:`RetrievalResult` whose ``retrieval_attempted`` is
        ``False`` when the route-gating decision short-circuits, and
        ``True`` when the provider was invoked. Provider failures are
        logged and produce an empty ``sources`` list.
        """

        if request.task_profile is None:
            return RetrievalResult(
                sources=[],
                retrieval_attempted=False,
                retrieval_skipped_reason="missing task_profile",
                route_gating="off",
                weights=self._weights,
                telemetry={"outcome": "skipped", "reason": "missing_task_profile"},
            )

        should_run, mode, reason = self.should_retrieve(
            request.task_profile,
            uncertainty_triggered=request.uncertainty_triggered,
        )
        if not should_run:
            return RetrievalResult(
                sources=[],
                retrieval_attempted=False,
                retrieval_skipped_reason=reason,
                route_gating=mode,
                weights=self._weights,
                telemetry={
                    "outcome": "skipped",
                    "reason": reason,
                    "route": request.task_profile.task_type,
                },
            )

        try:
            raw = await self._provider.retrieve(request)
        except Exception as exc:  # ponytail: never raise into the request path
            LOGGER.warning("Retrieval provider failed: %s", exc, exc_info=False)
            return RetrievalResult(
                sources=[],
                retrieval_attempted=True,
                retrieval_skipped_reason=f"provider_error: {type(exc).__name__}",
                route_gating=mode,
                weights=self._weights,
                telemetry={
                    "outcome": "error",
                    "error_type": type(exc).__name__,
                    "route": request.task_profile.task_type,
                },
            )

        # Defensive conversion: the provider may return either
        # SourceCandidate objects or dicts (the original ContextManager
        # contract accepted dicts/strings). The scorer normalizes both.
        candidates: list[SourceCandidate] = []
        for item in raw:
            if isinstance(item, SourceCandidate):
                candidates.append(item)
            elif isinstance(item, dict):
                candidates.append(_record_to_candidate(item))
            else:
                # Strings were accepted by the legacy retrieval hook; the
                # new layer scores them with neutral priors and rejects
                # them from ranking (no excerpt ⇒ no source).
                continue

        ranked = rank_sources(candidates, limit=request.limit, weights=weights or self._weights)
        evidence_bump = len(ranked) * self._evidence_bump_per_source
        return RetrievalResult(
            sources=ranked,
            selected_count=len(ranked),
            retrieval_attempted=True,
            retrieval_skipped_reason=None,
            route_gating=mode,
            weights=weights or self._weights,
            evidence_bump=evidence_bump,
            telemetry={
                "outcome": "ok" if ranked else "empty",
                "candidate_count": len(candidates),
                "selected_count": len(ranked),
                "evidence_bump": evidence_bump,
                "route": request.task_profile.task_type,
            },
        )


# ── Config loading ───────────────────────────────────────────────────────


def load_routing_weights(
    config_path: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, float]:
    """Load retrieval weights from ``config/capabilities/routing_defaults.json``.

    Resolution order (per RFC-008 §8 / ADR-005):

    1. ``AETHERIS_RETRIEVAL_WEIGHTS_JSON`` env var (raw JSON).
    2. ``AETHERIS_RETRIEVAL_WEIGHTS_PATH`` env var (path to JSON file).
    3. ``config/capabilities/routing_defaults.json`` ``retrieval.source_ranking_weights`` block.
    4. :data:`DEFAULT_RANKING_WEIGHTS`.

    Loader errors log and fall back to :data:`DEFAULT_RANKING_WEIGHTS` —
    never raise (matches the capability-loader contract from Step 18 and
    the ADR-007 deterministic-fallback discipline).
    """

    import json
    import os
    from pathlib import Path

    environment = os.environ if env is None else env

    raw_env = environment.get("AETHERIS_RETRIEVAL_WEIGHTS_JSON")
    if raw_env:
        try:
            parsed = json.loads(raw_env)
        except json.JSONDecodeError as exc:
            LOGGER.warning("Invalid AETHERIS_RETRIEVAL_WEIGHTS_JSON: %s", exc)
        else:
            if isinstance(parsed, dict):
                merged = {**DEFAULT_RANKING_WEIGHTS, **parsed}
                return _normalize_weights(merged)

    path_env = environment.get("AETHERIS_RETRIEVAL_WEIGHTS_PATH")
    if path_env:
        try:
            payload = json.loads(Path(path_env).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Failed to load weights from %s: %s", path_env, exc)
        else:
            if isinstance(payload, dict):
                block = payload.get("retrieval", {}).get("source_ranking_weights", payload)
                if isinstance(block, dict):
                    merged = {**DEFAULT_RANKING_WEIGHTS, **block}
                    return _normalize_weights(merged)

    candidates: list[Path] = []
    if config_path:
        candidates.append(Path(config_path))
    candidates.append(Path("config/capabilities/routing_defaults.json"))

    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        block = payload.get("retrieval", {}).get("source_ranking_weights")
        if isinstance(block, dict):
            merged = {**DEFAULT_RANKING_WEIGHTS, **block}
            return _normalize_weights(merged)

    return dict(DEFAULT_RANKING_WEIGHTS)


def load_route_gating(
    config_path: str | None = None,
) -> dict[str, str]:
    """Load the route-gating table from ``routing_defaults.json``.

    Falls back to :data:`ROUTE_GATING` on any error. Never raises.
    """

    import json
    from pathlib import Path

    candidates: list[Path] = []
    if config_path:
        candidates.append(Path(config_path))
    candidates.append(Path("config/capabilities/routing_defaults.json"))

    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        block = payload.get("retrieval", {}).get("route_gating")
        if isinstance(block, dict):
            merged = {**ROUTE_GATING, **block}
            return {str(k): str(v) for k, v in merged.items()}

    return dict(ROUTE_GATING)


# ── Helpers ──────────────────────────────────────────────────────────────


def _clamp01(value: float) -> float:
    if math.isnan(value):
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


def _record_to_candidate(record: dict[str, Any]) -> SourceCandidate:
    """Normalize a raw retrieval record into a :class:`SourceCandidate`.

    The four sub-scores default to ``0.0`` when missing — the ranker will
    still produce a deterministic order, but the source will not surface
    to the top unless callers supply non-zero scores.
    """

    excerpt = str(record.get("excerpt") or record.get("content") or "")
    return SourceCandidate(
        url=record.get("url"),
        title=record.get("title"),
        excerpt=excerpt,
        credibility_score=float(record.get("credibility_score", 0.0) or 0.0),
        freshness_score=float(record.get("freshness_score", 0.0) or 0.0),
        relevance_score=float(record.get("relevance_score", 0.0) or 0.0),
        consensus_score=float(record.get("consensus_score", 0.0) or 0.0),
        final_score=float(record.get("final_score", 0.0) or 0.0),
    )


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(value)) for value in weights.values())
    if total <= 0:
        return dict(DEFAULT_RANKING_WEIGHTS)
    if math.isclose(total, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        return {key: max(0.0, float(value)) for key, value in weights.items()}
    return {key: max(0.0, float(value)) / total for key, value in weights.items()}


# Re-export the convenience ``asyncio.to_thread`` shim so providers that
# wrap a sync SDK have a stable import surface. (ADR-002.)
__all__ = [
    "DEFAULT_RANKING_WEIGHTS",
    "DeterministicRetrievalProvider",
    "EVIDENCE_BUMP_PER_SOURCE",
    "InMemoryRetrievalProvider",
    "RetrievalProvider",
    "RetrievalRequest",
    "RetrievalResult",
    "RetrievalService",
    "ROUTE_GATING",
    "SourceCandidate",
    "StaticOverrideProvider",
    "asyncio",
    "load_route_gating",
    "load_routing_weights",
    "rank_sources",
    "score_candidate",
    "should_retrieve",
]


def utc_now() -> datetime:
    """Small timezone-aware clock helper (kept here so providers don't
    have to import :mod:`datetime` themselves)."""

    return datetime.now(tz=timezone.utc)
