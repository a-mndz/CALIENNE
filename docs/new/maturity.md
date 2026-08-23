# Architecture Maturity Matrix

Per-subsystem lifecycle stage tracking. The canonical source of truth for
"is this production-ready?" is this file, not `plan.md`.

## Stages

| Stage | Meaning |
| --- | --- |
| Not Started | RFC not yet written or design not finalized. |
| Experimental | Code in `main`; no real users; behavior may change without notice. |
| Shadow | Code runs in shadow mode (predictions logged but not used for routing). |
| Beta | Enabled behind a feature flag; real traffic; not load-bearing. |
| Stable | Default-on for at least one route; no known regressions. |
| Deprecated | Still callable; removal scheduled in a specific RFC version. |

## Matrix

| Subsystem | Stage | Owner | Last Updated | RFC | Notes |
| --- | --- | --- | --- | --- | --- |
| Architecture (layer separation, `CalienneBaseModel`) | Experimental | — | 2026-07-16 | RFC-001 | Step 21 landed behind `CALIENNE_ENABLE_KNOWLEDGE_LAYER` (default off): `KnowledgeLayer` owns facts/provenance/retrieval and prior lessons, `ReasoningLayer` wraps existing breaker/generation without retrieval or judging, and `ValidationLayer` owns judge/consensus/repair/firewall plus `StageAssessment`/`ClarificationRequest`. Flag-off keeps the stable merged `DecisionEngine` path. `CalienneBaseModel` and critical-contract policy were completed in earlier steps; legacy payload parsing remains green. `architecture_version` bumped `0.1.6` → `0.1.7` (DEC-022). Not load-bearing yet. |
| Execution Pipeline (Intent, ExecutionManager, ResourceManager) | Experimental | — | 2026-07-14 | RFC-002 | Steps 5–18 landed behind `CALIENNE_ENABLE_DAG`: `IntentAnalyzer`, `ExecutionManager`, and (Step 18) the capability loader (`api_gateway/capabilities.py`) + `ResourceManager` (`orchestrator/resource_manager.py`) owning `effective_parallel` (RFC-002 §6, ADR-004/DEC-011). Not load-bearing yet. |
| Planner & Scheduler (Strategic + Execution + event-driven Scheduler) | Not Started | — | 2026-07-13 | RFC-003 | Depends on RFC-002. |
| Memory / RAG / Context (hierarchy, `ContextManager`) | Experimental | — | 2026-07-14 | RFC-004 | Step 7 (context manager) + Step 15 (smart RAG, route-gated) + Step 16 (memory hierarchy) all landed behind `CALIENNE_ENABLE_*` flags; not load-bearing yet. |
| Versioning & Execution Manifest (stamps, fingerprint, manifest) | Experimental | — | 2026-07-14 | RFC-005 | Step 19 landed 2026-07-14: canonical SHA-256 `graph_fingerprint` via `TopologyNormalizer` (node-name- and order-independent, contract-aware), monotonic in-memory `VersionRegistry` keyed by `(planner_version, strategy_version, contract_version)`, frozen `ExecutionManifest` (`extra="forbid"`, `manifest_schema_version="1.0"` decoupled from `architecture_version`) with the full `FeatureFlags.as_env_map()` snapshot, and process-start `HostPrimitives` (`torch.cuda.is_available()` for `cuda_version`; kubernetes/docker/containerd/podman detection for `container`/`container_runtime`). `ExecutionManager` now builds the manifest pre-strategic-plan, model_copy-overwrites with `planner_version` after `_maybe_plan`, stamps the graph via `versioning.stamp_graph` after MetaReasoner mutation, and attaches the same instance to `TaskGraph` / `ExecutionPassport` / both DAG response branches. Remaining Step 17 stubs (`planner.fingerprint.hash`, `learning.graph.fingerprint`, `manifest.graph_*`, `resources.gpu`) now sourced. `architecture_version` bumped `0.1.4` → `0.1.5` (DEC-020). |
| Feature Flags (`CALIENNE_ENABLE_*`) | Not Started | — | 2026-07-13 | RFC-006 | Independent; implement first. |
| Implementation Roadmap | Not Started | — | 2026-07-13 | RFC-007 | Document; no code. |
| Governance (CI, Decision Register, Maturity) | Not Started | — | 2026-07-13 | RFC-008 | Document; no code. |
| Existing `DecisionEngine` path | Stable | — | 2026-07-13 | — | Production today; the baseline every new subsystem must beat. |
| PostgreSQL Experience DB (two tables) | Experimental | — | 2026-07-15 | RFC-004 | Step 20b landed 2026-07-15 behind `CALIENNE_ENABLE_EXPERIENCE_DB` (default off): `core/models.py` gains `ExperienceOperationalRecord` (7-day cadence) + `ExperienceLearningRecord` (90-day cadence); migration `003_experience_db` (additive, `down_revision=002_add_title_to_conversation_sessions`); `orchestrator/experience_db.py` `ExperienceRepository` is the sole SQL boundary (invariant 8), `db_session_factory`-injected like `CheckpointManager` (CRIT-003), writes gated on `enabled`, `_require_factory` raises when unwired. `requirements.txt` adds `testcontainers[postgresql]` + `pgvector` (v2-reserved, DEC-007). Tests: in-memory fake-session round-trip (default suite) + `integration`/`slow` Testcontainers-PostgreSQL round trip (skips gracefully w/o Docker). Realizes DEC-002 + DEC-013. Not load-bearing yet. |
| Replay (Execution Replay, Execution Trace) | Experimental | — | 2026-07-15 | RFC-004 | Step 20a landed 2026-07-15 behind `CALIENNE_ENABLE_REPLAY` (default off): `orchestrator/execution_replay.py` ships `prompt_fingerprint` (SHA-256, `(graph_version, prompt_fingerprint)` index), `redact_pii`, the 11-event RFC-004 §6 vocabulary, `ReplayEvent`/`ExecutionTrace`, `ReplayRecorder` (injectable clock, drops unknown events), filesystem `ReplayStore` under `telemetry/replays/` (30-day retention via `CALIENNE_REPLAY_RETENTION_DAYS`; `record`/`load`/`list_traces`/`prune`, never raises — ADR-007), and `replay_trace` (replay/shadow/simulate identical under fixed seed + injected clock — exit-gate property). Wired flag-gated into `ExecutionManager` (11 event emissions + `_finalize_replay` + `replay_trace_id` on both response branches) and `calienne_orchestrator.py`; `GET /api/debug/replay/{trace_id}` (admin, 503 when off). `architecture_version` bumped `0.1.5` → `0.1.6` (DEC-021). Not load-bearing yet. |
| MetaReasoner (Performance Optimizer) | Not Started | — | 2026-07-13 | RFC-003 | Merge/skip/downgrade/reorder only; no escalation in v1. |

## Update Discipline

A subsystem row moves stage when:

- The relevant RFC §Exit Criteria is fully checked.
- `docs/decision_register.md` is updated to reflect any new deferred/rejected
  decisions surfaced during the move.
- The PR description references the relevant RFC and ADR.

Without this discipline the matrix goes stale.
