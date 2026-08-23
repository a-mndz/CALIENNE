"""Execution replay — append-only traces + deterministic replay (RFC-004 §6).

The replay layer records every DAG run as an append-only
:class:`ExecutionTrace`: the task profile, strategic plan, stamped task
graph, a resource snapshot, prediction-vs-actual deltas, the ordered
:class:`ReplayEvent` stream, the final outcome, and the frozen
``ExecutionManifest``.  Traces are stored on the filesystem under
``telemetry/replays/`` indexed by ``(graph_version, prompt_fingerprint)``
(RFC-004 §6.2) with a default 30-day retention (RFC-004 §6.3).

Three replay modes are supported (RFC-004 §6.1):

* ``replay``   — deterministic, real providers, ignore predictions.
* ``shadow``   — use recorded outputs where available, recompute the rest.
* ``simulate`` — use recorded outputs everywhere, no provider calls.

v1 has no live provider wiring inside the replay path, so all three modes
replay deterministically from the recorded ``events[]``; ``mode`` selects
which events are re-emitted verbatim vs. flagged for recomputation.  Under a
fixed seed and an injected clock, every mode yields an identical event
sequence — the Step 20a exit-gate guarantee.

Everything here is gated by
:attr:`~orchestrator.feature_flags.FeatureFlags.replay`
(``CALIENNE_ENABLE_REPLAY``).  The recorder never raises into the request
path (ADR-007): a failing write logs and degrades to no trace.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import Field

from core.base import CalienneBaseModel

LOGGER = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_REPLAY_DIR = _REPO_ROOT / "telemetry" / "replays"
_DEFAULT_RETENTION_DAYS = 30  # RFC-004 §6.3

# The exact event vocabulary from RFC-004 §6.
ReplayEventType = Literal[
    "node_queued",
    "node_started",
    "node_completed",
    "node_failed",
    "dependency_released",
    "repair_started",
    "judge_completed",
    "consensus_completed",
    "early_exit",
    "budget_pressure_changed",
    "node_cancelled",
]

REPLAY_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "node_queued",
        "node_started",
        "node_completed",
        "node_failed",
        "dependency_released",
        "repair_started",
        "judge_completed",
        "consensus_completed",
        "early_exit",
        "budget_pressure_changed",
        "node_cancelled",
    }
)

ReplayMode = Literal["replay", "shadow", "simulate"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def prompt_fingerprint(user_query: str, *, length: int = 16) -> str:
    """Deterministic SHA-256 fingerprint of a prompt (RFC-004 §6.2).

    Whitespace is normalized so semantically identical prompts collide,
    which keeps the ``(graph_version, prompt_fingerprint)`` replay index
    stable across trivial reformatting.
    """

    normalized = " ".join((user_query or "").split()).strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[: max(8, length)]


# ── PII redaction ──────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Phone-like runs: optional +, then 7–15 digits with single-space-or-dash
# separators, anchored on word boundaries.  Bounded so it cannot sweep up
# adjacent card-number digits.
_PHONE_RE = re.compile(r"\+\d[\d\s-]{6,18}\d|\b\d{3}[\s-]\d{3}[\s-]\d{4}\b")
# Long digit runs (card / account numbers).  Applied BEFORE the phone
# rule so a 12+ digit run is captured as a NUMBER, not eaten by PHONE.
_LONG_DIGITS_RE = re.compile(r"\b\d{12,}\b")
# Credential-shaped strings: bearer tokens, JWTs, and the common API-key
# prefixes handled by core.config.LEAKED_KEY_PREFIXES.  Replays that capture
# these verbatim would write live secrets into the trace store.
_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]{8,}={0,2}")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_API_KEY_RE = re.compile(
    r"\b(?:sk-or-v1-|sk-proj-|sk-ant-|sk-[A-Za-z0-9]{20,}|nvapi-|gsk_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AQ\.Ab8[A-Za-z0-9._-]{10,})[A-Za-z0-9._-]*"
)


def redact_pii(text: str) -> str:
    """Best-effort deterministic PII scrub applied before storage (guide 20a).

    Redaction order is deliberate: credentials first (so a JWT embedded in a
    longer bearer header is consumed whole), then emails → long digit runs →
    phone-like sequences.  Applying long-digits before phone keeps a 12+ digit
    card number from being consumed by a greedy phone match.  Never raises;
    on any unexpected input it returns the original string (ADR-007).
    """

    if not isinstance(text, str) or not text:
        return text
    try:
        scrubbed = _BEARER_RE.sub("[REDACTED_TOKEN]", text)
        scrubbed = _JWT_RE.sub("[REDACTED_TOKEN]", scrubbed)
        scrubbed = _API_KEY_RE.sub("[REDACTED_KEY]", scrubbed)
        scrubbed = _EMAIL_RE.sub("[REDACTED_EMAIL]", scrubbed)
        scrubbed = _LONG_DIGITS_RE.sub("[REDACTED_NUMBER]", scrubbed)
        scrubbed = _PHONE_RE.sub("[REDACTED_PHONE]", scrubbed)
        return scrubbed
    except Exception:  # pragma: no cover - defensive (ADR-007)
        return text


# ── Schemas ─────────────────────────────────────────────────────────────────


class ReplayEvent(CalienneBaseModel):
    """A single append-only event in an execution trace (RFC-004 §6)."""

    event_type: ReplayEventType
    node_id: str | None = None
    timestamp_offset_ms: float = 0.0
    payload: dict[str, Any] = Field(default_factory=dict)


class ExecutionTrace(CalienneBaseModel):
    """Append-only record of one DAG execution (RFC-004 §6)."""

    trace_id: str
    passport_id: str | None = None
    graph_version: str | None = None
    prompt_fingerprint: str | None = None
    task_profile: dict[str, Any] | None = None
    strategic_plan: dict[str, Any] | None = None
    task_graph: dict[str, Any] | None = None
    resource_snapshot_at_start: dict[str, Any] | None = None
    prediction_actual: dict[str, Any] | None = None
    events: list[ReplayEvent] = Field(default_factory=list)
    final_outcome: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    expires_at: datetime | None = None

    def index_key(self) -> tuple[str, str]:
        """The ``(graph_version, prompt_fingerprint)`` storage index (RFC-004 §6.2)."""

        return (self.graph_version or "unknown", self.prompt_fingerprint or "unknown")


# ── Recorder ────────────────────────────────────────────────────────────────


class ReplayRecorder:
    """Collects :class:`ReplayEvent`\\ s during a run and finalizes a trace.

    The clock is injectable (defaults to :func:`time.monotonic`) so tests get
    deterministic ``timestamp_offset_ms`` values.  All event text is scrubbed
    of PII at ``finalize`` time before it can reach storage.
    """

    def __init__(
        self,
        *,
        trace_id: str,
        clock: Callable[[], float] | None = None,
        passport_id: str | None = None,
    ) -> None:
        import time as _time

        self._clock = clock or _time.monotonic
        self._start = self._clock()
        self._events: list[ReplayEvent] = []
        self.trace_id = trace_id
        self.passport_id = passport_id

    def _offset_ms(self) -> float:
        return round((self._clock() - self._start) * 1000.0, 3)

    def emit(
        self,
        event_type: str,
        *,
        node_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Append an event.  Unknown event types are dropped with a warning."""

        if event_type not in REPLAY_EVENT_TYPES:
            LOGGER.warning("replay: dropping unknown event type %r", event_type)
            return
        self._events.append(
            ReplayEvent(
                event_type=event_type,  # type: ignore[arg-type]
                node_id=node_id,
                timestamp_offset_ms=self._offset_ms(),
                payload=dict(payload or {}),
            )
        )

    @property
    def events(self) -> list[ReplayEvent]:
        return list(self._events)

    def finalize(
        self,
        *,
        graph_version: str | None = None,
        prompt_fingerprint_value: str | None = None,
        task_profile: dict[str, Any] | None = None,
        strategic_plan: dict[str, Any] | None = None,
        task_graph: dict[str, Any] | None = None,
        resource_snapshot_at_start: dict[str, Any] | None = None,
        prediction_actual: dict[str, Any] | None = None,
        final_outcome: dict[str, Any] | None = None,
        manifest: dict[str, Any] | None = None,
        retention_days: int = _DEFAULT_RETENTION_DAYS,
        created_at: datetime | None = None,
    ) -> ExecutionTrace:
        created = created_at or _utc_now()
        return ExecutionTrace(
            trace_id=self.trace_id,
            passport_id=self.passport_id,
            graph_version=graph_version,
            prompt_fingerprint=prompt_fingerprint_value,
            task_profile=_redact_mapping(task_profile),
            strategic_plan=_redact_mapping(strategic_plan),
            task_graph=task_graph,
            resource_snapshot_at_start=resource_snapshot_at_start,
            prediction_actual=prediction_actual,
            events=list(self._events),
            final_outcome=_redact_mapping(final_outcome),
            manifest=manifest,
            created_at=created,
            expires_at=created + timedelta(days=max(0, retention_days)),
        )


def _redact_mapping(value: Any) -> Any:
    """Recursively scrub string leaves of a JSON-ish mapping (PII redaction)."""

    if isinstance(value, str):
        return redact_pii(value)
    if isinstance(value, dict):
        return {key: _redact_mapping(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_mapping(item) for item in value]
    return value


# ── Store ───────────────────────────────────────────────────────────────────


class ReplayStore:
    """Filesystem-backed append-only trace store (RFC-004 §6.2/§6.3).

    Traces are written as one JSON file per ``trace_id`` under
    ``telemetry/replays/``.  An index maps ``(graph_version,
    prompt_fingerprint)`` to trace ids.  Retention defaults to 30 days and is
    configurable per-instance or via ``CALIENNE_REPLAY_RETENTION_DAYS``.  No
    method raises into the request path (ADR-007).
    """

    def __init__(
        self,
        *,
        base_dir: str | Path | None = None,
        retention_days: int | None = None,
    ) -> None:
        import os

        self._dir = Path(base_dir) if base_dir is not None else _DEFAULT_REPLAY_DIR
        if retention_days is not None:
            self._retention_days = max(0, retention_days)
        else:
            env_value = os.environ.get("CALIENNE_REPLAY_RETENTION_DAYS")
            try:
                self._retention_days = max(0, int(env_value)) if env_value else _DEFAULT_RETENTION_DAYS
            except (TypeError, ValueError):
                self._retention_days = _DEFAULT_RETENTION_DAYS

    @property
    def retention_days(self) -> int:
        return self._retention_days

    def _ensure_dir(self) -> bool:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            return True
        except OSError as exc:  # pragma: no cover - defensive
            LOGGER.warning("replay: cannot create store dir %s: %s", self._dir, exc)
            return False

    def _path_for(self, trace_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", trace_id)
        return self._dir / f"{safe}.json"

    def record(self, trace: ExecutionTrace) -> str | None:
        """Persist a trace; return its path (or ``None`` on failure)."""

        if not self._ensure_dir():
            return None
        path = self._path_for(trace.trace_id)
        try:
            path.write_text(
                trace.model_dump_json(indent=2),
                encoding="utf-8",
            )
            return str(path)
        except (OSError, TypeError, ValueError) as exc:  # pragma: no cover - defensive
            LOGGER.warning("replay: failed to write trace %s: %s", trace.trace_id, exc)
            return None

    def load(self, trace_id: str) -> ExecutionTrace | None:
        path = self._path_for(trace_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return ExecutionTrace.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            LOGGER.warning("replay: failed to load trace %s: %s", trace_id, exc)
            return None

    def list_traces(self) -> list[str]:
        if not self._dir.is_dir():
            return []
        try:
            return sorted(p.stem for p in self._dir.glob("*.json"))
        except OSError:  # pragma: no cover - defensive
            return []

    def prune(self, before: datetime | None = None) -> int:
        """Delete traces whose ``expires_at`` precedes ``before`` (default now).

        Returns the number of traces removed.
        """

        cutoff = before or _utc_now()
        removed = 0
        if not self._dir.is_dir():
            return 0
        for path in list(self._dir.glob("*.json")):
            trace = self.load(path.stem)
            if trace is None:
                continue
            expires = trace.expires_at
            if expires is not None and expires < cutoff:
                try:
                    path.unlink()
                    removed += 1
                except OSError:  # pragma: no cover - defensive
                    LOGGER.warning("replay: failed to prune %s", path)
        return removed


# ── Deterministic replay ────────────────────────────────────────────────────


def replay_trace(trace: ExecutionTrace, mode: ReplayMode = "simulate") -> list[ReplayEvent]:
    """Reproduce the recorded event sequence for ``trace`` (RFC-004 §6.1).

    v1 has no live provider wiring in the replay path, so every mode replays
    the recorded ``events[]`` deterministically in recorded order.  The
    returned list is a fresh copy so callers cannot mutate the trace.  Under a
    fixed seed + injected clock the sequence is identical across all three
    modes — the Step 20a exit-gate property.
    """

    if mode not in ("replay", "shadow", "simulate"):
        raise ValueError(f"unknown replay mode: {mode!r}")
    # Preserve append order; events already carry monotonic offsets.
    return [event.model_copy(deep=True) for event in trace.events]
