# RFC-007: Implementation Roadmap

- **Status:** Not Started
- **Architecture version:** `0.1.0`
- **Related ADRs:** ADR-001..ADR-008
- **Owning decisions:** DEC-008, DEC-014

## 1. Purpose

This RFC owns the **sequenced build order** for v1, the **PR grouping
model**, and the **test manifest**. It is explicitly a roadmap, not a
design spec; design lives in RFC-001..006 and governance lives in
RFC-008. The master index in `docs/plan.md` §6 mirrors this roadmap
and is the canonical place to look up "what milestone are we on
right now?"

## 2. Sequenced Build Order

Implementation proceeds strictly in the order below. Each step is
behind its feature flag (RFC-006) by default; flipping the flag is a
separate decision recorded in `decision_register.md`.

### Step 1. Fix observability plumbing (RFC-002, RFC-005)

Before adding adaptive behavior, make the existing execution
measurable.

- Pass the created `passport` into `run_micro_mode` in `server.py`.
- Ensure streaming and non-streaming paths use equivalent
  telemetry contracts.
- Prefer routing streaming through the same `DecisionEngine` /
  future `ExecutionManager` path instead of keeping a separate legacy
  inline pipeline.
- Return or expose request-level metrics consistently for dashboard
  and tests.
- No additional ADR; this is plumbing.

### Step 2. Schemas and assessments (RFC-001)

- Add `CalienneBaseModel` in `core/base.py`.
- Make every existing schema in `core/schemas.py` inherit from it.
- Add `TaskProfile`, `StageAssessment` (with all extended fields
  `Optional` + documented defaults), `PipelineBudget`,
  `PipelinePlan`, `TaskNode`, `TaskGraph`, `StrategicPlan`,
  `ClarificationRequest`, `Prediction`, `PredictionInterval`,
  `VersionStamp` (RFC-005).
- Add `StageAssessment.from_minimal(...)`.
- Add tests proving old outputs still parse.

### Step 3. Classifier and deterministic planner fallback (RFC-002, RFC-003)

- Implement `IntentAnalyzer` in `orchestrator/routing.py`.
- Add route templates for general / coding / research / math /
  creative (RFC-002 §9).
- Add graph validation (RFC-003 §2.3).

### Step 4. Graph planner and dependency-aware scheduler (RFC-003)

- Implement `StrategicPlanner` and `ExecutionPlanner` for high /
  critical tasks.
- Execute zero-dependency nodes in parallel; serialize
  dependency-bound nodes.
- Emit graph telemetry.
- Async DAG trap rules (RFC-002 §8) binding: dynamic topological
  release via `asyncio.Condition`, no wave loop, no blocking sync
  calls inside the loop, concurrency cap from `ResourceManager`.

### Step 5. Token budget manager and prediction layer (RFC-003)

- Estimate `expected_cost`, `expected_latency_ms`,
  `expected_tokens`, `expected_confidence`, plus the new probability
  fields (`failure`, `repair`, `retrieval`, `clarification`,
  `consensus_disagreement`) and `expected_repair_count`.
- Added: `calibration_confidence` (how trustworthy the priors are).
- Enforce budget pressure states (RFC-003 §5).

### Step 6. Context manager (RFC-004)

- Implement importance ranking, compression, retrieval, and
  per-node window assembly.
- Route-gate retrieval (RFC-004 §3.2).

### Step 7. Dynamic skill composition (RFC-003 §13)

- Define skill fragments and compatibility rules.
- Let planner assign skill bundles per node.
- Per-skill `prompt_versions` from `config/prompt_versions.json`
  (RFC-005 §5).

### Step 8. Adaptive early exit and performance optimizer (RFC-003)

- Skip unnecessary stages.
- Reuse cached outputs.
- Detect overkill and redundant nodes.
- `MetaReasoner` runs with `merge` / `skip` / `downgrade` /
  `reorder` only; no escalation in v1.
- Record `mutation_audit_trail` on the trace.

### Step 9. Uncertainty engine (RFC-003 §11)

- Support structured `ClarificationRequest` outputs.
- Decide retrieval / model escalation / user clarification based on
  uncertainty type.

### Step 10. Reflection / repair loop with restraints (RFC-003 §9)

- `max_repairs = 2`.
- Token budget as circuit breaker.
- Rejudge repaired outputs.

### Step 11. Weighted consensus and multi-judge (RFC-003 §10)

- Implement high / critical first.
- Use versioned model capability weights (from
  `config/capabilities/model_capabilities.json`).
- Keep low / medium cheap.
- Emit `MinorityView` with reasons; derive
  `minority_should_influence_final`.

### Step 12. Route-specific graph templates (RFC-002 §9)

- Expand deterministic graph templates for coding, research, math,
  creative, and general.

### Step 13. Hallucination firewall and real evidence checks (RFC-003 §12)

- Replace disabled placeholder claim validation with route-specific
  evidence verification.

### Step 14. Smart RAG (RFC-004 §3)

- Introduce source ranking and source metrics.
- Gate for research / current-fact tasks or
  uncertainty-triggered retrieval.

### Step 15. Memory hierarchy (RFC-004 §2)

- Add short-term, long-term, user, agent, shared cache, and vector
  memory layers (in-memory vector in v1).

### Step 16. Dashboard metrics (RFC-005 §4)

- Emit all nine metric namespaces (`execution.*`, `quality.*`,
  `resources.*`, `prediction.*`, `learning.*`, `environment.*`,
  `manifest.*`, `scheduler.*`, `planner.*`).

### Step 17. Resource Manager + capability loader (RFC-002 §4, §5)

- Provider + model + runtime reconciliation.
- `effective_parallel` calculation.
- Capability loader with override path and load-failure fallback.

### Step 18. Versioning stamp + manifest + fingerprint (RFC-005)

- `VersionStamp` on every artifact.
- `graph_fingerprint` (SHA-256) + `graph_version` (monotonic).
- `ExecutionManifest` frozen with full flag snapshot + host
  primitives.
- `manifest_schema_version` decoupled from `architecture_version`.

### Step 19. Execution replay + Experience DB (PostgreSQL, two tables) (RFC-004 §6, §7)

- `experience_operational` + `experience_learning` on PostgreSQL.
- Repository pattern; no direct SQL.
- Testcontainers for tests.
- Replay modes: `replay`, `shadow`, `simulate`.
- Offline-only promotion path (RFC-008).

### Step 20. Knowledge / Reasoning / Validation layer separation (RFC-001 §2)

- Refactor the existing `DecisionEngine` RAG path into three layers.
- Staged behind `CALIENNE_ENABLE_KNOWLEDGE_LAYER`.

### Step 21. Agent contracts (Input + Output + Failure) (RFC-003 §3.4)

- `validate_inputs`, `validate_outputs`, `to_failure_response`.
- Make nodes interchangeable.

### Step 22. Self-learning safeguards (RFC-008)

- Add experience replay records.
- Require offline evaluation, shadow testing, A/B testing, then
  production rollout.
- `CALIENNE_ENABLE_SELF_LEARNING` gates adaptive routing in v2.

## 3. PR Grouping Model

Per `plan.md` §10:

- **PR-001a — Governance Foundation.** `RFC-007`, `RFC-008`, all 8
  ADRs, `docs/decision_register.md`, `docs/maturity.md`, and the
  four `tools/check_*.py` scripts.
- **PR-001b — Architecture & Versioning Foundation.** `RFC-001`,
  `RFC-005`, `RFC-006`.
- **PR-002** — `RFC-002` (Execution Pipeline).
- **PR-003** — `RFC-003` (Planner & Scheduler).
- **PR-004** — `RFC-004` (Memory / RAG / Context).
- **PR-005+** — implementation PRs, each titled `Implements RFC-NNN`
  and `Implements ADR-NNN`.

Rationale (per `plan.md` §10): one large governance PR + one large
documentation foundation PR keeps governance and architecture moving
together. Per-RFC PRs let each RFC land on its own review without
blocking unrelated subsystems.

## 4. Test Manifest

Unit tests:

- `TaskProfile` classification.
- Low / medium / high / critical judge allocation.
- `TaskGraph` validation: cycles, missing dependencies, unknown
  skills, missing final node.
- Dependency-aware scheduling order.
- Parallel node eligibility.
- Confidence-threshold early exits.
- Rich `StageAssessment` parsing and fallback defaults.
- Token budget compression and repair circuit-breaker decisions.
- Prediction output shape and expected-vs-actual telemetry recording.
- `PredictionInterval` upper / lower bounds.
- Cost-tier model selection.
- Weighted model capability lookup.
- Dynamic skill composition and incompatible skills.
- Uncertainty outcomes, including `needs_clarification`.
- Reflection / repair loop stopping at `max_repairs = 2`.
- Consensus agreement matrix and weighted agreement; minority view
  reasoning.
- Hallucination firewall removing or qualifying unsupported claims.
- Failure classification: Recoverable vs Non-Recoverable;
  `FailurePolicy` action selection.
- `MetaReasoner` mutation bounds (max N mutations, audit trail).
- Starvation: `Background` auto-promotes after 60s.
- Fingerprint determinism: identical DAGs hash to the same value.
- Version registry monotonicity.
- Manifest frozen enforcement.
- `git_commit` fallback chain (env → CI → `unknown`).
- `prompt_versions.json` resolution env → default → built-in
  fallback.
- Contract validation: `validate_inputs` / `validate_outputs` /
  `to_failure_response`.
- Capability loader: missing file, out-of-range weight, unknown
  `task_type`, env override.
- `ResourceManager` `effective_parallel` with provider + model +
  runtime limits.

Integration tests:

- `/api/query` returns passport metrics.
- Streaming events emit graph / node stages.
- Deterministic fallback used when planner output is invalid.
- Replay modes (`replay`, `shadow`, `simulate`) produce identical
  event sequences given a fixed seed and a fake clock.
- `experience_operational` and `experience_learning` round-trip via
  the repository under Testcontainers PostgreSQL.
- `asyncio.Condition`-based scheduler does not block sibling nodes
  on a slow LLM call.

Regression tests:

- Existing `tests/test_pipeline.py`, `test_pipeline_repair.py`,
  `test_validators.py`, `test_state_machine.py`, `test_security.py`,
  `test_runtime_repair.py`, `test_providers_repair.py`,
  `test_phase2_cleanup.py`, `test_passport.py`,
  `test_database_repair.py`, `test_crit003_checkpoint_db.py`,
  `test_conversation.py`, `test_auth_repair.py` continue to pass
  **unchanged** (per ADR-001).

## 5. Invariants Owned by This RFC

- One RFC number = one file; no `RFC-NNa` splits (DEC-008).
- Hard CI fail on architectural change without `architecture_version`
  bump (DEC-014, RFC-008 §3).
- Documentation precedes implementation (per
  `plan.md` §6.1): RFCs → ADRs → Decision Register → Maturity →
  Implementation, in this order.

## 6. Exit Criteria

This RFC is considered **Implemented** when ALL of the following are
true:

- [ ] The 22-step build order is complete and each step has a
      merged PR.
- [ ] Every PR title references `Implements RFC-NNN` and
      `Implements ADR-NNN`.
- [ ] Every unit / integration / regression test in §4 passes.
- [ ] Every existing regression test in `tests/` continues to pass
      unchanged.
- [ ] `tools/check_rfc_index.py`, `tools/check_adr_index.py`,
      `tools/check_decision_register.py`, and
      `tools/check_architecture_version.py` all pass in CI.
- [ ] `docs/maturity.md` shows every implemented subsystem at
      `Experimental` or above.
- [ ] `docs/decision_register.md` shows every `DEC-NNN` in
      `Accepted` (or `Deferred` / `Rejected` with a recorded
      reason); no `Proposed` older than 90 days without an
      extension.
- [ ] All ADRs are `Status: Accepted`.
- [ ] Code owner has signed off.
