# CALIENNE Plan — Master Roadmap & Invariant Index

> This document is the **master index** for the CALIENNE adaptive architecture.
> It is intentionally thin. Detailed design lives in the RFCs; settled
> decisions live in the ADRs; the running decision log lives in
> `docs/decision_register.md`; per-subsystem maturity lives in
> `docs/maturity.md`.

- **Architecture version:** `0.1.0` (SemVer; `1.0.0` reserved for "stable, backward-compatible")
- **Manifest schema version:** `1.0` (decoupled from `architecture_version`; see RFC-005)
- **Last updated:** 2026-07-13

## 1. Executive Summary

CALIENNE is moving from a linear, hard-coded pipeline to a **planner-driven,
DAG-based, async-first orchestration runtime** that is observable, replayable,
versioned, and feature-flagged end-to-end. The v1 build introduces:

- A **Strategic + Execution planner split**, fronted by a deterministic
  **Intent Analyzer**.
- An **async event-driven scheduler** that runs independent nodes concurrently
  without blocking the event loop.
- A **Resource Manager** that owns global + per-route + per-model concurrency,
  derived from explicit provider and model limits.
- A **weighted consensus engine**, **uncertainty engine**, and **reflection/repair
  loop** governed by a **Token Budget Manager** as the circuit breaker.
- A **two-table Experience DB on PostgreSQL** (operational + learning) used
  **strictly offline in v1**.
- An **immutable Execution Manifest** stamped onto every artifact, carrying
  per-skill prompt versions, full feature-flag snapshot, and host primitives
  for replay determinism.
- A **Governance layer (RFC-008)** that makes every architectural change
  acknowledge versioning via a hard CI fail, and that keeps all calibration
  promotion as **manual-PR only**.

What this document does **not** do: it does not contain the design itself.
Every section below points at the RFC, ADR, or ledger that owns the design.

## 2. RFC Pointer Table

| RFC | Title | Owns | Status | Exit Criteria |
| --- | --- | --- | --- | --- |
| RFC-001 | System Architecture | Layer separation (K/R/V), `core/base.py`, `CalienneBaseModel` (global `extra="ignore"`), `extra="forbid"` opt-in for critical contracts, `StageAssessment.from_minimal` | Experimental | Step 21 landed 2026-07-16 behind `CALIENNE_ENABLE_KNOWLEDGE_LAYER`: explicit Knowledge / Reasoning / Validation owners wrap the stable `DecisionEngine`; flag-off behavior and legacy payload parsing remain unchanged. `architecture_version` bumped to `0.1.7` (DEC-022). RFC-001 implementation exit gate met. |
| RFC-002 | Execution Pipeline | `IntentAnalyzer`, `ExecutionManager`, `ResourceManager` ceiling rules, `asyncio.to_thread` boundary for sync providers, dynamic topological release | Not Started | See RFC-002 §Exit Criteria |
| RFC-003 | Planner & Scheduler | `StrategicPlanner` + `ExecutionPlanner` split, event-driven `Scheduler`, `MetaReasoner` (merge/skip/downgrade/reorder only), 60s starvation guard, async DAG trap | Not Started | See RFC-003 §Exit Criteria |
| RFC-004 | Memory / RAG / Context | Memory hierarchy (short/long-term/user/agent/shared cache/vector), `SourceCandidate` + ranking formula, `ContextManager` window assembly | Not Started | See RFC-004 §Exit Criteria |
| RFC-005 | Versioning & Execution Manifest | `VersionStamp`, `architecture_version: "0.1.0"`, `graph_fingerprint` (SHA-256) + `graph_version` (monotonic), `manifest_schema_version` decoupling, **metric namespace spec** (`execution.*`, `quality.*`, `resources.*`, `prediction.*`, `learning.*`, `environment.*`, `manifest.*`, `scheduler.*`, `planner.*`), `git_commit` capture (env → CI → `"unknown"`) | Experimental | Step 19 landed 2026-07-14 — canonical SHA-256 fingerprint via `TopologyNormalizer`, monotonic `VersionRegistry`, frozen `ExecutionManifest` (`extra="forbid"`, `manifest_schema_version` decoupled), process-start `HostPrimitives`, manifest attached to `TaskGraph` / `ExecutionPassport` / DAG response payload. `architecture_version` bumped to `0.1.5` (DEC-020). RFC-005 exit gate met. |
| RFC-006 | Feature Flags | `CALIENNE_ENABLE_<SUBSYSTEM>` namespace, per-subsystem default off, typed accessor in `orchestrator/feature_flags.py`, full flag snapshot in manifest | Not Started | See RFC-006 §Exit Criteria |
| RFC-007 | Implementation Roadmap | 22-step sequenced build order, test manifest, PR grouping (PR-001a/b foundation, PR-002..005 per RFC, then implementation PRs) | Not Started | See RFC-007 §Exit Criteria |
| RFC-008 | Governance | Hard CI fail on architectural change without `architecture_version` bump, manual-PR-only calibration promotion, `Decision Register` lifecycle, `Maturity Matrix` lifecycle, Experience DB promotion policy, replay retention, deprecation policy | Not Started | See RFC-008 §Exit Criteria |

**One RFC number = one file.** If a topic grows past its file's bounds, it
becomes `RFC-009`, never `RFC-NNa`. See `docs/decision_register.md` DEC-008.

## 3. ADR Pointer Table

| ADR | Title | Status | Related RFCs |
| --- | --- | --- | --- |
| ADR-001 | Global Pydantic `extra="ignore"` Policy | Accepted | RFC-001 |
| ADR-002 | Async-First Event Loop | Accepted | RFC-002, RFC-003 |
| ADR-003 | Planner + DAG Architecture | Accepted | RFC-003 |
| ADR-004 | Resource Ceiling Management (ResourceManager owns concurrency) | Accepted | RFC-002 |
| ADR-005 | Split Configuration Files under `config/capabilities/` | Accepted | RFC-002, RFC-005 |
| ADR-006 | Validation Layer Always Runs (no fingerprint-skip in v1) | Accepted | RFC-003, RFC-005 |
| ADR-007 | Deterministic Graph Templates with Bounded Planning | Accepted | RFC-003 |
| ADR-008 | Persistence Stack — PostgreSQL + SQLAlchemy 2 + `asyncpg` + Alembic (`pgvector` reserved for v2) | Accepted | RFC-004 |

ADR schema (8-tier with optional `Supersedes`):

```markdown
# ADR-NNN: <Title>
- **Status**: Accepted | Superseded by ADR-XXX | Deprecated
- **Date**: YYYY-MM-DD
- **Deciders**: <names or roles>
- **Related RFCs**: RFC-XXX §N
## Context
## Decision
## Consequences
## Alternatives Considered
## Supersedes (optional)
```

## 4. Decision Register Pointer

The running ledger of architectural decisions lives at
[`docs/decision_register.md`](decision_register.md). It is the canonical
answer to "did we already decide this?" and is the only place where a
decision's status (`Proposed | Accepted | Deferred | Rejected | Superseded`)
changes over time.

- Aging policy: any `Proposed` decision older than **90 days** fails
  `tools/check_decision_register.py` in CI. Promote to `Accepted`,
  `Deferred`, or `Rejected`, or extend the deadline with a recorded reason.
- Initial entries: see `docs/decision_register.md`.

## 5. Architecture Maturity Pointer

Per-subsystem stage tracking lives at
[`docs/maturity.md`](maturity.md).

Stages: `Not Started → Experimental → Shadow → Beta → Stable → Deprecated`.

Stars are intentionally rejected: subjective ratings decay in meaning as the
project grows. Stages are unambiguous and align with the rest of the
documentation.

## 6. Milestone / Progress

The implementation roadmap is owned by `RFC-007`. The high-level milestone
plan, in dependency order:

1. **Documentation Foundation** — PR-001a (Governance) + PR-001b (Architecture/Versioning).
2. **Guardrail Foundation** — `CalienneBaseModel`, `feature_flags.py`,
   `versioning.py`, `git_commit` capture, manifest schema. PR-002.
3. **Schema and Assessment** — `TaskProfile`, `StageAssessment`,
   `PipelineBudget`, `PipelinePlan`, `TaskNode`, `TaskGraph`,
   `StrategicPlan`. PR-003.
4. **Classifier and Deterministic Planner Fallback** — task classification,
   route templates, graph validation. PR-004.
5. **Graph Planner and Dependency-Aware Scheduler (async, event-driven)** —
   planner-generated DAGs for high/critical tasks, topological release via
   `asyncio.Condition`. PR-005.
6. **Token Budget Manager + Prediction Layer** — estimate cost/latency/tokens/
   confidence/repair/retrieval/clarification probabilities, with calibration
   confidence. PR-006.
7. **Context Manager** — importance ranking, compression, retrieval, per-node
   window assembly. PR-007.
8. **Dynamic Skill Composition** — skill fragments and compatibility rules.
   PR-008.
9. **Adaptive Early Exit + Performance Optimizer (MetaReasoner)** — skip/
   merge/downgrade/reorder, 60s starvation guard, mutation audit. PR-009.
10. **Uncertainty Engine** — structured `ClarificationRequest`, retrieval/
    escalation/clarification decisions. PR-010.
11. **Reflection / Repair Loop with Budget Restraint** — `max_repairs = 2`,
    Token Budget as circuit breaker, rejudge. PR-011.
12. **Weighted Consensus + Multi-Judge** — high/critical first, versioned
    `MODEL_CAPABILITY_WEIGHTS`. PR-012.
13. **Route-Specific Graph Templates** — coding, research, math, creative,
    general. PR-013.
14. **Hallucination Firewall + Real Evidence Checks** — replace disabled
    placeholder claim validation. PR-014.
15. **Smart RAG** — `SourceCandidate` ranking, gated by route. PR-015.
16. **Memory Hierarchy** — short/long/user/agent/shared/vector layers.
    PR-016.
17. **Dashboard Metrics (Namespaced)** — `execution.*`, `quality.*`,
    `resources.*`, `prediction.*`, `learning.*`, `environment.*`, `manifest.*`,
    `scheduler.*`, `planner.*`. PR-017.
18. **Resource Manager + Capability Loader** — provider + model + runtime
    reconciliation. PR-018.
19. **Versioning Stamp + Manifest + Fingerprint** — `VersionStamp`,
    `graph_fingerprint` (SHA-256) + `graph_version` (monotonic), full
    feature-flag snapshot, host primitives. PR-019.
20. **Execution Replay + Experience DB (PostgreSQL, two tables)** — operational
    and learning tables; offline-only promotion; testcontainers. PR-020.
21. **Knowledge / Reasoning / Validation Layer Separation** — refactor, not
    rewrite. PR-021.
22. **Agent Contracts (Input + Output + Failure)** — `validate_inputs`,
    `validate_outputs`, `to_failure_response`. PR-022.

Each implementation PR must reference `Implements RFC-NNN` and
`Implements ADR-NNN` in its title or description.

## 7. Cross-RFC Invariants

These invariants hold across all RFCs. Breaking any of them is a breaking
change and must be recorded in `docs/decision_register.md` and an ADR.

1. **Pydantic policy** — all schemas inherit from `CalienneBaseModel` with
   `model_config = ConfigDict(extra="ignore")`; critical contracts opt into
   `extra="forbid"` explicitly. (ADR-001)
2. **Async-first runtime** — every orchestrator component is async; sync
   provider SDKs are wrapped in `asyncio.to_thread(...)`. (ADR-002)
3. **Planner + DAG, not linear** — planning is a two-step (`Strategic` +
   `Execution`) process; scheduling is event-driven. (ADR-003)
4. **ResourceManager owns concurrency** — no other module computes or
   enforces parallelism ceilings. (ADR-004)
5. **Capability files live under `config/capabilities/`, never hardcoded.**
   (ADR-005)
6. **Validation Layer always runs** in v1; no fingerprint-skip. (ADR-006)
7. **All scheduler tasks register an explicit name and attach a cancellation
   boundary hook** to prevent unhandled dangling coroutine leaks on
   dependency failure or timeout.
8. **All persistence goes through repository interfaces.** No orchestration
   module talks directly to SQL.
9. **All adaptive behavior must be observable.** Planner, Prediction,
   MetaReasoner, and Repair must emit telemetry. No hidden AI decisions.
10. **Every adaptive decision has a deterministic fallback.** Never LLM-only;
    always `LLM → Validation → Fallback`. (ADR-007)
11. **Calibration promotion is manual-PR only**, always.
    `CALIENNE_ENABLE_SELF_LEARNING` gates adaptive routing in v2 and does not
    auto-promote. (ADR-008)
12. **`manifest_schema_version` is decoupled from `architecture_version`.**
    The manifest can evolve without forcing an architecture bump.
13. **One RFC number = one file.** No `RFC-NNa`/`RFC-NNb` splits.

## 8. Future Horizons / Phase 3 Incubator

These items are explicitly out of scope for v1. They are tracked here so the
architecture retains a roadmap anchor and so future contributors do not
re-debate them without context.

- **Online learning via Experience DB.** Strictly offline in v1 (ADR-008).
- **MetaReasoner model-tier escalation.** `merge`/`skip`/`downgrade`/`reorder`
  only in v1; escalation gated by `CALIENNE_ENABLE_META_ESCALATION` (default
  off, reserved for v2).
- **Validation skip on fingerprint hit.** Rejected for v1; any future
  bypass needs a dedicated RFC (e.g. `RFC-009 Execution Cache`) with shadow
  testing, replay validation, and a safety-metrics rollout policy. (ADR-006)
- **`pgvector` semantic memory.** Driver installed but unused in v1; lights
  up in v2 against the same `experience_learning` table. (ADR-008)
- **Multi-tenant ResourceManager.** Global + per-route only in v1.
- **Automatic calibration promotion.** Manual-PR only in v1; gated by
  `CALIENNE_ENABLE_SELF_LEARNING`. (ADR-008)
- **Continuous hardware-level optimization mapping** (e.g. dynamic offloading
  profiles for mixed CPU/GPU contexts like Intel i5 HX / RTX 3050).
- **Distributed Execution** — multiple workers, shared queue, coordinator.
- **Model Distillation** — feed Experience DB into a fine-tuned small model
  for cheaper routing decisions.

## 9. Document Layout (Final)

```text
docs/
├── plan.md                            (this file — master index)
├── maturity.md                        (subsystem Architecture Maturity Matrix)
├── decision_register.md               (programmatic decision log; CI-checked)
├── adrs/
│   ├── ADR-001_Global_Pydantic_Ignore_Policy.md
│   ├── ADR-002_Async_First_Event_Loop.md
│   ├── ADR-003_Planner_+_DAG.md
│   ├── ADR-004_Resource_Ceiling_Management.md
│   ├── ADR-005_Split_Configuration_Files.md
│   ├── ADR-006_Validation_Layer_Invariance.md
│   ├── ADR-007_Deterministic_Graph_Templates.md
│   └── ADR-008_Persistence_PostgreSQL_SQLAlchemy2_asyncpg_Alembic.md
└── rfcs/
    ├── RFC-001_System_Architecture.md
    ├── RFC-002_Execution_Pipeline.md
    ├── RFC-003_Planner_Scheduler.md
    ├── RFC-004_Memory_RAG_Context.md
    ├── RFC-005_Versioning_&_Execution_Manifest.md
    ├── RFC-006_Feature_Flags.md
    ├── RFC-007_Implementation_Roadmap.md
    └── RFC-008_Governance.md
```

## 10. PR Grouping

- **PR-001a — Governance Foundation.** `RFC-007`, `RFC-008`, all 8 ADRs,
  `docs/decision_register.md`, `docs/maturity.md`, `tools/check_*.py`.
- **PR-001b — Architecture & Versioning Foundation.** `RFC-001`, `RFC-005`,
  `RFC-006`.
- **PR-002** — `RFC-002` (Execution Pipeline).
- **PR-003** — `RFC-003` (Planner & Scheduler).
- **PR-004** — `RFC-004` (Memory / RAG / Context).
- **PR-005+** — implementation PRs, each titled
  `Implements RFC-NNN` and `Implements ADR-NNN`.

## 11. CI Tooling

All four tools run in CI; any failure blocks merge.

- `tools/check_rfc_index.py` — every `RFC-NNN` title appears in `plan.md`
  §2; every `Related RFCs` field in an ADR resolves to a real RFC file.
- `tools/check_adr_index.py` — every `ADR-NNN` title appears in `plan.md`
  §3; every `Related RFCs` reference resolves.
- `tools/check_decision_register.py` — no `Proposed` decision older than
  90 days without an explicit extension; every `DEC-NNN` is unique.
- `tools/check_architecture_version.py` — hard CI fail if any file in the
  architectural watchlist is changed without a bump in
  `orchestrator/versioning.py`.

## 12. Relevant Files

- `docs/plan.md` — this index.
- `docs/maturity.md` — per-subsystem maturity matrix.
- `docs/decision_register.md` — running decision ledger.
- `docs/adrs/ADR-001..008_*.md` — settled architectural decisions.
- `docs/rfcs/RFC-001..008_*.md` — forward-looking design specs.
- `tools/check_rfc_index.py`, `tools/check_adr_index.py`,
  `tools/check_decision_register.py`, `tools/check_architecture_version.py`
  — CI verification scripts.
- Existing code anchors (referenced by RFCs, not modified by this plan):
  - `orchestrator/pipelines.py` (current `run_micro_mode` entry path;
    legacy pipeline toggle `calienne_LEGACY_PIPELINE_ENABLED`;
    `_is_claim_extraction_enabled` default-off; CRIT-001 enforces
    `DecisionEngine` as sole path).
  - `orchestrator/decisions.py` (`DecisionEngine`, `DecisionStrategy`).
  - `orchestrator/evaluation.py` (`arbitrate_and_synthesize` judge call).
  - `orchestrator/memory.py` (`EpistemicMemory` failure tracking).
  - `orchestrator/memory_manager.py` (`MemoryManager` token compression).
  - `orchestrator/streaming.py` (SSE event types, `StreamingManager`).
  - `core/schemas.py` (`AgentOutput`, `calienneOutput`,
    `CalienneBaseModel`).
  - `core/runtime.py` (`RuntimeEngine`, `RuntimeContract`).
  - `core/passport.py` (`ExecutionPassport`).
  - `api_gateway/strategy.py` (`ProviderStrategy`, `StrategyMode`).
  - `api_gateway/client.py`, `api_gateway/rate_limiter.py`.
  - `agents/prompt_utils.py`.
  - `server.py` (Step 1 target: passport telemetry contract).
  - `migrations/`, `alembic.ini` (PostgreSQL Alembic chain).
  - `tests/test_pipeline.py`, `test_pipeline_repair.py`, `test_validators.py`,
    `test_state_machine.py`, `test_security.py`, `test_runtime_repair.py`,
    `test_providers_repair.py`, `test_phase2_cleanup.py`, `test_passport.py`,
    `test_database_repair.py`, `test_crit003_checkpoint_db.py`,
    `test_conversation.py`, `test_auth_repair.py`.
- **New artifacts to be created during implementation:**
  - `config/capabilities/{model_capabilities,provider_limits,pricing,routing_defaults,prediction_calibration}.json`
  - `config/prompt_versions.json`
  - `config/feature_flags.json`
  - `tools/check_architecture_version.py` (others listed above)
  - `orchestrator/{strategic_planner,execution_planner,resource_manager,meta_reasoner,contracts,knowledge_layer,reasoning_layer,validation_layer,execution_replay,experience_db,prediction,budget,context_manager,execution_manager,scheduler,performance,uncertainty,repair,consensus,retrieval,memory_hierarchy,routing_feedback,versioning,execution_manifest,feature_flags,skills,planner,routing}.py`
  - `api_gateway/capabilities.py`
  - `core/base.py`
