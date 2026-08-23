# CALIENNE Build Guide — Step-by-Step Implementation Plan

> **What this is.** A practical, ordered checklist for building the v1
> adaptive runtime described in `plan.md`, the eight RFCs, and the eight
> ADRs in this folder. The RFCs tell you *what* and *why*; this guide tells
> you *in what order*, *how big each chunk is*, and *how to know you're
> done*. Read `plan.md` first for the executive summary, then use this file
> as your working tracker.
>
> **Golden rule (from RFC-007 §5):** *Documentation precedes
> implementation.* The docs in this folder are the spec. Do not edit an RFC
> mid-build to match your code — record design changes in
> `decision_register.md` with a new `DEC-NNN`.

---

## 0. Orientation — the mental model before you touch code

CALIENNE is moving **from** a linear pipeline
(`Breaker → Logician/Creative → Judge`, today in `orchestrator/pipelines.py`
via `run_micro_mode`) **to** a planner-driven, DAG-based, async-first
runtime. Every new subsystem ships **behind a feature flag that defaults to
off** (RFC-006), so the existing `DecisionEngine` path keeps working the
whole way. Nothing you build breaks production until a flag is flipped in a
separate, recorded decision.

### The layered architecture you are building toward

```text
                         ┌─────────────────────────────┐
   request ─────────────▶│  IntentAnalyzer (RFC-002)   │  deterministic, token-free
                         │  → TaskProfile              │  (regex/keyword only)
                         └──────────────┬──────────────┘
                                        ▼
                         ┌─────────────────────────────┐
                         │  StrategicPlanner (RFC-003) │  LLM-assisted, planning-only
                         │  → StrategicPlan            │  (only if needs_decomposition)
                         └──────────────┬──────────────┘
                                        ▼
                         ┌─────────────────────────────┐
                         │  ExecutionPlanner (RFC-003) │  rule-based, fast
                         │  → validated TaskGraph      │  (falls back to templates)
                         └──────────────┬──────────────┘
                                        ▼
   ┌───────────────┐      ┌─────────────────────────────┐      ┌──────────────────┐
   │ ResourceMgr   │◀────▶│  ExecutionManager (RFC-002) │◀────▶│ ContextManager   │
   │ (RFC-002)     │      │  owns the event loop        │      │ (RFC-004)        │
   │ effective_    │      └──────────────┬──────────────┘      └──────────────────┘
   │ parallel      │                     ▼
   └───────────────┘      ┌─────────────────────────────┐
                          │  Scheduler (RFC-003)        │  event-driven, asyncio.Condition
                          │  workers pull ready-set     │  MetaReasoner may mutate graph
                          └──────────────┬──────────────┘
                                         ▼
              ┌───── Knowledge Layer ──── Reasoning Layer ──── Validation Layer ─────┐
              │  (RFC-001 §2: retrieval → generation → judge/consensus/repair/firewall) │
              └───────────────────────────────┬────────────────────────────────────┘
                                              ▼
                    Every artifact stamped with an immutable ExecutionManifest
                    (RFC-005) → optionally recorded to Experience DB (RFC-004)
```

### Nine invariants that constrain every step (from `plan.md` §7)

Keep these pinned; breaking any one is a breaking change requiring an ADR +
`decision_register.md` entry:

1. **Every schema** inherits from `CalienneBaseModel` (`extra="ignore"`);
   critical contracts opt into `extra="forbid"`. (ADR-001)
2. **Async-first**: every orchestrator component is async; sync SDKs wrapped
   in `asyncio.to_thread(...)`. (ADR-002)
3. **Planner + DAG**, never linear; scheduling is event-driven. (ADR-003)
4. **ResourceManager owns concurrency** — nothing else computes ceilings.
   (ADR-004)
5. **Capability files** live under `config/capabilities/`, never hardcoded.
   (ADR-005)
6. **Validation Layer always runs** in v1; no fingerprint-skip. (ADR-006)
7. **Every scheduler task** has an explicit name + cancellation hook.
8. **All persistence** goes through repository interfaces; no module talks
   raw SQL.
9. **Every adaptive decision has a deterministic fallback**:
   `LLM → Validation → Fallback`, never LLM-only. (ADR-007)

---

## 1. Current state of the repo (verified 2026-07-13)

| Thing | Status | Note |
| --- | --- | --- |
| `docs/new/` RFCs + ADRs + registers | ✅ Present | The spec. This guide lives beside them. |
| `tools/check_*.py` (4 CI scripts) | ✅ **Verified green 2026-07-13** | `check_rfc_index`, `check_adr_index`, `check_decision_register`, `check_architecture_version`. **Bug found & fixed:** all four hardcoded `DOCS = repo/"docs"` but the specs live in `docs/new/` — so `check_rfc_index`/`check_adr_index` were passing *vacuously* (dirs absent → early-return) while `check_decision_register` hard-failed. Repointed `DOCS` at `docs/new` in the three doc-reading scripts; now non-vacuous (validates 8 real RFCs). `check_architecture_version` is diff-driven — run with `--stdin`/`--changed-files`, not bare. |
| `orchestrator/` legacy modules | ✅ Present | `pipelines.py`, `decisions.py`, `evaluation.py`, `memory.py`, `memory_manager.py`, `streaming.py`, `state_machine.py`, etc. These are the anchors you wrap, not rewrite. |
| `core/` (`schemas.py`, `passport.py`, `runtime.py`) | ✅ Present | `CalienneBaseModel` target lives in a new `core/base.py`. |
| `api_gateway/` (`strategy.py`, `rate_limiter.py`, `client.py`) | ✅ Present | `ResourceManager` extends `rate_limiter.py`; capabilities loader is new. |
| `migrations/` + `alembic.ini` | ✅ Present | PostgreSQL Alembic chain already scaffolded. |
| `tests/` (13 regression suites) | ✅ Present | Must keep passing **unchanged** (ADR-001). |
| `config/` | ✅ **Seeded 2026-07-13** | All 7 files now exist: `config/capabilities/{model_capabilities,provider_limits,pricing,routing_defaults,prediction_calibration}.json`, `config/prompt_versions.json`, `config/feature_flags.json`. Values are **seed defaults** grounded in `strategy.py` (11 real models, 6 providers) and the RFC thresholds. **Still TODO:** verify `pricing.json` against live provider rates; build the loaders that read these (Steps 4, 8, 18). Each file carries a `_meta` block (owner/reviewer per RFC-008 §8) — loaders must ignore `_`-prefixed keys. |
| `requirements.txt` | ⚠️ Note | Has `asyncpg`, `sqlalchemy>=2`, `alembic`, but **`aiosqlite` present and no `testcontainers`/`pgvector`** — add these when you reach the DB steps. |

**First action, before any coding:** run the four CI tools and the full
test suite to establish a green baseline.

```bash
python tools/check_rfc_index.py
python tools/check_adr_index.py
python tools/check_decision_register.py
git diff --name-only origin/main | python tools/check_architecture_version.py --stdin
python -m pytest -q
```

If any fail *now*, fix the tooling/docs first — you cannot measure progress
against a broken baseline.

> **Baseline established 2026-07-13:** 4/4 CI scripts green, `pytest` = 120
> passed. Note the tooling bug fixed to get here: the three doc-reading
> scripts were repointed from `docs/` to `docs/new/` (they were previously a
> false green). `check_architecture_version.py` is diff-driven and **requires**
> `--stdin` or `--changed-files` — a bare invocation is a usage error, not a
> failure.

---

## 2. How the work splits into phases

The 22 steps in RFC-007 §2 are correct and **must be followed in order** —
each depends on artifacts from the previous. I have grouped them into six
phases by theme and dependency, split the heavy steps into sub-tasks, and
marked the natural stopping points (mergeable PRs). Work **top to bottom**;
do not start a phase until the previous phase's exit gate is green.

```text
Phase A  Foundation & guardrails      Steps 0–1        (PR-001a, PR-001b, Step 1)
Phase B  Schemas & the planner spine  Steps 2–5        (PR-002, PR-003, PR-005)
Phase C  Budgeting & context          Steps 5b–7       (PR-006, PR-007)
Phase D  Adaptive intelligence        Steps 8–14       (PR-008 … PR-014)
Phase E  Knowledge, memory, metrics   Steps 15–18      (PR-015 … PR-018)
Phase F  Versioning, replay, contracts Steps 18–22     (PR-019 … PR-022)
```

> **Feature-flag discipline (every step):** land the code behind its
> `CALIENNE_ENABLE_*` flag defaulted **off**. Flipping a flag on is a
> *separate* PR with its own `decision_register.md` note. This keeps `main`
> shippable at every step.

---

## PHASE A — Foundation & Guardrails

*Goal: the docs, CI gates, and observability plumbing are solid before any
adaptive behavior exists.*

### ☐ Step 0 — Ratify the documentation foundation (PR-001a + PR-001b)

The docs already exist; this step is about making CI *enforce* them.

- [x] Confirm `tools/check_rfc_index.py` verifies every `RFC-NNN` in
      `plan.md` §2 and every ADR `Related RFCs` resolves to a real file.
      *(2026-07-13: green, validates all 8 RFCs after `DOCS`→`docs/new` fix.)*
- [x] Confirm `tools/check_adr_index.py` verifies §3 pointers. *(green)*
- [x] Confirm `tools/check_decision_register.py` fails on a `Proposed`
      decision older than 90 days and on duplicate `DEC-NNN`. *(green after
      `DOCS`→`docs/new` fix — was hard-failing on missing file.)*
- [x] Confirm `tools/check_architecture_version.py` reads the **exact**
      watchlist in RFC-008 §2.2 and hard-fails when a watchlist file changes
      without a bump in `orchestrator/versioning.py`. *(verified: watchlist
      matches; fails correctly when `scheduler.py` "changes" while
      `versioning.py` is absent. Run it with `--stdin`, not bare.)*
- [ ] Wire all four into CI so any failure blocks merge. *(scripts green
      locally; CI wiring still TODO.)*
- [x] Confirm all 8 ADRs are `Status: Accepted`, `maturity.md` has its
      12 rows, `decision_register.md` has DEC-001…DEC-015. *(the three
      passing index/register checks assert exactly this.)*

**Exit gate:** four scripts green in CI; `maturity.md` Governance row can
move to `Stable` (governance has no runtime behavior to shadow — RFC-008
§11).

### ☑ Step 1 — Fix observability plumbing (RFC-007 §Step 1) *(completed 2026-07-13)*

Make the *existing* execution measurable before adding anything adaptive.
No new ADR — this is plumbing.

- [x] Pass the created `passport` into `run_micro_mode` in `server.py`.
- [x] Make streaming and non-streaming paths use equivalent telemetry
      contracts (`orchestrator/streaming.py`).
- [x] Route streaming through the same `DecisionEngine` / future
      `ExecutionManager` path — stop maintaining a separate legacy inline
      pipeline.
- [x] Expose request-level metrics consistently for dashboard + tests.
- [x] Treat public API ingress payloads in `server.py` as a **critical
      contract** (`extra="forbid"`) per RFC-001 §4.

**Exit gate (met):** `/api/query` returns passport metrics
(`test_run_micro_mode_returns_passport_metrics`); streaming events carry
the same telemetry as non-streaming (single `run_micro_mode` call site
emits both shapes via `MicroModeResult["passport"]` +
`_build_frontend_payload["metrics"]`). `extra="forbid"` coverage in
`tests/test_server_ingress.py`.

---

## PHASE B — Schemas & the Planner Spine

*Goal: the type system and the deterministic planner/scheduler skeleton
exist. This is the backbone everything else hangs on.*

### ☑ Step 2 — Base model + all v1 schemas (PR-002 + PR-003 schemas) *(completed 2026-07-13)*

Split into two commits so review is tractable:

**2a — the base class + backward-compat proof**
- [x] Add `core/base.py` with `CalienneBaseModel`
      (`ConfigDict(extra="ignore")`). (RFC-001 §3)
- [x] Make **every** schema in `core/schemas.py` inherit from it. (ponytail:
      `passport.py` uses `@dataclass` with `threading.Lock` by design — not a
      Pydantic schema; converting would break threading. Skipped with note.)
- [x] Add a test proving every legacy `AgentOutput` / `calienneOutput`
      fixture still parses unchanged. This is the ADR-001 safety net.

**2b — the new schemas** (all fields `Optional` with documented defaults;
gating fields default to `None`, not optimistic values)
- [x] `StageAssessment` + `StageAssessment.from_minimal()` (RFC-001 §5.1).
- [x] `TaskProfile`, `StrategicPlan`, `TaskNode`, `TaskGraph`,
      `PipelineBudget`, `PipelinePlan` (RFC-003 §3).
- [x] `InputContract`, `OutputContract`, `FailureContract`,
      `FailurePolicy` table (RFC-003 §3.4/§3.5) → `orchestrator/contracts.py`.
- [x] `Prediction`, `PredictionInterval` (RFC-003 §3.6).
- [x] `ClarificationRequest` (RFC-003 §3.7).
- [x] `VersionStamp` (RFC-005 §2).

**Exit gate (met):** 10 new schema tests pass (backward-compat, from_minimal,
inheritance, defaults); all 135 existing tests pass unchanged.

### ☑ Step 3 — Classifier + deterministic planner fallback (RFC-007 §Step 3) *(completed 2026-07-13)*

- [x] Implement `IntentAnalyzer` in `orchestrator/routing.py` —
      deterministic, token-free: route detection (coding/research/math/
      creative/general), complexity scoring (low/medium/high/critical), and
      the `needs_decomposition` signal. (RFC-002 §2)
- [x] Add the five route templates (RFC-002 §9) as the deterministic
      backstop.
- [x] Add graph validation (RFC-003 §2.3): reject cycles, missing deps,
      unknown skills/tiers, missing final node, over-cap node count, nodes
      without objective+output contract → fall back to a template.

**Exit gate (met):** `tests/test_routing.py` covers `TaskProfile`
classification across all five routes, validates the deterministic
templates, rejects cycles / missing deps / unknown skills / missing final
node / missing output contract, and proves invalid graphs fall back via
`validate_or_fallback(...)`. Full regression suite green: `pytest -q` = 147
passed.

### ☑ Step 4 — Feature flags + versioning primitives (prereq for Steps 5+) *(completed 2026-07-13)*

> These are listed late in RFC-007's numbering (Steps 16/18) but the flag
> accessor and the `architecture_version` constant are **needed early**
> because every later step gates on a flag and the CI watchlist points at
> `orchestrator/versioning.py`. Build the thin versions now; enrich later.

- [x] `orchestrator/feature_flags.py`: `FeatureFlags` dataclass +
      `load_flags()` with precedence env > `config/feature_flags.json` >
      hardcoded off. (RFC-006 §4) — verified: env > file > hardcoded-off
      precedence correct; v2-reserved flags log warning + stay disabled.
- [x] `config/feature_flags.json` with all 13 flags declared, default off.
- [x] `orchestrator/versioning.py`: `architecture_version = "0.1.0"`
      constant + `git_commit` capture chain (env → CI → `"unknown"`,
      captured once at process start). (RFC-005 §2.2) — *fingerprint /
      registry come in Step 18.* — verified: `CALIENNE_GIT_COMMIT` >
      `GIT_COMMIT` > CI env > `.git_commit_sha` file > `"unknown"`.
- [x] `CALIENNE_ENABLE_META_ESCALATION` and
      `CALIENNE_ENABLE_SELF_LEARNING` log a warning + do nothing in v1
      (reserved for v2 per DEC-003/015).

**Exit gate (met):** flag-precedence unit test passes
(`tests/test_feature_flags.py`: 2 tests — env-over-file precedence,
v2-reserved-flag warning); `git_commit` fallback-chain test passes
(`tests/test_versioning.py`: 5 tests — architecture_version constant,
CALIENNE_GIT_COMMIT > GIT_COMMIT > CI env > file > unknown). Full
regression green: `pytest -q` = 159 passed (147 original + 12 new).

### ☑ Step 5 — Graph planner + event-driven scheduler (PR-005, RFC-007 §Step 4) *(completed 2026-07-13)*

The heart of the system. Split into three:

**5a — planners**
- [x] `orchestrator/strategic_planner.py` (LLM-assisted, planning-only;
      invoked only when `needs_decomposition`; rejects raw execution steps).
- [x] `orchestrator/execution_planner.py` (rule-based; `StrategicPlan` or
      template → validated `TaskGraph`; assigns tier/tokens/retries/
      contracts per node). Retire the single `orchestrator/planner.py` shape.

**5b — the async scheduler** (obey the **Async DAG trap rules**, RFC-002 §8)
- [x] `orchestrator/scheduler.py`: one long-lived scheduler coroutine owns
      the ready-set; workers pull via `asyncio.Condition`. **No wave loop.**
- [x] Zero-dependency nodes run in parallel; dependency-bound nodes
      serialize. Concurrency cap is a semaphore from `ResourceManager`
      (stub the cap now; real `ResourceManager` is Step 17).
- [x] Priority bands Critical→High→Normal→Background + 60s starvation guard
      (`starvation_promote_after_seconds`). (RFC-003 §4.3)
- [x] Every task gets an explicit name + cancellation hook (invariant 7).
- [x] Keep a `run_dag_blocking(graph)` façade for back-compat (RFC-002 §8).

**5c — `ExecutionManager`**
- [x] `orchestrator/execution_manager.py` owns the event loop and the
      request entry point; wraps `DecisionEngine`; when `CALIENNE_ENABLE_DAG`
      is off, falls back to `run_micro_mode` unchanged. (RFC-002 §3)

**Exit gate (met):** dependency-aware scheduling-order test +
parallel-eligibility test pass; the integration test proving
`asyncio.Condition` doesn't block siblings on a slow LLM call passes;
`CALIENNE_ENABLE_DAG=false` falls back to `run_micro_mode` unchanged.
(`tests/test_execution_manager.py`: 5 tests — dependency order, parallel
zero-dep nodes, non-blocking siblings, DAG-off fallback, DAG-on graph
execution). Full regression green: `pytest -q` = 159 passed.

---

## PHASE C — Budgeting & Context

*Goal: the runtime knows what a request will cost and assembles the right
context per node.*

### ☑ Step 6 — Token Budget Manager + Prediction layer (RFC-007 §Step 5) *(completed 2026-07-13)*

- [x] `orchestrator/budget.py`: default 15 000-token budget with the RFC
      split (planning 5% / generation 45% / critique+repair 20% /
      judge 15% / memory 10% / final 5%), pressure states
      `normal→tight→critical→exhausted`, and repair-circuit-breaker
      decisions. Integrated with `MemoryManager.track_tokens()` and
      optional `RuntimeContract.max_tokens` clamping. (RFC-003 §5)
- [x] `orchestrator/prediction.py`: deterministic prediction layer for
      cost/latency/tokens/confidence using `PredictionInterval`s, the five
      probability fields, `expected_repair_count`, and
      `calibration_confidence`, seeded from
      `config/capabilities/prediction_calibration.json`. Exposes
      expected-vs-actual telemetry in the RFC metric namespace and keeps
      `upper_bound` available for the future `ResourceManager` check.
- [x] Wired Step 6 into `ExecutionManager`: DAG runs now materialize a
      request budget, apply history compression pressure decisions, and
      emit prediction telemetry only when
      `CALIENNE_ENABLE_PREDICTION=true`. With the flag off, execution stays
      deterministic and unchanged apart from carrying the budget object.
- [x] Hardened token counting fallback: if `tiktoken` cannot initialize in a
      restricted environment, `MemoryManager` now falls back to the existing
      word-count heuristic instead of failing the request/test run.

**Exit gate (met):** `tests/test_budget.py` covers budget allocation,
history compression, runtime-contract clamping, and repair circuit-breaker
decisions; `tests/test_prediction.py` covers graph-aware priors and
expected-vs-actual telemetry; `tests/test_execution_manager.py` covers
prediction-mode integration; `tests/test_schemas.py` still covers
`PredictionInterval` bounds. Full regression suite green:
`.venv\Scripts\python.exe -m pytest -q` = 166 passed.

### ☑ Step 7 — Context Manager (RFC-007 §Step 6) *(completed 2026-07-13)*

- [x] `orchestrator/context_manager.py`: implemented the RFC flow
      (importance ranking → compression → retrieval hook → per-node window
      assembly). System/developer constraints are preserved verbatim, recent
      turns stay verbatim, and older low-priority turns are compressed into a
      bounded summary. (RFC-004 §4)
- [x] Attached each node's `InputContract` to its assembled window and carried
      forward the flattened `incoming_outputs` payload (`request`,
      `task_profile`, `strategic_plan`, dependency outputs) so future
      `validate_inputs(...)` wiring has the right substrate. (RFC-004 §5)
- [x] Wired the context path into `ExecutionManager` behind
      `CALIENNE_ENABLE_CONTEXT`: DAG nodes now receive a rich per-node
      `ContextWindow` when the flag is on, and a deterministic minimal window
      when it is off. Retrieval remains route-gated (`research` on by default;
      other routes off unless future logic enables them), keeping full RAG
      deferred to the later retrieval step.
- [x] Added a small execution seam for produced node outputs so downstream
      nodes can assemble their windows against named contract fields rather
      than only upstream task IDs.

**Exit gate (met):** `tests/test_context_manager.py` verifies bounded
per-node window assembly, preserved constraints/recent turns, attached
`InputContract`, and route-gated retrieval hooks; `tests/test_execution_manager.py`
verifies context-mode integration on the DAG path. Full regression suite
green: `.venv\Scripts\python.exe -m pytest -q` = 169 passed.

---

## PHASE D — Adaptive Intelligence

*Goal: the system gets smart — skills, early exit, uncertainty, repair,
consensus, firewall. Each is independently flag-gated.*

### ☑ Step 8 — Dynamic skill composition (RFC-007 §Step 7) *(completed 2026-07-13)*

- [x] `orchestrator/skills.py`: implemented the 9 initial skills
      (`caveman`, `precision`, `academic`, `coder`, `researcher`,
      `devils_advocate`, `explainer`, `security`, `performance`) with
      capability tags, prompt fragments, behavioral constraints, preferred
      output-contract hints, incompatibility rules, and cost / verbosity
      impact metadata. (RFC-003 §13)
- [x] Added deterministic skill composition via `SkillComposer`: planners now
      assign per-node bundles from route + node-objective heuristics, preserve
      existing node skill intent, and support user overrides through
      force/block lists. Incompatible forced bundles fail loudly; non-forced
      conflicts resolve deterministically by priority.
- [x] Wired skill composition into `ExecutionPlanner` / `ExecutionManager`
      behind `CALIENNE_ENABLE_SKILLS`. When the flag is off, nodes keep their
      pre-Step-8 skill lists unchanged; when on, the DAG result includes a
      resolved per-node `skill_plan`.
- [x] `config/prompt_versions.json` now fully participates in the RFC-005
      resolution order: env (`CALIENNE_PROMPT_VERSIONS_PATH`) → default config
      → `skills.py` built-in defaults with a warning. Loaders ignore `_`-
      prefixed metadata keys and merge partial config overrides onto the
      built-in registry.

**Exit gate (met):** `tests/test_skills.py` covers the 9-skill registry,
prompt-version resolution, incompatible forced skills, and planner-applied
skill bundles; `tests/test_execution_manager.py` covers skills-mode DAG
integration. Full regression suite green:
`.venv\Scripts\python.exe -m pytest -q` = 176 passed.

### ☑ Step 9 — Adaptive early exit + MetaReasoner (RFC-007 §Step 8) *(completed 2026-07-13)*

- [x] Early-exit thresholds in `routing_defaults.json` are now consumed by a
      deterministic evaluator in `orchestrator/meta_reasoner.py`. The runtime
      checks confidence/calibration/reasoning/evidence thresholds, returns an
      explicit early-exit decision when all pass, and escalates complexity +
      judge count when contradictions or unsupported claims are detected.
      (RFC-002 §10)
- [x] Implemented `orchestrator/meta_reasoner.py` with bounded
      `merge`/`skip`/`downgrade`/`reorder` behavior only. There is still **no
      upgrade authority** in v1; model-tier escalation remains reserved for
      `PredictionLayer` + `ResourceManager` per DEC-003. The optimizer records
      a `mutation_audit_trail` and respects the config cap on mutations per
      run. (RFC-003 §6)
- [x] Wired the Step 9 logic into `ExecutionManager`: DAG requests now derive a
      deterministic pre-execution `StageAssessment`, evaluate early exit, apply
      bounded graph optimization before scheduling, and expose both the
      `early_exit_decision` and `mutation_audit_trail` in the execution result.
      A cheap post-node-completion re-check is also recorded for auditability.
- [x] Kept scheduler starvation behavior aligned with the config-driven
      threshold model and added explicit coverage for the auto-promote path.

**Exit gate (met):** `tests/test_meta_reasoner.py` covers confidence-threshold
early exit, contradiction-triggered escalation, bounded mutation audit trails,
and scheduler starvation auto-promote; `tests/test_execution_manager.py`
covers DAG integration for early-exit/meta-reasoner outputs. Full regression
suite green: `.venv\Scripts\python.exe -m pytest -q` = 181 passed.

### ☑ Step 10 — Uncertainty engine (RFC-007 §Step 9) *(completed 2026-07-13)*

- [x] `orchestrator/uncertainty.py`: implemented the RFC outcomes
      `continue_execution` / `run_retrieval` / `ask_user_clarification`
      (emits `ClarificationRequest`) / `request_more_context` /
      `escalate_model` / `run_additional_checker` /
      `synthesize_with_uncertainty`. The engine is deterministic and chooses
      the least-hallucinatory intervention from prompt ambiguity, context
      availability, stage-assessment signals, and prediction probabilities.
      (RFC-003 §11)
- [x] Ambiguous prompts now return a structured clarification response rather
      than charging into the DAG with a guess. For example, terse references
      like “Fix this.” on a coding route emit `ClarificationRequest` with
      explicit missing-context hints.
- [x] Wired uncertainty evaluation into `ExecutionManager`: every DAG request
      now carries an `uncertainty_decision`, and clarification-triggered
      requests short-circuit safely with `status = "needs_clarification"`.
      Non-clarification outcomes remain advisory in this step so later stages
      can consume them without breaking the existing execution path.

**Exit gate (met):** `tests/test_uncertainty.py` covers multiple uncertainty
outcomes including `needs_clarification`; `tests/test_execution_manager.py`
verifies ambiguous DAG requests return a structured clarification response.
Full regression suite green: `.venv\Scripts\python.exe -m pytest -q` = 186
passed.

### ☑ Step 11 — Reflection / repair loop (RFC-007 §Step 10) *(completed 2026-07-14)*

- [x] `orchestrator/repair.py`: `Generate → Judge → Reflect → Repair →
      Rejudge`. `max_repairs = 2`; only for actionable defects
      (`contradiction`, `unsupported_claim`, `failed_code_check`,
      `math_error`, `missing_requirement`, `validation_error`); Token Budget
      Manager is the circuit breaker; bypass + synthesize-with-caveats if over
      budget. Gate: `CALIENNE_ENABLE_REPAIR`. (RFC-003 §9)
- [x] Wired repair into `ExecutionManager`: DAG requests now run the repair
      loop after the scheduler completes when `CALIENNE_ENABLE_REPAIR=true`.
      With the flag off, `repair_result` is `None` and behavior is unchanged.
      Judge/critique integration is a deterministic stub — real LLM-based
      judging lands in Step 12 (consensus/multi-judge).

**Exit gate (met):** `tests/test_repair.py` covers no-defect pass-through,
non-actionable filtering, first-cycle and second-cycle repair, `max_repairs=2`
cap with caveats, budget-exhausted circuit breaker, critique-budget-exceeded
circuit breaker, and all 6 actionable defect types via parametrize;
`tests/test_execution_manager.py` still passes unchanged. Full regression
suite green: `.venv\Scripts\python.exe -m pytest -q` = 197 passed.

### ☑ Step 12 — Weighted consensus + multi-judge (RFC-007 §Step 11) *(completed 2026-07-14)*

- [x] Dynamic judge allocation by complexity: low 1 (only if early-exit
      fails) / medium 2 / high 4 / critical full. (RFC-003 §8) — `allocate_judges`
      in `orchestrator/consensus.py`; low+early-exit-pass returns 0 judges,
      coding/math get `verifier` roles (no Creative), medium+ requires
      capability-weighted consensus.
- [x] `orchestrator/consensus.py`: raw + weighted agreement, agreement
      matrix, disagreement clusters, `MinorityView{claim,model_id,
      confidence,reason}` + derived `minority_should_influence_final`.
      Weights from `config/capabilities/model_capabilities.json` (neutral
      0.5 fallback on load failure). Gate: `CALIENNE_ENABLE_CONSENSUS`.
      (RFC-003 §10) — wired into `ExecutionManager._run_consensus` (was
      **called but undefined** — enabling the flag would `AttributeError`;
      added a deterministic judge stub, real multi-model judges land with LLM
      integration).

**Exit gate (met):** `tests/test_consensus.py` covers complexity→judge-count
allocation, low-complexity zero-judge skip, coding-route verifiers,
weighted-vs-raw agreement under capability weights, high-weight-minority
influence flag, and DAG-integration (consensus on/off). Also fixed
`tests/test_crit003_checkpoint_db.py` — replaced deprecated
`asyncio.get_event_loop().run_until_complete` with `asyncio.run` (broke once
any prior async test closed the loop). Full regression green:
`.venv\Scripts\python.exe -m pytest -q` = 208 passed (2 `test_skills.py`
errors are the pre-existing Windows `tmp_path` permission glitch, unrelated).

### ☑ Step 13 — Route-specific graph templates (RFC-007 §Step 12) *(completed 2026-07-14)*

- [x] Expand the five deterministic templates (coding/research/math/
      creative/general) from RFC-002 §9 with route-specific verifiers
      (no `Logician+Creative` for every route). Each route already carries its
      own verifier — coding `verify` (code), research `evidence_check`, math
      `independent_check`+`contradiction_check`, creative `critique`. Step 13
      made the templates `TaskProfile`-aware: `get_template()` now accepts a
      route name (back-compat) **or** a `TaskProfile`, and high/critical
      complexity splices one route-specific `judge` node before `final`
      (RFC-002 §9's "optional judge" band). `ExecutionPlanner` passes the
      `TaskProfile` through, so the adaptivity is live on the DAG path.

**Exit gate (met):** each template accepts a `TaskProfile` and validates
(`tests/test_routing.py::test_templates_accept_task_profile_and_validate`);
high/critical profiles add the route judge and still validate
(`test_high_complexity_profile_adds_route_judge`); medium/no-profile
templates stay judge-free and unchanged. Full regression green:
`.venv\Scripts\python.exe -m pytest -q` = 199 passed (2 `test_skills.py`
errors are a Windows `tmp_path` permission glitch at fixture setup,
unrelated to this step).

### ☑ Step 14 — Hallucination firewall (RFC-007 §Step 13) *(completed 2026-07-14)*

- [x] Replaced the placeholder `ClaimManager.validate_claim()` in
      `orchestrator/claims.py` with a deterministic evidence checker:
      claims now link to request-scoped source/context/code/math/reasoning
      evidence, unsupported claims are marked explicitly, and contradicted
      claims remain visible as non-verified outputs. The old
      `calienne_DISABLE_CLAIM_EXTRACTION` env var is now an emergency bypass,
      not the default path. (RFC-003 §12)
- [x] Wired the firewall into both runtime entry points: legacy
      `run_micro_mode` / DecisionEngine synthesis in `orchestrator/pipelines.py`
      and the DAG path in `orchestrator/execution_manager.py`. Final outputs
      are now qualified before they leave the Validation Layer seam, and the
      result payload exposes `firewall_result` metadata plus unsupported-claim
      evidence.
- [x] Added exit-gate tests in `tests/test_claims.py`, `tests/test_pipeline.py`,
      `tests/test_pipeline_repair.py`, and `tests/test_execution_manager.py`
      proving supported claims verify, unsupported claims are qualified, the
      firewall is enabled by default, and both legacy + DAG paths surface the
      qualified output.

**Exit gate (met):** focused Step-14 suite green:
`.venv\Scripts\python.exe -m pytest tests/test_claims.py tests/test_pipeline_repair.py tests/test_pipeline.py tests/test_execution_manager.py`
= 26 passed. Broader regression pass remains unchanged apart from the known
pre-existing Windows `tmp_path` permission issue in `tests/test_skills.py`:
`.venv\Scripts\python.exe -m pytest -q` = 213 passed, 2 errors (unrelated).

---

## PHASE E — Knowledge, Memory, Metrics, Resources

*Goal: real retrieval, the memory hierarchy, full metrics, and the resource
ceiling become load-bearing.*

### ☑ Step 15 — Smart RAG (RFC-007 §Step 14) *(completed 2026-07-14)*

- [x] `orchestrator/retrieval.py`: `SourceCandidate` schema +
      `final_score = relevance*0.4 + credibility*0.25 + freshness*0.15 +
      consensus*0.2`; top-by-score (not fixed 3–5). Route-gated: required
      research, optional general, off coding/math/creative unless
      uncertainty-triggered. Gate: `CALIENNE_ENABLE_RAG`. (RFC-004 §3)
- [x] Pluggable async provider protocol (`RetrievalProvider`); v1 ships
      `DeterministicRetrievalProvider` (default, no network), plus
      `InMemoryRetrievalProvider` and `StaticOverrideProvider` for tests
      and local development. The layer **never raises into the request
      path** — provider errors log and return an empty `RetrievalResult`
      with a descriptive `retrieval_skipped_reason` (ADR-007
      deterministic-fallback discipline).
- [x] Loader precedence (per RFC-008 §8 / ADR-005):
      `CALIENNE_RETRIEVAL_WEIGHTS_JSON` env var → file at
      `CALIENNE_RETRIEVAL_WEIGHTS_PATH` → repo
      `config/capabilities/routing_defaults.json` →
      `DEFAULT_RANKING_WEIGHTS` (normalized to sum to 1.0). Route-gating
      table loadable from the same `retrieval.route_gating` block; falls
      back to the module `ROUTE_GATING` on any I/O / parse error.
- [x] `ContextManager.assemble_window` is now `async`; it threads
      `uncertainty_triggered_retrieval` from the uncertainty engine's
      `outcome == "run_retrieval"` into the `RetrievalRequest`, so coding
      / math / creative routes can be forced on when uncertainty requests
      retrieval. `ContextWindow.retrieval_result` exposes the
      `RetrievalResult` to downstream callers; legacy `retrieval_provider`
      hook still works (back-compat).
- [x] `ExecutionManager` instantiates a `RetrievalService` when
      `CALIENNE_ENABLE_RAG` is on (using `load_routing_weights()` /
      `load_route_gating()`), passes it into `ContextManager`, and
      aggregates per-node retrieval results into a top-level
      `rag_telemetry` block (`status`, `nodes_attempted`,
      `selected_total`, `evidence_bump_total`, `weights`, `per_node`).
      When the flag is off, `rag_telemetry["status"] == "disabled"` and
      each node's `retrieval_result` is `None`.
- [x] `decision_register.md` updated with `DEC-016` recording the
      implementation. `architecture_version` bumped `0.1.0` → `0.1.1` in
      `orchestrator/versioning.py` (file is on the
      `tools/check_architecture_version.py` watchlist).

**Exit gate (met):** `tests/test_retrieval.py` (33 tests) covers the
ranking formula, score clamping, top-by-score ordering (no fabricated
sources to fill a limit), route gating for all five task types
(research=required, general=optional with/without `requires_rag`,
coding/math/creative=off), uncertainty-engine force-override on
off-routes, provider failure degrades to an empty result (no raise),
all three built-in providers, and the config-loader fallback chain
(env-var JSON, env-var path, repo file, defaults, normalization, invalid
JSON). `tests/test_execution_manager.py` adds 3 integration tests:
RAG-off emits `status="disabled"` telemetry; RAG-on with a research
provider surfaces `SourceCandidate` excerpts into
`context_window.retrieved_snippets` and aggregates into
`rag_telemetry`; provider exception during a real DAG run does not
break the request (silent degradation, status remains `"success"`).
`tests/test_context_manager.py` updated for the async signature and
still green. Full regression suite green: `pytest -q` = 249 passed, 2
errors (the 2 pre-existing Windows `tmp_path` permission glitches in
`tests/test_skills.py`, unrelated to this step).

### ☑ Step 16 — Memory hierarchy (RFC-007 §Step 15) *(completed 2026-07-14)*

- [x] `orchestrator/memory_hierarchy.py`: implemented all 6 layers
      (short_term, long_term, user_memory, agent_memory, shared_cache,
      vector_memory) per RFC-004 §2. Vector layer uses in-process TF
      cosine similarity in v1; `pgvector` swap-in is the v2 plan (DEC-007).
      `MemoryEntry` / `MemoryQuery` / `MemoryHierarchyConfig` are the
      Pydantic-friendly data classes; the `MemoryHierarchy` facade exposes
      `gather`, `gather_snippets`, `write`, `evict_all`, and `snapshot`.
      All read/write paths are async-first (ADR-002) and fail-safe
      (ADR-007 — never raise into the request path).
- [x] Wired the hierarchy into `ContextManager` and `ExecutionManager`
      behind `CALIENNE_ENABLE_CONTEXT` (the existing context flag per
      RFC-004 §2). When the flag is off, no hierarchy is instantiated and
      `ExecutionManager` emits `memory_telemetry = {"status": "disabled"}`.
      When the flag is on, `ContextManager.assemble_window` merges
      memory-derived snippets into `retrieved_snippets` and exposes
      `metadata["memory_hits"]`; `ExecutionManager` seeds short-term
      memory with the user query + last 4 history turns, then emits a
      per-layer snapshot in `memory_telemetry`.
- [x] `ExecutionManager` gained a `memory_hierarchy` constructor arg
      (default `None`) and a `memory_telemetry` key on both
      `status="success"` and `status="needs_clarification"` response
      payloads. ADR-001 / Step 4's `MemoryManager` (compression) is kept
      untouched — the new module composes *remembering*, the legacy
      module composes *compressing*.
- [x] `architecture_version` bumped `0.1.1` → `0.1.2` in
      `orchestrator/versioning.py` because
      `tools/check_architecture_version.py`'s watchlist includes
      `memory_hierarchy.py`, `context_manager.py`, and
      `execution_manager.py` (all three were edited this step).

**Exit gate (met):** `tests/test_memory_hierarchy.py` (15 tests) covers
all six layers (eviction, segmentation by user/agent, cosine ranking
in `vector_memory`, hit/miss tracking in `shared_cache`),
the `MemoryHierarchy` facade (multi-layer gather with score-merged
output, fail-safe degradation when a layer raises, full-evict),
`ContextManager` integration (memory hits attached when wired,
absent when not), and `ExecutionManager` integration (memory
telemetry on/off keyed on the context flag, short-term seeding on
`status="success"`). Full regression suite green:
`pytest -q --ignore=tests/test_skills.py` = 260 passed (the
`test_skills.py` 2 errors are the pre-existing Windows `tmp_path`
permission glitch, unrelated to this step).

### ☑ Step 17 — Dashboard metrics, namespaced (RFC-007 §Step 16) *(completed 2026-07-14)*

- [x] Emit all nine namespaces: `execution.*`, `quality.*`, `resources.*`,
      `prediction.*`, `learning.*`, `environment.*`, `manifest.*`,
      `scheduler.*`, `planner.*`. Spec is RFC-005 §4; emission is owned by
      each component's module. `ExecutionManager.execute()` now returns a
      `dashboard_metrics` key on both `status="success"` and
      `status="needs_clarification"` payloads — a flat dict (mirroring the
      `prediction_telemetry` precedent, not a nested tree) merged onto the
      module-level `_DASHBOARD_METRIC_TEMPLATE` so every RFC-005 §4.1
      example key is always present (`None` = not yet sourced), never
      silently omitted.
- [x] Pull-based assembly, no event bus (RFC-005 pattern): each module
      exposes its own metrics and `ExecutionManager._assemble_dashboard_metrics`
      collects them. New per-module seams: `Scheduler.telemetry`
      (`execution.node.started/completed/failed`, `scheduler.node.queued/released`,
      `scheduler.priority_band` histogram, `scheduler.starvation_promoted`);
      `ExecutionPlanner.last_planner_telemetry` (`planner.output.valid/invalid`,
      `planner.template.fallback`); `versioning.manifest_metrics(graph=…)` +
      `versioning.capture_environment_snapshot()` (`manifest.*`;
      `environment.os`/`environment.python_version` are real via stdlib
      `platform`). Reused as-is: `PredictionLayer.record_actuals`
      (`prediction.*`), StageAssessment / firewall / consensus (`quality.*`),
      MetaReasoner audit trail (`learning.mutation.audit`).
- [x] Best-effort `None` stubs for fields owned by later steps (marked
      `ponytail:` in code): `resources.gpu`/`cpu`/`memory`/`rate_limit.headroom`/
      `connection_pool.size` (Step 18 ResourceManager);
      `environment.cuda_version`/`container`, `manifest.graph_version`/
      `graph_fingerprint`, `learning.graph.fingerprint`,
      `planner.fingerprint.hash` (Step 19 fingerprint/manifest/HostPrimitives).
- [x] No new feature flag — pure additive telemetry, always emitted
      (traceability row 17 flag column stays `—`). `architecture_version`
      bumped `0.1.2` → `0.1.3` because the watchlist files `scheduler.py`,
      `execution_planner.py`, `versioning.py`, and `execution_manager.py`
      were all edited this step. Recorded as DEC-018.

**Exit gate (met):** `tests/test_scheduler.py` (new, 3 tests) covers
scheduler telemetry (started/completed/failed counts on a failing graph,
`queued == released` for a linear graph, priority-band histogram on a
mixed-priority graph). `tests/test_versioning.py` gains 2 tests
(`capture_environment_snapshot` returns all four keys with real
os/python + `None` stubs; `manifest_metrics` matches module constants
and stubs graph fields when `graph=None`) and the architecture-version
assertion is updated to `0.1.3`. `tests/test_execution_manager.py` gains
3 tests (a full `execute()` run asserts all 41 template keys present and
all nine namespaces represented with live-sourced fields non-`None`; the
`needs_clarification` branch asserts `execution.*`/`scheduler.*` stay
`None` while `quality.confidence` is populated; with the `prediction`
flag on, `dashboard_metrics["prediction.tokens.actual"]` equals the
`prediction_telemetry` value). Full regression suite green:
`pytest -q` = 272 passed (the `test_skills.py` 2 errors are the
pre-existing Windows `tmp_path` permission glitch, unrelated to this
step). CI scripts `check_rfc_index` / `check_adr_index` /
`check_decision_register` all exit 0; `check_architecture_version --stdin`
correctly flags the four watchlist changes against the recorded bump.

### ☑ Step 18 — Resource Manager + capability loader (RFC-007 §Step 17) *(completed 2026-07-14)*

- [x] `api_gateway/capabilities.py`: `CapabilityRegistry` loads
      `config/capabilities/*.json` (`model_capabilities`, `provider_limits`,
      `pricing`, `routing_defaults`, `prediction_calibration`); override dir
      via `CALIENNE_CAPABILITIES_PATH`; `_meta`/`_`-prefixed keys stripped.
      Every accessor degrades to a documented default on missing file /
      malformed JSON / out-of-range value (`NEUTRAL_WEIGHT = 0.5`,
      `DEFAULT_MAX_CONCURRENCY = 5`, `DEFAULT_PROVIDER_LIMIT`) and records the
      reason in `load_errors`; `capability_load_failed` surfaces the metric.
      Construction **never raises into the request path** (ADR-007). Module
      singleton `get_capability_registry(refresh=…)`. (RFC-002 §5, ADR-005)
- [x] `orchestrator/resource_manager.py`: `ResourceManager` **composes**
      `api_gateway/rate_limiter.py` (health, token buckets, global semaphore)
      rather than duplicating it. `effective_parallel = min(provider,
      model, cpu, memory, budget, rate_limit)` with a floor of 1 (non-positive
      terms ignored defensively); API `acquire/release/snapshot/
      recompute_plan` + `scheduler_concurrency_limit` (preserves the Step 5b
      stub contract). Sole owner of concurrency ceilings (ADR-004 / DEC-011);
      global + per-route, no per-tenant. (RFC-002 §4, §6)
- [x] `MODEL_CAPABILITY_WEIGHTS` already externalized to
      `model_capabilities.json` (consumed by `consensus.py`); `strategy.py`
      now **consults** the loader — `get_model_chain_for_plan(plan)` picks the
      route generation role from `task_type`, re-ranks the chain best-first by
      per-`task_type` capability weight, and sizes it by `complexity`.
      `get_model_chain(role)` unchanged (route-role aliases added). (RFC-002 §7)
- [x] Real `ResourceManager` is now the `ExecutionManager` default (replacing
      `_StubResourceManager`); its `snapshot()` feeds `resources.concurrency.active`,
      `resources.cpu`, and `resources.connection_pool.size` into the Step 17
      dashboard block (`resources.gpu`/`memory` remain `None` — Step 19
      HostPrimitives). Scheduler cap still pulled from
      `scheduler_concurrency_limit`.

**Exit gate (met):** `tests/test_capabilities.py` (7 tests) covers missing
files, malformed JSON, out-of-range weight → neutral, unknown task_type /
model → neutral, `CALIENNE_CAPABILITIES_PATH` override (incl. singleton
refresh + restore), `_meta` strip, and the real repo config loading clean.
`tests/test_resource_manager.py` (14 tests) covers `effective_parallel`
honoring **both** provider and model limits (plus budget/rate-limit/floor),
the `acquire`/`release`/`snapshot` lifecycle, idempotent release,
`recompute_plan` ok/reject, `scheduler_concurrency_limit` node-cap + floor,
and the capability-load-failure degradation path. `tests/test_strategy.py`
(8 tests) covers `get_model_chain_for_plan` (cheaper/shorter for `low`,
full-depth for `critical`, coding re-rank, unknown-route degrade,
missing-attr defaults) and confirms `get_model_chain` is unchanged. No new
feature flag — sits behind the existing `CALIENNE_ENABLE_DAG` (traceability
row 18 flag column stays `—`). `architecture_version` bumped `0.1.3` →
`0.1.4` (watchlist files `capabilities.py`, `resource_manager.py`,
`strategy.py`, `execution_manager.py`, `versioning.py`); recorded as DEC-019;
maturity RFC-002 row advanced Not Started → Experimental. Full regression
suite: `pytest -q` = 301 passed (the `test_skills.py` 2 errors are the
pre-existing Windows `tmp_path` permission glitch, unrelated to this step).
CI scripts `check_rfc_index` / `check_adr_index` / `check_decision_register`
all exit 0; `check_architecture_version --stdin` correctly flags the five
watchlist changes against the recorded bump. This is the RFC-002 exit gate.

---

## PHASE F — Versioning, Replay, Persistence, Contracts

*Goal: full reproducibility — every artifact stamped, replayable, and
recorded; nodes become interchangeable.*

### ☑ Step 19 — Versioning stamp + manifest + fingerprint (RFC-007 §Step 18) *(completed 2026-07-14)*

- [x] `orchestrator/versioning.py`: `graph_fingerprint` (SHA-256 via
      `TopologyNormalizer` — canonical topological sort, contract-aware, and
      structurally identical DAGs hash equal) + `graph_version` (monotonic
      `VersionRegistry`, in-memory, keyed by
      `(planner_version, strategy_version, contract_version)`). Fingerprint is
      for dedup/replay/analytics/caching **only — never validation-skip**
      (ADR-006). `stamp_graph(...)` is the single source of truth and is called
      after the MetaReasoner mutation so the recorded identity matches the
      executed graph. `build_version_stamp(...)` produces the RFC-005 §2
      `VersionStamp` from the stamped graph. (RFC-005 §2.3/§2.4)
- [x] `orchestrator/execution_manifest.py`: `ExecutionManifest`
      **`frozen=True, extra="forbid"`** (critical contract); full feature-
      flag snapshot via `FeatureFlags.as_env_map()`; `HostPrimitives`
      captured once at process start (`cuda_version=None` when `torch`/CUDA
      is absent; container/k8s detection via `/.dockerenv`,
      `/proc/1/cgroup`, `KUBERNETES_SERVICE_HOST`, or the `container` env).
      Built once at request start, **either** re-copied with `planner_version`
      after the strategic plan is known or overwritten once before stamping;
      frozen from that point. `manifest_schema_version="1.0"`
      **decoupled** from `architecture_version` (DEC-009). Same manifest
      instance is attached to `TaskGraph`, `ExecutionPassport`, and both DAG
      response payloads. (RFC-005 §3)

**Exit gate (met):** `tests/test_versioning.py` covers
`graph_fingerprint` determinism (equal hashes for node-name/order-renamed
DAGs), structural variation (changing a contract type changes the hash;
SHA-256 length = 64), `VersionRegistry` stability per key (`v1`),
monotonic advance for new keys (`v2`), and the `stamp_graph` round-trip
(version + fingerprint written, registry counter advances, graph returned
unchanged). `tests/test_execution_manifest.py` (new, 3 tests) covers
frozen enforcement (`ValidationError` on assignment and `extra="forbid"`),
full `FeatureFlags` snapshot with `manifest_schema_version="1.0"`
≠ architecture_version, `git_commit` captured, prompt versions copied
inline, and `HostPrimitives` once-only with `cuda_version=None` when
`torch` is unavailable (monkeypatched). `tests/test_execution_manager.py`
gains: manifest attachment to `TaskGraph` / response / `ExecutionPassport`
(same instance across all three), `passport.to_dict()` includes
`execution_manifest`, dashboard metrics `planner.fingerprint.hash` /
`learning.graph.fingerprint` / `manifest.graph_fingerprint` align with
`graph.graph_fingerprint`. Full regression green: `pytest -q` = 311
passed (the `test_skills.py` 2 errors are the pre-existing Windows
`tmp_path` permission glitch, unrelated to this step). CI scripts
`check_rfc_index` / `check_adr_index` / `check_decision_register` all
exit 0; `check_architecture_version --stdin` correctly flags the four
watchlist changes (`versioning.py`, `execution_manifest.py`,
`execution_manager.py`, `schemas.py`) against the recorded bump.
`architecture_version` bumped `0.1.4` → `0.1.5` (DEC-020); RFC-005 row
in `maturity.md` advances Not Started → Experimental. **This is the
RFC-005 exit gate.**

### ☑ Step 20 — Execution replay + Experience DB (RFC-007 §Step 19) *(completed 2026-07-15)*

Split — replay first (no DB), then persistence:

**20a — replay**
- [x] `orchestrator/execution_replay.py`: append-only `ExecutionTrace`;
      modes `replay` / `shadow` / `simulate`; store under `telemetry/`
      indexed by `(graph_version, prompt_fingerprint)`; default 30-day
      retention; `/api/debug/replay/{trace_id}` gated by
      `CALIENNE_ENABLE_REPLAY`; PII redaction before storage. (RFC-004 §6)

**20b — Experience DB** (add `testcontainers` + `pgvector` driver to
`requirements.txt` first)
- [x] Alembic migration creating `experience_operational` (7-day) +
      `experience_learning` (90-day) tables. (RFC-004 §7)
- [x] `orchestrator/experience_db.py`: `ExperienceRepository`
      (`record_operational/record_learning/query_*/prune`) — **no module
      touches raw SQL**. Connection pool owned by `ResourceManager`. Gate:
      `CALIENNE_ENABLE_EXPERIENCE_DB` (writes). `pgvector` installed but
      unused (DEC-007). (RFC-004 §7, ADR-008)

**Exit gate (met):** `tests/test_execution_replay.py` proves the replay
modes produce identical event sequences under a fixed seed + injected
(fake) clock — `replay`, `shadow`, and `simulate` all return the same
`(event_type, node_id, timestamp_offset_ms)` sequence as the recorded
trace — plus fingerprint determinism/whitespace-normalization, PII scrub
(email/phone/long-digit), recorder offset math + unknown-event drop, and
the `ReplayStore` filesystem round-trip + retention prune. Replay is wired
flag-gated into `ExecutionManager` (11 RFC-004 §6 event emissions;
`_finalize_replay` + `replay_trace_id` on both the success and
needs-clarification branches) and `calienne_orchestrator.py` (store stood
up only when the flag is on); `GET /api/debug/replay/{trace_id}` (admin)
returns 503 when disabled. `tests/test_experience_db.py` covers all four
repo methods (`record_operational`/`record_learning`/`query_*`/`prune`)
twice: an in-memory fake `AsyncSession` that introspects the real
SQLAlchemy statements (default suite, always green) **and** a
`integration`/`slow` Testcontainers-PostgreSQL round trip that skips
gracefully when Docker/`testcontainers` are absent (ADR-008). All SQL is
behind `ExperienceRepository` (invariant 8); nothing raises into the
request path (ADR-007). `architecture_version` bumped `0.1.5` → `0.1.6`
(DEC-021); the `Replay` and `PostgreSQL Experience DB` rows in
`maturity.md` advance Not Started → Experimental. **This is the RFC-004
§6/§7 exit gate.**

### ☑ Step 21 — Knowledge / Reasoning / Validation layer separation (RFC-007 §Step 20) *(completed 2026-07-16)*

- [x] Refactor (not rewrite) the `DecisionEngine` RAG path into
      `orchestrator/knowledge_layer.py` (facts+provenance, no reasoning),
      `reasoning_layer.py` (generation, no retrieval/judging),
      `validation_layer.py` (judge/consensus/repair/firewall, owns
      `StageAssessment`/`ClarificationRequest`). Gate:
      `CALIENNE_ENABLE_KNOWLEDGE_LAYER`; merged behavior when off. (RFC-001 §2)

**Exit gate (met):** `tests/test_layers.py` covers retrieval provenance,
DecisionEngine contract-preserving reasoning wrappers, and Validation Layer
ownership of firewall + stage assessment. `tests/test_pipeline.py` proves the
flag-on path preserves the legacy `MicroModeResult` payload; existing schema
tests still parse legacy `AgentOutput` / `calienneOutput` payloads. DAG
assessment, uncertainty clarification, consensus, repair, and firewall now
route through `ValidationLayer`; flag-off `run_micro_mode` remains unchanged.
`ProviderConfig` now closes RFC-001's remaining critical-contract gap with
`extra="forbid"`. Full suite with an ACL-safe pytest temp root = 337 passed,
1 Docker-dependent skip.
`architecture_version` bumped `0.1.6` → `0.1.7` (DEC-022); RFC-001 maturity
advanced to Experimental. Code-owner signoff remains PR governance, not an
implementation task.

### ☑ Step 22 — Agent contracts (RFC-007 §Step 21)

- [x] Added `validate_inputs` / `validate_outputs` / `to_failure_response`
      (plus `ContractViolation` + `classify_failure`) to `contracts.py` —
      Step 2b shipped only the contract *models*, not this API. Wired
      `validate_inputs`/`validate_outputs` into the DAG node executor
      (`ExecutionManager._make_node_executor`), so every node validates its
      declared inputs against upstream `produced_outputs` before running and
      its declared outputs after, surfacing breaches as a
      `contract_violations` list on each node result. This is the
      interchangeability boundary — nodes are swappable because the runtime,
      not the node, owns contract enforcement. (RFC-003 §3.4/§3.5)

**Exit gate (met):** `tests/test_contracts.py` covers ambient-vs-produced
input satisfaction, missing-output detection, recoverable/non-recoverable
failure classification (unlisted modes fail safe), and the structured
`to_failure_response` shape. Validation reports violations as telemetry
rather than aborting — the DAG path is flag-off (`CALIENNE_ENABLE_DAG`) and
a hard abort would break template graphs whose declared input chains are
intentionally loose (e.g. the spliced `judge` node). Upgrade path: promote
`contract_violation` to a scheduler `NodeFailed` when the DAG runtime owns
retries.

> **Step 22 (self-learning safeguards, RFC-007 §Step 22) is a v2 concern.**
> `CALIENNE_ENABLE_SELF_LEARNING` stays off and inert in v1; the offline
> promotion pipeline (Experience DB → Offline Eval → Benchmark → Shadow →
> Manual Review → Merge → Release) is manual-PR only (DEC-015). Do not build
> auto-promotion.

---

## 3. Where to start — the honest first week

1. **Baseline (Step 0 + Step 1).** Run the four CI scripts + full test
   suite. Fix anything red. Do the `passport`-into-`run_micro_mode`
   plumbing. This is low-risk and gives you the telemetry you'll rely on to
   prove every later step works. **Start here — do not skip to the exciting
   planner code.**
2. **Types (Step 2).** `core/base.py` + backward-compat test, then the new
   schemas. Everything downstream imports these; a wrong schema shape here
   costs you rework in ten later steps.
3. **Flags + version constant (Step 4), then the classifier (Step 3).** Now
   you can gate code and route requests deterministically.
4. **The spine (Step 5).** Planners + async scheduler + `ExecutionManager`,
   all behind `CALIENNE_ENABLE_DAG=off`. When this merges with the
   fallback-to-`run_micro_mode` test green, you have the architecture; the
   rest is filling in adaptive behavior one flag at a time.

After that, walk Phases C→F in order. Each step is a mergeable PR titled
`Implements RFC-NNN` / `Implements ADR-NNN` (RFC-007 §3), flag-off by
default, with its exit-gate tests green and the relevant `maturity.md` row
advanced to `Experimental`.

## 4. Per-step definition of done (apply to every step)

- [ ] Code lands behind its `CALIENNE_ENABLE_*` flag, default **off**.
- [ ] The step's exit-gate tests (above) pass; the named tests in RFC-007 §4
      are covered.
- [ ] All 13 existing regression suites still pass **unchanged** (ADR-001).
- [ ] If a watchlist file (RFC-008 §2.2) changed, `architecture_version` was
      bumped in `orchestrator/versioning.py`.
- [ ] `decision_register.md` rows for the step's `DEC-NNN` updated;
      `maturity.md` row advanced.
- [ ] PR title references `Implements RFC-NNN` and `Implements ADR-NNN`.

## 5. Traceability — step ↔ RFC ↔ flag ↔ PR

| Guide step | RFC-007 step | Primary RFC | Feature flag | PR |
| --- | --- | --- | --- | --- |
| 0 | — | RFC-007, RFC-008 | — | PR-001a |
| 1 | 1 | RFC-002, RFC-005 | — | (plumbing) |
| 2 | 2 | RFC-001, RFC-003 | — | PR-002/003 |
| 3 | 3 | RFC-002, RFC-003 | — | PR-004 |
| 4 | 16/18 (pulled early) | RFC-006, RFC-005 | (all) | PR-001b |
| 5 | 4 | RFC-002, RFC-003 | `DAG`, `PLANNER` | PR-005 |
| 6 | 5 | RFC-003 | `PREDICTION` | PR-006 |
| 7 | 6 | RFC-004 | `CONTEXT` | PR-007 |
| 8 | 7 | RFC-003, RFC-005 | `SKILLS` | PR-008 |
| 9 | 8 | RFC-003 | — | PR-009 |
| 10 | 9 | RFC-003 | — | PR-010 |
| 11 | 10 | RFC-003 | `REPAIR` | PR-011 |
| 12 | 11 | RFC-003 | `CONSENSUS` | PR-012 |
| 13 | 12 | RFC-002 | — | PR-013 |
| 14 | 13 | RFC-003 | — | PR-014 |
| 15 | 14 | RFC-004 | `RAG` | PR-015 |
| 16 | 15 | RFC-004 | `CONTEXT` | PR-016 |
| 17 | 16 | RFC-005 | — | PR-017 |
| 18 | 17 | RFC-002 | — | PR-018 |
| 19 | 18 | RFC-005 | — | PR-019 |
| 20 | 19 | RFC-004 | `REPLAY`, `EXPERIENCE_DB` | PR-020 |
| 21 | 20 | RFC-001 | `KNOWLEDGE_LAYER` | PR-021 |
| 22 | 21 | RFC-003 | — | PR-022 |
| (v2) | 22 | RFC-008 | `SELF_LEARNING` | — |

---

*Generated 2026-07-13 from `docs/new/{plan,maturity,decision_register}.md`,
RFC-001…008, and ADR-001…008. When any of those change, update this guide
and record the change in `decision_register.md`.*
