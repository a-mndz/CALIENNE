# RFC-002: Execution Pipeline

- **Status:** Not Started
- **Architecture version:** `0.1.0`
- **Related ADRs:** ADR-002, ADR-004, ADR-005
- **Owning decisions:** DEC-001, DEC-011, DEC-014

## 1. Purpose

This RFC defines the **execution front-end** of the CALIENNE runtime:
the deterministic `IntentAnalyzer`, the `ExecutionManager` that owns
the event loop, and the `ResourceManager` ceiling rules. It does not
define the planner or the scheduler (RFC-003), memory or RAG
(RFC-004), versioning or the manifest (RFC-005), feature flags
(RFC-006), the roadmap (RFC-007), or governance (RFC-008).

## 2. IntentAnalyzer

`orchestrator/routing.py` exposes the `IntentAnalyzer`. It is
**deterministic and token-free** (regex / string matching only; no
LLM calls). It runs upstream of every planner.

### 2.1 Responsibilities

- Classify the request into one of five routes: `coding`, `research`,
  `math`, `creative`, `general`.
- Score complexity: `low`, `medium`, `high`, `critical`.
- Emit the `needs_decomposition` signal that gates the
  `StrategicPlanner` (RFC-003 §2).
- Return a `TaskProfile` (RFC-003 §3) before any planner or generation
  stage runs.

### 2.2 Route detection

- **Coding**: file paths, stack traces, repo / code keywords.
- **Research**: source / citation / current-events keywords.
- **Math**: equation / proof / calculation keywords.
- **Creative**: branding / story / design / copy keywords.
- **General**: fallback.

### 2.3 Complexity scoring

- **Low**: direct factual / helpful question.
- **Medium**: multi-step or needs one verification pass.
- **High**: multiple constraints, code changes, research, high
  ambiguity.
- **Critical**: security, finance, medical / legal, destructive
  actions, production-impacting code.

`IntentAnalyzer` is **merged with the deterministic complexity
router** (originally specified as a separate step in the planning
thread). Merging ensures the planners and templates consume one
artifact — the `TaskProfile` — not two.

## 3. ExecutionManager

`orchestrator/execution_manager.py` is the owner of the event loop
and the entry point for every request.

### 3.1 Responsibilities

- Build `TaskProfile` via `IntentAnalyzer`.
- Build or request `TaskGraph` via the planner (RFC-003) or a
  deterministic template.
- Validate the graph (RFC-003 §3).
- Build `PipelineBudget` (RFC-003 §5).
- Request `Prediction` from `PredictionLayer` (RFC-003 §6).
- Assemble per-node context via `ContextManager` (RFC-004 §5).
- Delegate scheduling to the `Scheduler` (RFC-003 §4).
- Select fallback models via `ProviderStrategy` (RFC-002 §7).
- Cancel unnecessary stages on early exit (RFC-003 §7).
- Delegate actual provider calls to `RuntimeEngine`.
- Emit `execution.*` and `planner.*` telemetry namespaces (spec
  in RFC-005 §4).

### 3.2 Relationship to `DecisionEngine`

The existing `DecisionEngine` in `orchestrator/decisions.py` is kept
as a lower-level compatibility executor initially. The new
`ExecutionManager` wraps it instead of replacing everything in one
step. When `CALIENNE_ENABLE_DAG` is off, the request falls back to
the existing `run_micro_mode` path.

## 4. ResourceManager

`orchestrator/resource_manager.py` is the **sole owner** of
concurrency, ceilings, and rate-limit state. The scheduler
(RFC-003) is a client.

### 4.1 Owned resources

- `gpu_budget`, `api_budget_per_minute`, `concurrency_slots` (per
  route, per provider), `rate_limit_quotas`, `memory_ceiling`
  (token + RAM), per-provider circuit-breaker state.

### 4.2 API

- `acquire(node) -> Reservation | Reject(reason)`
- `release(reservation)`
- `snapshot() -> ResourceState` — fed to metrics, dashboard,
  predictions.
- `recompute_plan(graph, prediction)` — returns whether the graph
  can run as-is, must be downgraded, or must be rejected.

### 4.3 Scope

- **Global** with **per-route overrides**. Global owns CPU, RAM, API
  budget, concurrency, and provider health; per-route owns preferred
  model tier, token budget, and latency target.
- **No per-tenant in v1.**

### 4.4 Backing implementation

Backed by **extending** `api_gateway/rate_limiter.py`
`ResourceManager`, not duplicating it. The existing class already
exposes `ResourceManager.GLOBAL_CONCURRENCY_LIMIT` and a per-provider
`TokenBucket`; the new module composes them into the
`effective_parallel` calculation (RFC-002 §6).

## 5. Capability File Layout

Capability configuration lives under `config/capabilities/` (per
ADR-005). Never hardcoded in orchestration logic.

```text
config/
└── capabilities/
    ├── model_capabilities.json
    ├── provider_limits.json
    ├── pricing.json
    ├── routing_defaults.json
    └── prediction_calibration.json
```

Loader: `api_gateway/capabilities.py`. Override path:
`CALIENNE_CAPABILITIES_PATH=/abs/path/to/dir`. On load failure: log a
warning, fall back to a neutral default of `0.5`, emit a
`capability_load_failed` metric. **Never** raise into the request
path.

## 6. Concurrency Source (the `effective_parallel` calculation)

Configuration provides **limits**; `ResourceManager` computes
**effective concurrency** at runtime. Both layers are honored (per
ADR-004):

```python
effective_parallel = min(
    provider.parallel_limit,    # from provider_limits.json
    model.max_concurrency,      # embedded in model_capabilities.json
    system.cpu_limit,
    system.memory_limit,
    budget.parallel_limit,
    rate_limit.remaining,
)
```

This gives `ResourceManager` real global awareness (RFC-002 §4) and
gives config authors a clean declarative surface.

## 7. ProviderStrategy

`api_gateway/strategy.py` `ProviderStrategy` is extended with
route-aware role names and `get_model_chain_for_plan(plan)`:

- `coding_generation`, `research_generation`, `math_generation`,
  `creative_generation`, `cheap_judge`, `standard_judge`,
  `critical_judge`.
- `get_model_chain_for_plan(plan)` so simple requests choose cheaper
  chains and critical requests use stronger / multiple models.
- `get_model_chain(role)` is preserved for compatibility.

The capability matrix (`MODEL_CAPABILITY_WEIGHTS`) is moved **out**
of `api_gateway/strategy.py` and into
`config/capabilities/model_capabilities.json`. `ProviderStrategy`
consults via `api_gateway/capabilities.py`.

## 8. Async DAG Trap Rules (binding on RFC-003)

The execution manager and the scheduler must obey:

- **Dynamic topological release** via `asyncio.Condition` (or one
  `asyncio.Event` per node). No wave loop.
- The scheduler is a **long-lived task** (one coroutine), not a
  function that `await`s the whole graph.
- Workers are separate coroutines that pull from the ready-set via
  `condition.wait_for(lambda: ready_set)`.
- Concurrency cap is a semaphore sourced from `ResourceManager`
  (§4), never hardcoded.
- **Never** call a blocking sync LLM client directly inside the loop.
  Wrap with `asyncio.to_thread(...)`.
- Honor cancellation: when a node fails fatally, cancel in-flight
  workers for its branch and emit `NodeCancelled`.
- Telemetry, streaming SSE writes, and health checks run on their
  own coroutines and never queue behind LLM calls.

For back-compat with tests and the existing `DecisionEngine` path,
keep a `run_dag_blocking(graph)` façade that internally drives the
event loop with `asyncio.run` only when no outer loop is running.

## 9. Route-Specific Graph Templates

The planner produces DAGs, but deterministic templates are the
backstop for `low` / `medium` tasks and the fallback when planner
output is invalid. Templates are owned here, used by `ExecutionManager`:

- **Coding:** `Classifier -> Planner -> code-context gatherer ->
  implementation / planning agent -> code verifier -> optional repair
  -> optional judge -> final`
- **Research:** `Classifier -> Planner -> RAG retrieval -> source
  ranker -> research synthesizer -> evidence checker -> optional
  repair -> final`
- **Math:** `Classifier -> Planner -> solver -> independent checker
  -> contradiction detector -> optional repair -> final`
- **Creative:** `Classifier -> Planner -> ideation agent ->
  taste / constraint critic -> optional repair -> final`
- **General:** `Classifier -> Planner -> direct agent -> optional
  uncertainty / clarification -> optional judge -> final`

## 10. Adaptive Early-Exit Rules

Thresholds live in `orchestrator/routing.py` or
`orchestrator/execution_manager.py`. Proposed defaults:

- Confidence ≥ 0.95.
- Calibration ≥ 0.85 when available.
- Evidence strength ≥ route minimum.
- Agreement ≥ route minimum.
- Stability ≥ route minimum when multiple samples exist.
- Reasoning quality ≥ `strong`.
- Evidence count ≥ required count for route.
- Contradiction score ≤ 0.05.
- Unsupported claim count == 0.

If all pass, skip critique / judge and return. If confidence is
medium, run the minimum judge count. If contradictions are detected,
escalate complexity and add judges or repair.

## 11. Invariants Owned by This RFC

- Async-first runtime; sync SDKs wrapped in `asyncio.to_thread` (ADR-002).
- `ResourceManager` owns concurrency; no other module computes
  parallelism ceilings (ADR-004).
- Capability files live under `config/capabilities/`, never hardcoded
  (ADR-005).

## 12. Exit Criteria

This RFC is considered **Implemented** when ALL of the following are
true:

- [ ] `IntentAnalyzer` is implemented in `orchestrator/routing.py`
      with route detection, complexity scoring, and the
      `needs_decomposition` signal.
- [ ] `ExecutionManager` is implemented in
      `orchestrator/execution_manager.py` and owns the event loop.
- [ ] `ResourceManager` is implemented in
      `orchestrator/resource_manager.py`, backed by extending
      `api_gateway/rate_limiter.py`.
- [ ] `config/capabilities/` directory exists with all five JSON
      files; `api_gateway/capabilities.py` loader is implemented and
      unit-tested (including the missing-file / malformed-JSON
      fallback path).
- [ ] `ProviderStrategy` consults the loader, not the inline
      `MODEL_CAPABILITY_WEIGHTS` dict; the dict is removed.
- [ ] `get_model_chain_for_plan(plan)` is implemented and tested.
- [ ] The `effective_parallel` calculation is implemented and
      tested with both provider and model limits honored.
- [ ] All five route templates are implemented and accept a
      `TaskProfile`.
- [ ] Early-exit thresholds are configurable via
      `routing_defaults.json` and have unit tests.
- [ ] Telemetry emits `execution.*` and `planner.*` namespaces
      (spec in RFC-005 §4).
- [ ] Integration tests prove `CALIENNE_ENABLE_DAG=false` falls
      back to `run_micro_mode` unchanged.
- [ ] `docs/decision_register.md` rows for DEC-001, DEC-011 are
      `Implemented? Yes`; `docs/maturity.md` row for this RFC
      moves to `Experimental`.
- [ ] ADR-002, ADR-004, ADR-005 are `Status: Accepted`.
- [ ] Code owner has signed off.
