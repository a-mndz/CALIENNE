# RFC-004: Memory / RAG / Context

- **Status:** Not Started
- **Architecture version:** `0.1.0`
- **Related ADRs:** ADR-008
- **Owning decisions:** DEC-002, DEC-005, DEC-007, DEC-013

## 1. Purpose

This RFC defines the **memory hierarchy**, the **smart RAG layer**
with source ranking, the **context manager** that assembles per-node
context windows, the **execution replay** subsystem, and the
**two-table PostgreSQL Experience DB**. It does not define the
planner or scheduler (RFC-003), versioning or the manifest (RFC-005),
feature flags (RFC-006), the roadmap (RFC-007), or governance
(RFC-008).

## 2. Memory Hierarchy

Keep the existing `MemoryManager` as the context / token compression
component. Add a new `orchestrator/memory_hierarchy.py` that
composes:

Layers:

- **Short-term memory**: current request and recent turns.
- **Long-term memory**: durable summaries and prior outcomes.
- **User memory**: stable preferences.
- **Agent memory**: per-agent success / failure patterns.
- **Shared knowledge cache**: RAG and source cache.
- **Vector memory**: semantic retrieval layer; in-memory in v1,
  `pgvector` in v2 (per DEC-007).

Wire this gradually into `ContextManager` and `ExecutionManager`, not
directly into every agent. The hierarchy is gated by
`CALIENNE_ENABLE_CONTEXT` (RFC-006).

## 3. Smart RAG

`orchestrator/retrieval.py`.

### 3.1 `SourceCandidate` schema

```python
class SourceCandidate(CalienneBaseModel):
    url: str | None = None
    title: str | None = None
    excerpt: str
    credibility_score: float
    freshness_score: float
    relevance_score: float
    consensus_score: float
    final_score: float
```

### 3.2 Ranking formula

```text
final_score = relevance * 0.4 + credibility * 0.25 + freshness * 0.15 + consensus * 0.2
```

Use top sources by score, not a fixed `3-5`. Store selected source
metadata in `StageAssessment.evidence_count` (RFC-001 §5.1) and RAG
telemetry (`execution.*` namespace).

Retrieval is **route-gated**: required for `research`, optional for
`general`, off for `coding` / `math` / `creative` (unless
uncertainty-engine triggered).

## 4. Context Manager

`orchestrator/context_manager.py`.

Memory stores information; the context manager **actively assembles**
the per-node context window.

```text
Conversation History
  -> Importance Ranking
  -> Compression
  -> Retrieval
  -> Window Assembly
  -> Agent Context
```

Responsibilities:

- Preserve system / developer constraints.
- Rank user requirements by importance.
- Keep recent turns verbatim.
- Compress older low-priority turns.
- Retrieve relevant long-term / user / agent memory.
- Add RAG or code-context snippets only where needed.
- Assemble a bounded context window per task node.

## 5. Agent-Per-Node Context

Per the "Agent Contracts" framework, the ContextManager attaches
the **InputContract** (per RFC-003 §3.4) to every assembled window,
so the receiving node can `validate_inputs(node, incoming_outputs)`
before it starts.

## 6. Execution Replay

`orchestrator/execution_replay.py`.

Writes an append-only `ExecutionTrace`:

- `trace_id`, `passport_id`, `task_profile`, `strategic_plan`,
  `task_graph` (with version stamps), `resource_snapshot_at_start`,
  `prediction_actual` deltas, `events[]`, `final_outcome`, `manifest`
  (frozen).

Events:

```text
node_queued | node_started | node_completed | node_failed
| dependency_released | repair_started | judge_completed
| consensus_completed | early_exit | budget_pressure_changed
| node_cancelled
```

### 6.1 Replay modes

- `replay` — deterministic, real providers, ignore predictions.
- `shadow` — use recorded outputs where available, recompute the
  rest.
- `simulate` — use recorded outputs everywhere, no provider calls;
  for debugging and tests.

### 6.2 Storage

Stored under `telemetry/`, indexed by `(graph_version,
prompt_fingerprint)`.

### 6.3 Retention

Configurable, **default 30 days** (per DEC-006's discussion).

### 6.4 Endpoint

`/api/debug/replay/{trace_id}` gated by
`CALIENNE_ENABLE_REPLAY` (RFC-006).

## 7. Experience Database (PostgreSQL, Two Tables)

`orchestrator/experience_db.py` (SQLAlchemy 2 async + `asyncpg` +
Alembic, per ADR-008). All persistence goes through repository
interfaces (per `plan.md` invariant viii).

### 7.1 `experience_operational` (high write, short retention)

Schema:

```text
prompt_fingerprint | task_profile | prediction_actual_deltas
| latency_ms | cost_usd | failure_class | recovery_action
| replay_trace_id | created_at
```

Retention: **default 7 days**.

### 7.2 `experience_learning` (read-heavy, long retention)

Schema:

```text
prompt_fingerprint | task_profile | task_graph_fingerprint
| planner_version | consensus_quality | routing_quality
| user_satisfaction | graph_mutation_audit
| replay_trace_id | created_at
```

Retention: **default 90 days** (configurable).

### 7.3 Repository interface

```python
class ExperienceRepository:
    async def record_operational(self, record: OperationalExperience) -> None: ...
    async def record_learning(self, record: LearningExperience) -> None: ...
    async def query_operational(self, ...) -> list[OperationalExperience]: ...
    async def query_learning(self, ...) -> list[LearningExperience]: ...
    async def prune(self, before: datetime) -> None: ...
```

No orchestration module talks directly to SQL. The repository is the
only path in.

### 7.4 Test isolation

Tests use **Testcontainers** (Python) to spin a disposable PostgreSQL
per test session. No shared database, no schema isolation, no SQLite
shim (per DEC-002 and N3a).

### 7.5 Promotion pipeline (offline-only in v1)

```text
Experience DB
  -> Offline Evaluation
  -> Benchmark
  -> Shadow Run
  -> Manual Review
  -> Merge
  -> Release
```

No live rerouting in v1 (DEC-005). Gated by
`CALIENNE_ENABLE_EXPERIENCE_DB` (RFC-006) for writes; the
`CALIENNE_ENABLE_SELF_LEARNING` flag (default off) gates adaptive
routing in v2 only.

### 7.6 Vector memory (deferred to v2)

`pgvector` is installed but unused in v1. Vector memory lights up in
v2 against the same `experience_learning` table (per DEC-007).

## 8. Feeding the Other Layers

The Experience DB feeds:

- `MetaReasoner` (similar past failures → don't repeat).
- `PredictionLayer` (calibration priors).
- `RoutingFeedback` (offline policy tuning).

Reads go through a small `ExperienceQuery` API; no raw SQL outside the
repository.

## 9. Invariants Owned by This RFC

- All persistence goes through repository interfaces (`plan.md`
  invariant viii).
- All adaptive behavior must be observable (`plan.md` invariant
  viii) — replay emits `execution.*` / `planner.*` /
  `scheduler.*` events.
- Calibration promotion is manual-PR only (per DEC-015 / `plan.md`
  §7.11).

## 10. Exit Criteria

This RFC is considered **Implemented** when ALL of the following are
true:

- [ ] `orchestrator/memory_hierarchy.py` is implemented with all 6
      layers (in-memory vector layer in v1).
- [ ] `orchestrator/retrieval.py` is implemented with the
      `SourceCandidate` schema and the `final_score` ranking formula.
- [ ] Retrieval is route-gated and configurable via
      `routing_defaults.json`.
- [ ] `orchestrator/context_manager.py` is implemented with the
      importance ranking → compression → retrieval → window assembly
      flow.
- [ ] `orchestrator/execution_replay.py` is implemented with all
      three modes (`replay`, `shadow`, `simulate`) and the
      `/api/debug/replay/{trace_id}` endpoint.
- [ ] Replay retention defaults to 30 days and is configurable.
- [ ] Alembic migration creates `experience_operational` and
      `experience_learning` tables in PostgreSQL.
- [ ] `ExperienceRepository` exposes the documented API; no
      orchestration module talks directly to SQL.
- [ ] Testcontainers-based integration tests pass for all four
      repository methods and for replay storage.
- [ ] `pgvector` extension is installed but no schema depends on it
      (deferred to v2).
- [ ] Telemetry emits `learning.*` namespace (spec in RFC-005 §4).
- [ ] `docs/decision_register.md` rows for DEC-002, DEC-005,
      DEC-007, DEC-013 are updated; `docs/maturity.md` row for this
      RFC moves to `Experimental`.
- [ ] ADR-008 is `Status: Accepted`.
- [ ] Code owner has signed off.
