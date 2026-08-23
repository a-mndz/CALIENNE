"""Tests for the Step 20a execution-replay layer (RFC-004 §6).

Covers the fingerprint + PII helpers, the injectable-clock recorder, the
filesystem-backed store round-trip + retention prune, and the exit-gate
property: under a fixed seed and injected clock every replay mode yields an
identical event sequence.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestrator.execution_replay import (
    REPLAY_EVENT_TYPES,
    ExecutionTrace,
    ReplayRecorder,
    ReplayStore,
    prompt_fingerprint,
    redact_pii,
    replay_trace,
)


# ponytail: pytest-asyncio + Windows file-lock the parent tmp_path, so the
# store tests use a fresh mkdtemp dir each run and clean it up.
@pytest.fixture
def replay_dir():
    path = Path(tempfile.mkdtemp(prefix="calienne_replay_"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


# ── Fingerprint ─────────────────────────────────────────────────────────────


def test_prompt_fingerprint_is_deterministic_and_whitespace_normalized():
    a = prompt_fingerprint("Summarize the   report")
    b = prompt_fingerprint("summarize the report")
    assert a == b
    assert len(a) == 16


def test_prompt_fingerprint_respects_min_length():
    assert len(prompt_fingerprint("x", length=4)) == 8  # floor of 8


# ── PII redaction ───────────────────────────────────────────────────────────


def test_redact_pii_scrubs_email_phone_and_long_digits():
    scrubbed = redact_pii("mail me at a.b@example.com or +1 415 555 2671, card 4111111111111111")
    assert "example.com" not in scrubbed
    assert "[REDACTED_EMAIL]" in scrubbed
    assert "[REDACTED_PHONE]" in scrubbed
    assert "[REDACTED_NUMBER]" in scrubbed


def test_redact_pii_never_raises_on_non_string():
    assert redact_pii(None) is None  # type: ignore[arg-type]


# ── Recorder ────────────────────────────────────────────────────────────────


class _FakeClock:
    """Deterministic monotonic clock returning successive fixed values."""

    def __init__(self, ticks: list[float]) -> None:
        self._ticks = ticks
        self._i = 0

    def __call__(self) -> float:
        value = self._ticks[min(self._i, len(self._ticks) - 1)]
        self._i += 1
        return value


def test_recorder_uses_injected_clock_for_offsets():
    clock = _FakeClock([10.0, 10.5, 11.0])  # start=10.0
    recorder = ReplayRecorder(trace_id="t1", clock=clock)
    recorder.emit("node_started", node_id="n1")
    recorder.emit("node_completed", node_id="n1")
    events = recorder.events
    assert [e.timestamp_offset_ms for e in events] == [500.0, 1000.0]


def test_recorder_drops_unknown_event_types():
    recorder = ReplayRecorder(trace_id="t1", clock=_FakeClock([0.0]))
    recorder.emit("not_a_real_event", node_id="n1")
    assert recorder.events == []


def test_recorder_finalize_redacts_and_sets_expiry():
    clock = _FakeClock([0.0, 0.1])
    recorder = ReplayRecorder(trace_id="t1", clock=clock)
    recorder.emit("node_started", node_id="n1")
    created = datetime(2026, 7, 15, tzinfo=timezone.utc)
    trace = recorder.finalize(
        graph_version="g1",
        prompt_fingerprint_value="fp1",
        task_profile={"note": "reach me at a@b.com"},
        retention_days=30,
        created_at=created,
    )
    assert trace.task_profile == {"note": "reach me at [REDACTED_EMAIL]"}
    assert trace.expires_at == created + timedelta(days=30)
    assert trace.index_key() == ("g1", "fp1")


# ── Store round-trip ────────────────────────────────────────────────────────


def _make_trace(trace_id: str, *, expires_at: datetime | None = None) -> ExecutionTrace:
    return ExecutionTrace(
        trace_id=trace_id,
        graph_version="g1",
        prompt_fingerprint="fp1",
        created_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        expires_at=expires_at,
    )


def test_store_record_and_load_round_trip(replay_dir):
    store = ReplayStore(base_dir=replay_dir, retention_days=30)
    trace = _make_trace("abc123")
    store.record(trace)
    loaded = store.load("abc123")
    assert loaded is not None
    assert loaded.trace_id == "abc123"
    assert loaded.index_key() == ("g1", "fp1")
    assert store.list_traces() == ["abc123"]


def test_store_load_missing_returns_none(replay_dir):
    store = ReplayStore(base_dir=replay_dir)
    assert store.load("nope") is None


def test_store_prune_removes_expired_only(replay_dir):
    store = ReplayStore(base_dir=replay_dir)
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    store.record(_make_trace("expired", expires_at=now - timedelta(days=1)))
    store.record(_make_trace("fresh", expires_at=now + timedelta(days=1)))
    removed = store.prune(before=now)
    assert removed == 1
    assert store.load("expired") is None
    assert store.load("fresh") is not None


def test_store_retention_days_env_override(replay_dir, monkeypatch):
    monkeypatch.setenv("CALIENNE_REPLAY_RETENTION_DAYS", "5")
    store = ReplayStore(base_dir=replay_dir)
    assert store.retention_days == 5


# ── Exit gate: identical sequence across modes ──────────────────────────────


def test_replay_modes_produce_identical_sequences():
    clock = _FakeClock([0.0, 0.1, 0.2, 0.3, 0.4])
    recorder = ReplayRecorder(trace_id="t1", clock=clock)
    for event_type in ("node_queued", "node_started", "node_completed", "consensus_completed"):
        recorder.emit(event_type, node_id="n1")
    trace = recorder.finalize(graph_version="g1", prompt_fingerprint_value="fp1")

    replay = replay_trace(trace, mode="replay")
    shadow = replay_trace(trace, mode="shadow")
    simulate = replay_trace(trace, mode="simulate")

    def _seq(events):
        return [(e.event_type, e.node_id, e.timestamp_offset_ms) for e in events]

    assert _seq(replay) == _seq(shadow) == _seq(simulate)
    assert _seq(replay) == _seq(trace.events)


def test_replay_trace_rejects_unknown_mode():
    trace = _make_trace("t1")
    with pytest.raises(ValueError):
        replay_trace(trace, mode="bogus")  # type: ignore[arg-type]


def test_all_eleven_event_types_registered():
    assert len(REPLAY_EVENT_TYPES) == 11
