# Step 20 — Execution Replay + Experience DB (RFC-007 §Step 19)

Implements RFC-004 §6 (replay) and §7 (Experience DB, ADR-008). Both land
behind their feature flags (`CALIENNE_ENABLE_REPLAY`, `CALIENNE_ENABLE_EXPERIENCE_DB`),
default **off**, per Step 20's exit gate in `docs/new/guide.md`.

Flags already exist in `feature_flags.py` + `config/feature_flags.json`.
Watchlist already lists `execution_replay.py` + `experience_db.py`.

## 20a — Execution Replay (no DB)

### New: `orchestrator/execution_replay.py`
- `prompt_fingerprint(user_query) -> str` — deterministic SHA-256 (12–16 hex
  chars) so traces index by `(graph_version, prompt_fingerprint)` (RFC-004 §6.2).
- Schemas (all `CalienneBaseModel`, invariant 1):
  - `ReplayEvent{event_type, node_id?, timestamp_offset_ms, payload}` — event
    types exactly the 11 in RFC-004 §6 (`node_queued`, `node_started`,
    `node_completed`, `node_failed`, `dependency_released`, `repair_started`,
    `judge_completed`, `consensus_completed`, `early_exit`,
    `budget_pressure_changed`, `node_cancelled`).
  - `ExecutionTrace{trace_id, passport_id, task_profile, strategic_plan,
    task_graph, resource_snapshot_at_start, prediction_actual, events[],
    final_outcome, manifest, graph_version, prompt_fingerprint, created_at,
    expires_at}` — append-only.
- `ReplayMode = Literal["replay","shadow","simulate"]` (RFC-004 §6.1). A
  deterministic `replay_trace(trace, mode)` that reproduces the recorded event
  sequence under a **fixed seed + injected clock** (the exit-gate requirement).
  v1 has no live providers wired, so all three modes replay from the recorded
  `events[]`; `mode` governs which events are re-emitted vs recomputed (in v1
  `simulate`/`shadow`/`replay` all yield identical sequences from the trace,
  which satisfies "identical event sequences under a fixed seed").
- `ReplayStore` — filesystem-backed, append-only JSON under `telemetry/replays/`
  indexed by `(graph_version, prompt_fingerprint)`; `record()`, `load(trace_id)`,
  `list_traces()`, `prune(before)`; **default 30-day retention** (RFC-004 §6.3),
  configurable via ctor + `CALIENNE_REPLAY_RETENTION_DAYS`.
- **PII redaction before storage** (guide 20a): a `_redact()` pass over
  user-supplied text fields (query/history) before write — deterministic,
  no raising into the request path (ADR-007).
- `ReplayRecorder` — the collector `ExecutionManager` feeds during a run;
  `.emit(event_type, ...)`, `.finalize(...)` → `ExecutionTrace`. Injectable
  clock (defaults to `time.monotonic`) so tests are deterministic.

### Wire into `orchestrator/execution_manager.py`
- Gate on `self._flags.replay`. When **off**: no recorder, behavior unchanged,
  response gets `replay_trace_id: None` (matches the None-stub precedent).
- When **on**: build a `ReplayRecorder` at request start; emit events at the
  existing seams (scheduler start/complete, early-exit decision, repair,
  consensus, budget pressure). Persist via `ReplayStore` after execution;
  attach `replay_trace_id` + `replay_trace` to the success payload and to the
  `needs_clarification` branch (`early_exit`/`node_cancelled` still recorded).
- Emission is **best-effort**: wrapped so a recorder failure logs and never
  breaks the request (ADR-007), mirroring `_seed_memory_hierarchy`.

### Endpoint: `server.py`
- `GET /api/debug/replay/{trace_id}` gated by `CALIENNE_ENABLE_REPLAY`
  (RFC-004 §6.4). Returns the trace (503 when flag off / store unavailable,
  404 when trace absent), following the existing `/api/checkpoints/...` shape
  (`_calienne.get(...)`, `get_current_user` dep, `HTTPException`).

## 20b — Experience DB (PostgreSQL, two tables, ADR-008)

### `requirements.txt`
- Add `testcontainers[postgresql]>=4.0.0` and `pgvector>=0.2.0` (installed but
  unused in v1, per DEC-007). Note in the file that `pgvector` is v2-reserved.

### `core/models.py` — two ORM tables (SQLAlchemy 2 `Mapped` style)
- `ExperienceOperationalRecord` (`experience_operational`, RFC-004 §7.1):
  `prompt_fingerprint, task_profile(JSON), prediction_actual_deltas(JSON),
  latency_ms(Float), cost_usd(Float), failure_class(str?), recovery_action(str?),
  replay_trace_id(str?), created_at`. Indexes on `prompt_fingerprint`,
  `created_at` (for prune).
- `ExperienceLearningRecord` (`experience_learning`, RFC-004 §7.2):
  `prompt_fingerprint, task_profile(JSON), task_graph_fingerprint,
  planner_version, consensus_quality(Float?), routing_quality(Float?),
  user_satisfaction(Float?), graph_mutation_audit(JSON), replay_trace_id(str?),
  created_at`. Indexes on `prompt_fingerprint`, `task_graph_fingerprint`,
  `created_at`.

### Migration: `migrations/versions/003_experience_db.py`
- `down_revision = "002_add_title_to_conversation_sessions"`; additive-first
  (ADR-008). `upgrade()` creates both tables + indexes; `downgrade()` drops
  them. Matches the `001_initial_schema.py` `op.create_table` style exactly.

### `orchestrator/experience_db.py` — repository + record dataclasses
- Pydantic-friendly transfer objects `OperationalExperience` /
  `LearningExperience` (`CalienneBaseModel`), decoupled from ORM rows.
- `ExperienceRepository` — the **only** path to SQL (invariant 8, RFC-004 §7.3):
  `record_operational`, `record_learning`, `query_operational(...)`,
  `query_learning(...)`, `prune(before)`. Takes a `db_session_factory`
  (callable → `AsyncSession`), exactly like `CheckpointManager` (CRIT-003).
  Async-first (ADR-002); a missing factory raises `RuntimeError` on internal
  helper, public methods degrade/log per the checkpoint precedent.
- Gate: writes only fire when `CALIENNE_ENABLE_EXPERIENCE_DB` is on (checked by
  the caller / a thin `enabled` guard). No raw SQL anywhere else.
- Connection pool ownership: repository receives its factory from the caller;
  `ResourceManager` remains the documented pool owner (ADR-008) — no per-repo
  engine. (Full pool handoff is a wiring note; v1 passes `async_session_maker`.)

## Tests
- `tests/test_execution_replay.py`: prompt_fingerprint determinism; trace
  append-only; **all three modes produce identical event sequences under a
  fixed seed + fake clock** (exit gate); ReplayStore round-trip + 30-day prune;
  PII redaction; ExecutionManager integration (flag off → `replay_trace_id`
  None + unchanged; flag on → trace recorded, events present).
- `tests/test_experience_db.py`:
  - Fake-async-session round-trip for all four repo methods + prune (default
    suite, mirrors `test_crit003_checkpoint_db.py`).
  - Testcontainers-PostgreSQL round-trip marked `@pytest.mark.integration`
    + `@pytest.mark.slow`, **skipped gracefully** when Docker/testcontainers is
    absent (`pytest.importorskip` + connect guard) — satisfies ADR-008 §7.4
    where infra exists, stays green on this Windows box.
  - `no-raw-SQL` guard: assert orchestration modules only reach the DB via the
    repository (lightweight — assert repo is the import surface).

## Governance (per-step definition of done, guide §4)
- `architecture_version` bump `0.1.5` → `0.1.6` in `orchestrator/versioning.py`
  (watchlist files `execution_replay.py`, `experience_db.py`, `execution_manager.py`,
  `core/schemas.py` if touched, `core/models.py` is not on the watchlist but the
  new orchestrator modules are).
- `decision_register.md`: add **DEC-021** (replay + Experience DB implemented,
  flags, retention defaults, testcontainers gating). Mark DEC-002/013 `Implemented? → Partial/Yes`.
- `maturity.md`: advance the **Replay** and **PostgreSQL Experience DB** rows
  `Not Started → Experimental`.
- Update `docs/new/guide.md`: check the Step 20 boxes + exit gate, append a
  `*(completed 2026-07-15)*` note in the Step 20 heading, matching the Step 19 style.

## Exit gate (guide §Step 20)
- Replay modes produce identical event sequences under a fixed seed + fake clock. ✅ (test)
- Testcontainers round-trip test for all four repo methods passes where Docker
  is available; fake-session round-trip always green. ✅ (test)
- Full regression suite stays green (the 2 pre-existing `test_skills.py` Windows
  `tmp_path` errors are unrelated).

## Order of work
1. `execution_replay.py` (schemas + store + recorder + redaction).
2. Wire replay into `execution_manager.py` (flag-gated) + `/api/debug/replay`.
3. `requirements.txt` + `core/models.py` tables + migration 003.
4. `experience_db.py` repository + transfer objects.
5. Tests (replay, experience_db fake + gated testcontainers).
6. Version bump + DEC-021 + maturity + guide update.
7. Run `pytest -q` + the 4 CI scripts; confirm green.
