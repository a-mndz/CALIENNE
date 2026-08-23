# Adaptive CALIENNE Pipeline Plan

## Current Findings

- Current main path is `run_micro_mode` delegating to `DecisionEngine` in `orchestrator/pipelines.py`.
- `DecisionEngine` already owns the core Breaker -> Logician/Creative -> Judge flow in `orchestrator/decisions.py`.
- Current dynamic behavior is limited to `DecisionStrategy.PARALLEL`, `SEQUENTIAL`, and `CONDITIONAL`.
- Agent output only has `reasoning_steps`, `answer`, and `confidence` in `core/schemas.py`.
- Final judge output only has `final_answer`, `overall_confidence`, `overall_bias_risk`, `disagreement_notes`, and `validation_score` in `core/schemas.py`.
- `MemoryManager` exists, but it is context compression only, not a full memory hierarchy or active context manager.
- `EpistemicMemory` only tracks prior failures in memory.
- `RuntimeEngine` already tracks latency, tokens, and success metrics per agent/provider.
- `ProviderStrategy` already has role-based fallback chains, but not cost-aware task routing or weighted capability selection.
- The non-streaming API creates a passport but does not pass it into `run_micro_mode`, so monitoring data is incomplete.
- The streaming API still uses `stream_micro_mode`, which appears to be the older inline pipeline path rather than the `DecisionEngine` path.

## Target Architecture

The architecture should move from a mostly linear pipeline to a planner-driven task graph with bounded dynamic behavior.

```text
User Prompt
  -> Prompt Classifier
  -> Planner Agent
  -> Validated Task Graph (DAG)
  -> Prediction Layer
  -> Token Budget Manager
  -> Context Manager
  -> Dependency-Aware Scheduler
  -> Agent/Tool Execution Pool
  -> Weighted Consensus Layer
  -> Judge Pass
  -> Uncertainty Engine
  -> Reflection/Repair Loop
  -> Hallucination Firewall
  -> Memory Update
  -> Final Synthesizer
  -> Response
```

Key principle: keep route families deterministic, but let the planner generate a bounded task graph and dynamically compose skills inside a validated schema. Do not let an LLM invent arbitrary production workflows without constraints.

## Recommended Plan

### 1. Fix observability plumbing first

Before adding adaptive behavior, make the existing execution measurable.

- Pass the created `passport` into `run_micro_mode` in `server.py`.
- Ensure streaming and non-streaming paths use equivalent telemetry contracts.
- Prefer routing streaming through the same `DecisionEngine`/future `ExecutionManager` path instead of keeping a separate legacy inline pipeline.
- Return or expose request-level metrics consistently for dashboard and tests.

This makes later improvements data-driven instead of guesswork.

### 2. Add shared decision and graph schemas

Extend `core/schemas.py` with small, reusable contracts while preserving backward compatibility for existing `AgentOutput` and `calienneOutput` parsing.

Add `TaskProfile`:

```python
class TaskProfile(BaseModel):
    task_type: str
    complexity: str
    criticality: str
    requires_rag: bool = False
    requires_code_context: bool = False
    requires_math_check: bool = False
    requires_creativity: bool = False
```

Add richer `StageAssessment`:

```python
class StageAssessment(BaseModel):
    confidence: float
    calibration: float | None = None
    evidence_strength: float | None = None
    novelty: float | None = None
    agreement: float | None = None
    stability: float | None = None
    reasoning_quality: str | None = None
    evidence_count: int = 0
    contradiction_score: float = 0.0
    unsupported_claim_count: int = 0
```

Add budget and plan contracts:

```python
class PipelineBudget(BaseModel):
    total_tokens: int
    planning_tokens: int
    generation_tokens: int
    critique_tokens: int
    judge_tokens: int
    memory_tokens: int
    final_output_tokens: int
    consumed_tokens: int = 0
    pressure_state: str = "normal"

class PipelinePlan(BaseModel):
    route: str
    model_tier: str
    judge_count: int
    early_exit_threshold: float
    requires_consensus: bool = False
    requires_repair_loop: bool = False
```

Add task graph contracts:

```python
class TaskNode(BaseModel):
    task_id: str
    objective: str
    skills_required: list[str]
    model_tier: str
    depends_on: list[str] = []
    can_run_parallel: bool = True
    expected_tokens: int | None = None
    expected_latency_ms: int | None = None
    output_contract: str | None = None

class TaskGraph(BaseModel):
    nodes: list[TaskNode]
    root_task_id: str
    final_task_id: str
```

Add graph validation rules:

- Reject cycles.
- Reject missing dependencies.
- Reject unknown skills.
- Reject unknown model tiers.
- Reject graphs without a final node.
- Cap node count by complexity.
- Require every node to have an objective and output contract.

### 3. Add prompt analyzer and classifier

Create `orchestrator/routing.py`.

Implement deterministic classification first to avoid spending tokens:

- Coding: file paths, stack traces, repo/code keywords.
- Research: source/citation/current-events keywords.
- Math: equation/proof/calculation keywords.
- Creative: branding/story/design/copy keywords.
- General: fallback.

Add complexity scoring:

- Low: direct factual/helpful question.
- Medium: multi-step or needs one verification pass.
- High: multiple constraints, code changes, research, high ambiguity.
- Critical: security, finance, medical/legal, destructive actions, production-impacting code.

Return a `TaskProfile` before any planner or generation stage runs.

### 4. Add planner agent and task graph generation

Create `orchestrator/planner.py`.

The planner decomposes complex requests before execution. This prevents duplicate work, missed dependencies, and agents stepping on each other's responsibilities.

Planner responsibilities:

- Convert `TaskProfile` and user prompt into a bounded `TaskGraph`.
- Identify independent work that can run in parallel.
- Identify sequential dependencies.
- Assign required skills to each task node.
- Assign model tier per task node.
- Assign expected token and latency estimates per node.
- Declare output contracts for downstream nodes.

Example decomposition for "Build me a web app":

```text
Plan app requirements
  -> Design frontend
  -> Design backend
  -> Design database
  -> Design auth
  -> Implement tests
  -> Final integration plan
```

Implementation stance:

- Use deterministic route templates for low/medium tasks.
- Use the planner agent for high/critical or ambiguous multi-part tasks.
- Always validate the generated graph before scheduling.
- Fall back to a safe deterministic graph if planner output is invalid.

### 5. Add prediction layer

Create `orchestrator/prediction.py`.

Before execution, estimate:

- Expected cost.
- Expected latency.
- Expected token usage.
- Expected confidence.
- Expected retrieval need.
- Expected repair likelihood.

Use predictions to choose the lowest-cost graph and model plan that satisfies quality thresholds.

Prediction results should be stored for later accuracy tracking.

### 6. Add token budget manager

Create `orchestrator/budget.py`.

Default budget can start at `15000` tokens, then allocate:

- Planning: 5%.
- Generation: 45%.
- Critique and repair: 20%.
- Judge: 15%.
- Memory/context: 10%.
- Final output: 5%.

Integrate with `MemoryManager.track_tokens()` and `RuntimeContract.max_tokens`.

Add pressure states:

- `normal`: no compression.
- `tight`: compress history.
- `critical`: merge agent prompts, reduce judge count, summarize intermediate outputs.
- `exhausted`: stop expansion and synthesize from verified state.

Use the budget manager as the circuit breaker for reflection/repair. If a repair cycle would exceed the critique/repair budget, skip repair and synthesize from the best available verified state.

### 7. Add context manager

Create `orchestrator/context_manager.py`.

Memory stores information; the context manager actively assembles the per-node context window.

Flow:

```text
Conversation History
  -> Importance Ranking
  -> Compression
  -> Retrieval
  -> Window Assembly
  -> Agent Context
```

Responsibilities:

- Preserve system/developer constraints.
- Rank user requirements by importance.
- Keep recent turns verbatim.
- Compress older low-priority turns.
- Retrieve relevant long-term/user/agent memory.
- Add RAG or code-context snippets only where needed.
- Assemble a bounded context window per task node.

### 8. Add dependency-aware execution manager and scheduler

Create `orchestrator/execution_manager.py` and `orchestrator/scheduler.py`.

`ExecutionManager` responsibilities:

- Build `TaskProfile`.
- Build or request `TaskGraph`.
- Validate graph.
- Build `PipelineBudget`.
- Request predictions.
- Assemble context per node.
- Delegate scheduling.
- Select fallback models through `ProviderStrategy`.
- Cancel unnecessary stages on early exit.
- Delegate actual provider calls to `RuntimeEngine`.

`Scheduler` responsibilities:

- Find nodes with zero unmet dependencies.
- Run independent nodes concurrently.
- Hold dependent nodes until prerequisites complete.
- Cancel downstream nodes if a required dependency fails.
- Reuse node outputs when multiple downstream nodes need the same context.
- Apply retries and timeout policies.
- Emit graph-level telemetry: queued, running, skipped, failed, completed.

Keep `DecisionEngine` as a lower-level compatibility executor initially. The new execution manager should wrap it instead of replacing everything in one step.

### 9. Add performance optimizer

Create `orchestrator/performance.py` or keep this as a module inside `ExecutionManager` initially.

Every graph should be optimized before execution:

- Can these nodes run in parallel?
- Can a stage be skipped due to high assessment scores?
- Can cached retrieval or prior task output be reused?
- Can cheaper models handle low-risk nodes?
- Can multiple judge prompts be merged?
- Is this pipeline overkill?
- Are two agents doing the same work?

This is the deterministic version of a lightweight meta-agent. It should start rule-based and only become model-assisted after metrics prove the need.

### 10. Add cost optimizer and weighted model capability matrix

Extend `api_gateway/strategy.py` with model tiers, cost classes, and a versioned capability matrix.

Add route-aware role names instead of only `generation`, `breaker`, `judge`:

- `coding_generation`.
- `research_generation`.
- `math_generation`.
- `creative_generation`.
- `cheap_judge`.
- `standard_judge`.
- `critical_judge`.

Add `get_model_chain_for_plan(plan)` so simple requests choose cheaper chains and critical requests use stronger/multiple models.

Add a lightweight capability matrix rather than letting an LLM invent weights at runtime:

```python
MODEL_CAPABILITY_WEIGHTS = {
    "openrouter/anthropic/claude-3.5-sonnet": {
        "coding": 0.95,
        "creative": 0.75,
        "research": 0.82,
        "math": 0.78,
    },
    "google/gemini-2.5-pro": {
        "research": 0.96,
        "math": 0.84,
        "general": 0.88,
    },
    "deepseek": {
        "math": 0.98,
        "coding": 0.88,
    },
}
```

Preserve current `get_model_chain(role)` for compatibility.

### 11. Add dynamic skill composition

Create `agents/skills.py` or `orchestrator/skills.py`.

Skills should be composable rather than fixed personas.

Example composed persona:

```text
Coder + Security + Performance + Teacher
```

A skill should define:

- Name.
- Capability tags.
- Prompt fragment.
- Behavioral constraints.
- Preferred output contract.
- Incompatible skills, if any.
- Cost or verbosity impact.

Initial skills:

- `caveman`: remove unnecessary wording.
- `precision`: increase factual accuracy and evidence strictness.
- `academic`: formal structure/citations.
- `coder`: implementation and verification focus.
- `researcher`: retrieval and source synthesis.
- `devils_advocate`: challenge assumptions.
- `explainer`: beginner-friendly output.
- `security`: threat modeling and safe implementation focus.
- `performance`: latency, cost, and resource optimization.

The planner chooses skill bundles per `TaskNode`, and user overrides can force or block skills.

### 12. Add adaptive early-exit rules

Add thresholds in one place, probably `orchestrator/routing.py` or `orchestrator/execution_manager.py`.

Proposed defaults:

- Confidence >= `0.95`.
- Calibration >= `0.85` when available.
- Evidence strength >= route minimum.
- Agreement >= route minimum.
- Stability >= route minimum when multiple samples exist.
- Reasoning quality >= `strong`.
- Evidence count >= required count for route.
- Contradiction score <= `0.05`.
- Unsupported claim count == `0`.

If all pass, skip critique/judge and return.

If confidence is medium, run the minimum judge count.

If contradictions are detected, escalate complexity and add judges or repair.

### 13. Implement dynamic judge allocation

Map `TaskProfile.complexity` to judge count:

- Low: 1 judge only if early-exit fails.
- Medium: 2 judges.
- High: 4 judges.
- Critical: full pipeline with independent model families, critique, consensus, and firewall.

Add a `JudgePlan` structure with `judge_count`, `judge_roles`, `requires_consensus`, and `model_weighting_strategy`.

Avoid always running Logician + Creative for every route. For coding/math, replace Creative with route-specific verifier/solver.

### 14. Add route-specific graph templates

Keep route families deterministic, but represent each as a graph template that the planner can adapt within limits.

Coding route:

```text
Classifier -> Planner -> code-context gatherer -> implementation/planning agent -> code verifier -> optional repair -> optional judge -> final
```

Research route:

```text
Classifier -> Planner -> RAG retrieval -> source ranker -> research synthesizer -> evidence checker -> optional repair -> final
```

Math route:

```text
Classifier -> Planner -> solver -> independent checker -> contradiction detector -> optional repair -> final
```

Creative route:

```text
Classifier -> Planner -> ideation agent -> taste/constraint critic -> optional repair -> final
```

General route:

```text
Classifier -> Planner -> direct agent -> optional uncertainty/clarification -> optional judge -> final
```

### 15. Add uncertainty engine

Create `orchestrator/uncertainty.py`.

Purpose: decide whether the system should continue, retrieve, ask the user, or stop.

Possible outcomes:

- `continue_execution`.
- `run_retrieval`.
- `ask_user_clarification`.
- `request_more_context`.
- `escalate_model`.
- `run_additional_checker`.
- `synthesize_with_uncertainty`.

This prevents the system from hallucinating at all costs. More judges are not always the correct answer. If the prompt is ambiguous, the correct output should be a structured clarification request, not an over-engineered guess.

Clarification response contract:

```python
class ClarificationRequest(BaseModel):
    status: Literal["needs_clarification"]
    question: str
    reason: str
    missing_context: list[str]
    options: list[str] = []
```

### 16. Add reflection and repair loop

Create `orchestrator/repair.py` or keep this inside `ExecutionManager` initially.

Flow:

```text
Generate
  -> Judge/Critique
  -> Reflect
  -> Repair
  -> Rejudge
  -> Done
```

Rules:

- Default `max_repairs = 2`.
- Repair is only triggered for actionable defects: contradiction, unsupported claim, failed code check, math error, missing requirement.
- The repair prompt receives the original task, generated output, judge critique, failed checks, and relevant task graph state.
- The repaired output is judged again.
- Token Budget Manager is the circuit breaker.
- If repair would exceed the critique/repair budget, bypass repair and synthesize the best-available state with caveats.

### 17. Add weighted consensus engine

Create `orchestrator/consensus.py`.

Inputs: outputs from Model A/B/C or multiple judges.

Compute:

- Raw agreement.
- Weighted agreement.
- Model capability weight by task type.
- Agreement matrix.
- Disagreement clusters.
- Confidence spread.
- Stability across retries.
- Contradiction score.
- Majority-backed claims.
- Minority warnings.

Feed consensus result into the judge layer rather than letting one judge decide alone.

### 18. Add smart RAG

Create `orchestrator/retrieval.py`.

Add `SourceCandidate` fields:

- `url`.
- `title`.
- `excerpt`.
- `credibility_score`.
- `freshness_score`.
- `relevance_score`.
- `consensus_score`.
- `final_score`.

Add ranking formula:

```text
final_score = relevance * 0.4 + credibility * 0.25 + freshness * 0.15 + consensus * 0.2
```

Use top sources by score, not fixed `3-5`.

Store selected source metadata in `StageAssessment.evidence_count` and RAG telemetry.

Keep retrieval optional and route-gated.

### 19. Replace placeholder claim validation with hallucination firewall

Current `ClaimManager.validate_claim()` is effectively placeholder behavior and claim extraction is disabled by default.

Add a real `EvidenceChecker` or upgrade `ClaimManager`.

Required flow:

- Extract claims.
- Link each claim to source evidence, code evidence, math derivation, or model-only reasoning.
- Mark unsupported claims.
- Remove or qualify unsupported claims before final synthesis.
- Return `claim`, `evidence`, and `confidence` metadata.

For non-RAG tasks, evidence can be repo files, tests, calculations, or prior conversation context.

### 20. Split memory into a hierarchy

Keep `MemoryManager` as the context/token compression component.

Add a new `orchestrator/memory_hierarchy.py` or extend current memory package carefully.

Layers:

- Short-term memory: current request and recent turns.
- Long-term memory: durable summaries and prior outcomes.
- User memory: stable preferences.
- Agent memory: per-agent success/failure patterns.
- Shared knowledge cache: RAG and source cache.
- Vector memory: semantic retrieval layer, added behind an interface so it can start in-memory.

Wire this gradually into `ContextManager` and `ExecutionManager`, not directly into every agent.

### 21. Add monitoring/dashboard data

Backend first:

- Add a metrics aggregator that merges `RuntimeEngine.get_metrics_report()`, `ResourceManager.get_resource_metrics()`, `DecisionEngine.get_metrics()`, scheduler stats, graph stats, budget stats, RAG stats, uncertainty stats, repair stats, and consensus stats.
- Add or extend an API endpoint for dashboard consumption.

Frontend second:

- Extend existing telemetry UI components rather than adding a separate dashboard from scratch.

Track:

- Input tokens.
- Output tokens.
- Latency.
- Estimated API cost.
- Expected vs actual cost.
- Expected vs actual latency.
- Expected vs actual token usage.
- Judge agreement.
- Weighted consensus score.
- Hallucination/unsupported claim percentage.
- Compression ratio.
- Memory hits.
- RAG hits.
- Context reuse hits.
- Confidence.
- Calibration.
- Repair count.
- Uncertainty outcome.
- Final score.
- Graph nodes queued, running, skipped, failed, completed.

### 22. Add self-learning layer with safeguards

Do not let production routing change immediately based on user feedback.

Use staged promotion:

```text
Feedback
  -> Offline Evaluation
  -> Shadow Testing
  -> A/B Testing
  -> Production Rollout
```

Add `orchestrator/routing_feedback.py`.

Store experience replay records:

- Prompt fingerprint.
- Task profile.
- Planner graph.
- Selected route.
- Model choices.
- Cost.
- Latency.
- Token usage.
- Judge/consensus scores.
- Repair count.
- Uncertainty outcome.
- User satisfaction if available.
- Final outcome.

Use this for reports, offline tuning, and later routing policy training.

Only enable automatic routing changes behind an explicit flag after offline evaluation, shadow testing, and A/B testing show improvement.

## Dynamic Pipeline Generation Policy

Fully dynamic, on-the-fly pipeline generation where an LLM invents the entire workflow architecture from scratch is too unstable for production. It introduces high variance and makes testing/debugging difficult.

Use this compromise:

- Keep deterministic route families: coding, research, math, creative, general.
- Let the planner generate a task graph inside a strict schema.
- Let the planner compose skills dynamically.
- Validate every generated graph before scheduling.
- Reject or repair invalid graphs.
- Fall back to deterministic graph templates.
- Cap graph size by complexity.
- Track planner quality through telemetry.

## Updated Implementation Order

### 1. Fix observability plumbing

- Pass passports correctly.
- Unify streaming and non-streaming telemetry.
- Expose request-level metrics.

### 2. Add schemas and assessments

- Add `TaskProfile`, `StageAssessment`, `PipelineBudget`, `PipelinePlan`, `TaskNode`, and `TaskGraph`.
- Add tests proving old outputs still parse.

### 3. Add classifier and deterministic planner fallback

- Implement task classification.
- Add route templates for general/coding/research/math/creative.
- Add graph validation.

### 4. Add graph planner and dependency-aware scheduler

- Implement planner-generated DAGs for high/critical tasks.
- Execute zero-dependency nodes in parallel.
- Serialize dependency-bound nodes.
- Emit graph telemetry.

### 5. Add token budget manager and prediction layer

- Estimate expected cost, latency, tokens, confidence, retrieval need, and repair likelihood.
- Enforce budget pressure states.

### 6. Add context manager

- Implement importance ranking, compression, retrieval, and per-node window assembly.

### 7. Add dynamic skill composition

- Define skill fragments and compatibility rules.
- Let planner assign skill bundles per node.

### 8. Add adaptive early exit and performance optimizer

- Skip unnecessary stages.
- Reuse cached outputs.
- Detect overkill and redundant nodes.

### 9. Add uncertainty engine

- Support structured clarification requests.
- Decide retrieval/model escalation/user clarification based on uncertainty type.

### 10. Add reflection/repair loop with restraints

- Add `max_repairs = 2`.
- Use token budget as circuit breaker.
- Rejudge repaired outputs.

### 11. Add weighted consensus and multi-judge

- Implement high/critical only first.
- Use versioned model capability weights.
- Keep low/medium cheap.

### 12. Add route-specific graph templates

- Expand deterministic graph templates for coding, research, math, creative, and general.

### 13. Add hallucination firewall and real evidence checks

- Replace disabled placeholder claim validation with route-specific evidence verification.

### 14. Add smart RAG

- Introduce source ranking and source metrics.
- Gate it only for research/current-fact tasks or uncertainty-triggered retrieval.

### 15. Add memory hierarchy

- Add short-term, long-term, user, agent, shared cache, and vector memory layers.

### 16. Add dashboard metrics

- Add graph execution, repair count, uncertainty outcomes, weighted consensus, and prediction accuracy.

### 17. Add self-learning safeguards

- Add experience replay.
- Require offline evaluation, shadow testing, A/B testing, then production rollout.

## Test Plan

- Unit tests for `TaskProfile` classification.
- Unit tests for low/medium/high/critical judge allocation.
- Unit tests for `TaskGraph` validation: cycles, missing dependencies, unknown skills, missing final node.
- Unit tests for dependency-aware scheduling order.
- Unit tests for parallel node eligibility.
- Unit tests for confidence-threshold early exits.
- Unit tests for rich `StageAssessment` parsing and fallback defaults.
- Unit tests for token budget compression and repair circuit-breaker decisions.
- Unit tests for prediction output shape and expected-vs-actual telemetry recording.
- Unit tests for cost-tier model selection.
- Unit tests for weighted model capability lookup.
- Unit tests for dynamic skill composition and incompatible skills.
- Unit tests for uncertainty outcomes, including `needs_clarification`.
- Unit tests for reflection/repair loop stopping at `max_repairs`.
- Unit tests for consensus agreement matrix and weighted agreement.
- Unit tests for hallucination firewall removing or qualifying unsupported claims.
- Regression tests for existing `AgentOutput` and `calienneOutput` parsing.
- Integration test for `/api/query` proving passport metrics are returned.
- Integration test for streaming events proving graph/node stages are emitted.
- Integration test proving deterministic fallback is used when planner output is invalid.

## Clarifying Choices

- Should this be implemented behind a feature flag first, such as `CALIENNE_ADAPTIVE_PIPELINE_ENABLED=true`, or should it replace the current `DecisionEngine` path directly?
- Do you want the first implementation to prioritize cost savings, answer quality, latency, or dashboard visibility?
- Should `Critical -> Full Pipeline` be reserved for safety-sensitive/high-risk tasks only, or should users be able to force it manually?
- Should the planner agent be enabled only for high/critical tasks at first, with deterministic templates for low/medium tasks?

## Phase 2: Adaptive Architecture Extensions

These extensions are designed to integrate with the 22-item plan above without breaking the deterministic route families or the `Dynamic Pipeline Generation Policy`. They add structure (planners, resources, contracts, replay) without re-introducing fully unconstrained LLM-driven pipeline generation.

### P2-1. Split Planner Into Two (Strategic + Execution)

Replace the single `orchestrator/planner.py` with two modules:

- `orchestrator/strategic_planner.py` (LLM-assisted, planning-only): consumes `TaskProfile` and the user prompt, returns a `StrategicPlan` with goals, sub-problems, constraints, success criteria, required skills, and risk notes. Rejects if it returns raw execution steps.
- `orchestrator/execution_planner.py` (rule-based + lightweight, fast): consumes `StrategicPlan`, `PipelineBudget`, `Prediction`, and `ResourceManager` state, and produces a `TaskGraph` with `TaskNode`s, parallelism hints, model tiers, retries, and `InputContract`/`OutputContract`/`FailureContract` bindings.

`StrategicPlanner` is only invoked when a `needs_decomposition` signal fires (hybrid routing — Q4). Low/medium tasks skip the LLM planner and use deterministic templates.

New schema:

```python
class StrategicPlan(BaseModel):
    goal: str
    sub_problems: list[str]
    constraints: list[str]
    success_criteria: list[str]
    required_skills: list[str]
    risk_notes: list[str] = []
```

### P2-2. Resource Manager

New `orchestrator/resource_manager.py` (singleton owned by `ExecutionManager`).

Owned resources:

- `gpu_budget`, `api_budget_per_minute`, `concurrency_slots` (per route, per provider), `rate_limit_quotas`, `memory_ceiling` (token + RAM), `circuit_breaker_state` per provider.

API:

- `acquire(node) -> Reservation | Reject(reason)`
- `release(reservation)`
- `snapshot() -> ResourceState` (fed to metrics, dashboard, predictions).
- `recompute_plan(graph, prediction)` returns whether the graph can run as-is, must be downgraded, or must be rejected.

Scope: global with per-route overrides (Q5). Global owns CPU, RAM, API budget, concurrency, and provider health; per-route owns preferred model tier, token budget, and latency target. **No per-tenant in v1.**

Scheduler (`orchestrator/scheduler.py`) becomes a *client* of the Resource Manager; it does not own global limits. Backed by extending `api_gateway/rate_limiter.py` `ResourceManager`, not duplicating it.

### P2-3. Task Graph Versioning + Architecture Version

Every `TaskGraph` carries a `VersionStamp`:

- `graph_version`, `planner_version`, `strategy_version`, `model_capability_version`, `resource_policy_version`, `contract_version`, `prediction_model_version`, `prompt_versions: dict[str, str]` (per-skill per Q10).

Versions are set by the producer. `graph_version` is a monotonic counter from a small `VersionRegistry` keyed by `(planner_version, strategy_version, contract_version)`. A/B testing compares `graph_version=v12` vs `v13` by filtering the experience DB.

Architecture Version is decoupled from graph versioning (Policy 8):

- `architecture_version: "0.1.0"` (SemVer; `1.0.0` reserved for "stable, backward-compatible").
- Stored on `TaskGraph`, `ExecutionTrace`, `Experience`, and `ExecutionPassport`.

### P2-4. Execution Replay

New `orchestrator/execution_replay.py` writes an append-only `ExecutionTrace`:

- `trace_id`, `passport_id`, `task_profile`, `strategic_plan`, `task_graph` (with versions), `resource_snapshot_at_start`, `prediction_actual` deltas, `events[]` (`node_queued`, `node_started`, `node_completed`, `node_failed`, `dependency_released`, `repair_started`, `judge_completed`, `consensus_completed`, `early_exit`, `budget_pressure_changed`), `final_outcome`, `manifest` (frozen).

Replay modes:

- `replay` (deterministic, real providers, ignore predictions).
- `shadow` (use recorded outputs where available, recompute the rest).
- `simulate` (use recorded outputs everywhere, no provider calls) — for debugging and tests.

Stored under `telemetry/`, indexed by `(graph_version, prompt_fingerprint)`. Retention: **configurable, default 30 days** (Q6). Add a `/api/debug/replay/{trace_id}` endpoint gated by `CALIENNE_ENABLE_REPLAY`.

### P2-5. Better Prediction

Extend `orchestrator/prediction.py` so each `Prediction` includes:

- `expected_cost`, `expected_latency_ms`, `expected_tokens`, `expected_confidence` (existing).
- `probability_of_failure`, `probability_of_repair`, `probability_of_retrieval_needed`, `probability_of_clarification_needed`, `probability_of_consensus_disagreement`, `expected_repair_count` (new).

Probabilities come from a calibrated model: lookup in `config/capabilities/prediction_calibration.json` keyed by `(route, complexity, prompt_fingerprint_bucket)` first; fall back to priors per route; fall back to LLM only when both are missing. Store `prediction` + `actual` for every run; update the calibration table nightly (offline job, gated by feature flag).

`ExecutionPlanner` consumes the full `Prediction`, not just cost.

### P2-6. Event-Driven Scheduler

Refactor `orchestrator/scheduler.py` to an event loop:

- Event types: `NodeReady`, `NodeCompleted`, `NodeFailed`, `DependencyReleased`, `BudgetChanged`, `ResourceAcquired`, `ResourceDenied`, `EarlyExitRequested`, `ClarificationRequested`, `RepairScheduled`, `GraphMutated`.
- One `Scheduler` coroutine owns the ready-set; workers consume events and emit new ones.
- `MetaReasoner` (P2-7) can inject `GraphMutated` events at any transition.
- Backwards compatibility: keep a `run_dag_blocking(graph)` façade for tests and the existing `DecisionEngine` path.

**Async DAG trap guardrail (Guardrail 1):** the scheduler must be a long-lived task (one coroutine), not a function that `await`s the whole graph. Workers are separate coroutines that pull from the ready-set via `asyncio.Condition`. No blocking sync LLM client calls inside the loop; sync SDKs are wrapped in `asyncio.to_thread(...)`. Concurrency cap is a semaphore sourced from `ResourceManager`, never hardcoded.

### P2-7. Meta-Reasoner (continuous graph optimization)

New `orchestrator/meta_reasoner.py`:

- Runs after `ExecutionPlanner` produces a graph, and again at any `NodeCompleted` transition (cheap re-check).
- Checks: redundancy, parallelism opportunities, stage skipping, contract compatibility, resource waste, budget pressure, consensus overkill.
- Mutates the graph via a constrained `GraphMutation` API: `merge_nodes`, `skip_stage`, `downgrade_tier`, `cancel_branch`, `reorder` (Q7).
- **No upgrade authority.** Upgrading model tier is reserved for `PredictionLayer` + `ResourceManager`. Future gate: `CALIENNE_ENABLE_META_ESCALATION` (default off; locked naming per OQ2).
- Bounded: max N mutations per run; mutation budget consumed from the critique/repair budget. Records a `mutation_audit_trail` on the trace.

### P2-8. Knowledge / Reasoning / Validation Separation

Three explicit layers, each a module:

- `orchestrator/knowledge_layer.py`: owns `SourceCandidate`, RAG, code-context gatherer, file lookup. Returns *facts* with provenance.
- `orchestrator/reasoning_layer.py`: consumes knowledge, runs plan + agents, produces candidate outputs. No retrieval calls; no judging.
- `orchestrator/validation_layer.py`: judge, consensus, repair, firewall. Owns `StageAssessment` and `ClarificationRequest`.

Today these are smeared across RAG (item 18) and `DecisionEngine`; this is a refactor, not a rewrite, staged behind `CALIENNE_ENABLE_KNOWLEDGE_LAYER`.

### P2-9. Experience Database

New `orchestrator/experience_db.py` (SQLite-backed initially, swappable):

- Records: `Experience` with `prompt_fingerprint`, `task_profile`, `strategic_plan`, `task_graph` (versioned), `prediction`, `actual_outcome`, `consensus_score`, `user_satisfaction`, `graph_mutation_audit`, `replay_trace_id`, `manifest` (frozen).
- Indices on `(route, complexity)`, `(graph_version)`, `(prompt_fingerprint)`, `success/fail`.

Feeds:

- `MetaReasoner` (similar past failures → don't repeat).
- `PredictionLayer` (calibration priors).
- `RoutingFeedback` (offline policy tuning).

**Strictly offline-only in v1 (Q8).** Promotion pipeline: `Experience DB → Offline Evaluation → Benchmark → Shadow Run → Manual Review → Merge → Release`. No live rerouting. Gated by `CALIENNE_ENABLE_EXPERIENCE_DB`.

### P2-10. Agent Contracts (Input + Output + Failure)

Replace `output_contract: str | None` on `TaskNode` with a structured contract triple:

- `InputContract`: required fields, allowed types, validation rules.
- `OutputContract`: produced fields, types, optional `ContractSchema` (JSON schema or Pydantic ref).
- `FailureContract`: failure modes (`timeout`, `validation_error`, `unsupported_claim`, `contradiction`, `oom`, `rate_limited`, `auth_error`, `provider_down`) and the response shape for each (e.g. `RepairRequest`, `ClarificationRequest`, `downgrade_request`).

New `orchestrator/contracts.py`:

- `validate_inputs(node, incoming_outputs)` — runs before a node starts; produces `ContractViolation` on failure.
- `validate_outputs(node, produced)` — runs after a node completes.
- `to_failure_response(node, failure)` — emits the structured failure event.

All three contract types are Pydantic models. They are **backward-compatible** (Guardrail 2): fields are `Optional` with explicit defaults, and the models inherit from `CalienneBaseModel` (global `extra="ignore"`, see Guardrail 2). Nodes become interchangeable: a different agent that satisfies the same triple can be swapped without graph changes.

## Guardrails (Phase 1.5 — apply during implementation)

These guardrails bind every implementation step in the 22-item plan and the P2 extensions above. They are not new features; they are constraints.

### G1. Async-First Runtime

Every orchestrator component is async. Sync provider SDKs are wrapped in `asyncio.to_thread(...)`. One event loop owns planner, scheduler, execution manager, resource manager, memory, RAG, and consensus.

The event-driven scheduler (P2-6) is the only consumer of the ready-set. Concurrency cap is a semaphore sourced from `ResourceManager`; never hardcoded.

**Async DAG trap:** use dynamic topological release via `asyncio.Condition` (or one `asyncio.Event` per node); never `await` the whole graph in a wave loop; never call sync LLM clients directly inside the loop. Honor cancellation: when a node fails fatally, cancel in-flight workers for its branch and emit `NodeCancelled`. Telemetry and streaming SSE writes run on their own coroutines and never queue behind LLM calls. The async-first choice is permanent; retrofitting later is more expensive than doing it now.

### G2. Pydantic Schema Policy

All schemas in `core/schemas.py` (and any new schema file) inherit from a shared `CalienneBaseModel` with `model_config = ConfigDict(extra="ignore")`. This is a **global** safety net (Path E / option (b) from the planning thread): upstream orchestration components may emit rich adaptive fields that a legacy downstream node hasn't been refactored to parse yet, and the global ignore prevents structural validation failure during incremental migration.

Critical contracts opt into `extra="forbid"` explicitly:

```python
class ProviderConfig(CalienneBaseModel):
    model_config = ConfigDict(extra="forbid")
    ...
```

Rules:

- Every extended field in `StageAssessment` is `Optional` with a documented default (`None` for `calibration`/`evidence_strength`/`novelty`/`agreement`/`stability`/`reasoning_quality`; `0` for `evidence_count`; `0.0` for `contradiction_score`; `0` for `unsupported_claim_count`).
- Defaults for *gating* fields (calibration, evidence_strength) are `None`, not optimistic, so early-exit logic can detect "not measured."
- A `StageAssessment.from_minimal(...)` classmethod accepts the legacy 3-field shape (`confidence` only) and returns a fully-defaulted assessment for regression tests and unmigrated callers.
- Deprecation policy: when a field is promoted from `Optional` to required, bump the schema's `version` and route old payloads through a migrator.

### G3. Capability File Layout

Capability files live under `config/capabilities/` (split layout, Path E). Never hardcoded in orchestration logic.

- `config/capabilities/model_capabilities.json` — what models are good at (per-task-type weights).
- `config/capabilities/provider_limits.json` — infrastructure limits (`max_parallel`, `rpm`, `tpm`, `burst`, `timeout_ms`).
- `config/capabilities/pricing.json` — cost data.
- `config/capabilities/routing_defaults.json` — default orchestration policies (per-route `preferred_model_tier`, `max_judges`, `allow_repair`, `target_latency_ms`, `requires_rag`, `minimum_sources`).
- `config/capabilities/prediction_calibration.json` — `(route, complexity, prompt_fingerprint_bucket) -> probability` priors.

Loader contract: `api_gateway/capabilities.py` reads on import and on a config-reload signal. Override path: `CALIENNE_CAPABILITIES_PATH=/abs/path/to/dir` for tests and per-env overrides. On load failure (missing file, malformed JSON, out-of-range weights, unknown `task_type`): log a warning, fall back to a neutral default of `0.5` for the affected model, and emit a `capability_load_failed` metric. **Never** raise into the request path. Validate at load: every weight in `[0.0, 1.0]`; every `task_type` in an allowlist; reject duplicate model IDs.

Tests must not depend on the real config; pass a temp directory or use a `monkeypatch`-able loader.

### G4. Calibration Promotion (Manual-PR + CI)

Always manual-PR. The pipeline is:

```text
Experience DB
  -> Offline Evaluation
  -> Benchmark
  -> Shadow Run
  -> Manual Review
  -> Merge
  -> Release
```

`CALIENNE_ENABLE_SELF_LEARNING` exists but only gates adaptive routing in v2; it does **not** auto-promote in v1. No `CALIENNE_AUTO_CALIBRATE` flag.

A nightly CLI (`python -m calienne calibrate --since 30d`) compares predicted vs actual per `(model, task_type)` and writes a *proposed* `*.proposed.json`; promotion is a PR. `ProviderStrategy.version` reads the matrix's `version` field; a bump invalidates in-flight graphs whose `strategy_version` doesn't match.

### G5. Concurrency Source (Provider + Model + Runtime)

Configuration provides **limits**; `ResourceManager` computes **effective concurrency** at runtime. Both layers are honored (Path E / option (c)):

- `provider_limits.json` entries expose `max_parallel`, `rpm`, `tpm`, `burst`, `timeout_ms` per provider endpoint.
- `model_capabilities.json` entries embed a per-model `max_concurrency` ceiling alongside the capability weights (Path E's per-model sample shape).

`ResourceManager` computes effective parallelism as:

```python
effective_parallel = min(
    provider.parallel_limit,
    model.max_concurrency,
    system.cpu_limit,
    system.memory_limit,
    budget.parallel_limit,
    rate_limit.remaining
)
```

This gives ResourceManager real global awareness (P2-2) and gives config authors a clean declarative surface.

### G6. Version Everything

Every important decision is versioned and stamped onto the graph/experience. Required versions at minimum:

- `planner_version`, `scheduler_version`, `budget_version`, `routing_version` (includes `MODEL_CAPABILITY_WEIGHTS` version), `capabilities_version`, `prompt_versions` (per-skill per Q10), `consensus_version`, `contracts_version`, `resource_policy_version`, `prediction_model_version`, `graph_version`, `architecture_version`.

Stored on `VersionStamp`, attached to `TaskGraph`, `StrategicPlan`, every `Experience`, every `ExecutionTrace`, and the request `ExecutionPassport`. A bug report must be answerable from the trace alone: "which planner/scheduler/capabilities/prompt version produced this output?" Rollback rule: a version bump invalidates in-flight graphs whose stamp doesn't match; existing graphs continue to completion under their stamped versions.

Implementation: `orchestrator/versioning.py` owns all of the above. Per-skill `prompt_versions` are stored in `config/prompt_versions.json` (not in `skills.py`), loaded with the same env-override pattern as the capabilities files (`CALIENNE_PROMPT_VERSIONS_PATH` → default `config/prompt_versions.json` → `skills.py` built-in defaults with a warning). Resolution order: env override → default config → built-in safe defaults.

### G7. Feature Flags

Per-subsystem flags using the `CALIENNE_ENABLE_<SUBSYSTEM>` namespace, defaulting to **off** for every new subsystem in v1:

- `CALIENNE_ENABLE_PLANNER`
- `CALIENNE_ENABLE_DAG`
- `CALIENNE_ENABLE_CONSENSUS`
- `CALIENNE_ENABLE_RAG`
- `CALIENNE_ENABLE_REPAIR`
- `CALIENNE_ENABLE_PREDICTION`
- `CALIENNE_ENABLE_CONTEXT`
- `CALIENNE_ENABLE_SKILLS`
- `CALIENNE_ENABLE_EXPERIENCE_DB`
- `CALIENNE_ENABLE_META_ESCALATION` (default off; reserved for future; MetaReasoner never escalates in v1)
- `CALIENNE_ENABLE_SELF_LEARNING` (default off; gates adaptive routing in v2; never auto-promotes)

Implementation: single `orchestrator/feature_flags.py` with a typed accessor (`flags.planner`, `flags.dag`, ...) so the code reads `if flags.planner:` not `if os.getenv(...)`. Flags load from env with precedence: env > `config/feature_flags.json` > hardcoded default. The `ExecutionManifest` (G9) snapshots the **full set with explicit booleans**, not just the enabled ones, to preserve "disabled" vs "didn't exist" vs "wasn't loaded" distinctions.

### G8. Architecture Version

`architecture_version: "0.1.0"` initial value. Progression `0.1.0 → 0.2.0 → 0.5.0 → 0.8.0 → 1.0.0`; `1.0.0` is reserved for "stable, backward-compatible."

`git_commit` capture, never raises, no subprocess at request time:

```python
git_commit = (
    os.getenv("CALIENNE_GIT_COMMIT")
    or os.getenv("GIT_COMMIT")
    or _read_ci_metadata()  # reads .git_commit_sha
    or "unknown"
)
```

`architecture_version` lives in `orchestrator/versioning.py` as a constant. CI enforces (see G4-enforcement below) that architectural changes acknowledge versioning. `git_commit` is captured at process start, not per request.

### G9. Execution Manifest

A single immutable `ExecutionManifest` per request, attached to `TaskGraph`, `ExecutionTrace`, `Experience`, and `ExecutionPassport`:

```json
{
  "manifest_schema_version": "1.0",
  "architecture_version": "0.1.0",
  "planner_version": "2",
  "scheduler_version": "1",
  "routing_version": "3",
  "capabilities_version": "4",
  "prompt_versions": { "coder": "7", "security": "5" },
  "feature_flags": {
    "CALIENNE_ENABLE_PLANNER": true,
    "CALIENNE_ENABLE_DAG": true,
    "CALIENNE_ENABLE_CONSENSUS": false,
    "CALIENNE_ENABLE_REPAIR": true,
    "CALIENNE_ENABLE_SELF_LEARNING": false
  },
  "git_commit": "4f8e9ab"
}
```

- Frozen Pydantic model: `model_config = ConfigDict(frozen=True)`. No custom `__setattr__`.
- `manifest_schema_version` is **decoupled from `architecture_version`** — the manifest can evolve (new fields, renamed keys, additional telemetry) without forcing an architecture bump, and parsers can interpret older manifests correctly.
- `feature_flags` is the **full set with explicit booleans** (G7); missing key = "didn't exist" or "wasn't loaded," never ambiguous.
- Built once at request start, frozen thereafter. This is the single artifact that ties G6 + G7 + G8 together for replay, debugging, regression testing, and reproducibility.

### G4-enforcement. CI Architecture-Version Bump Check

Hard CI fail, not soft lint. Manual PR determines *what* the new version should be; CI enforces that the change acknowledges versioning.

Pipeline:

```text
Developer changes Planner/Scheduler/Routing/Execution/Consensus/Schemas/Versioning/etc.
  -> CI detects architectural files changed
  -> architecture_version bumped in orchestrator/versioning.py?
        YES -> continue
        NO  -> fail build
```

Scope: only architectural files. Initial watchlist:

- `orchestrator/{planner,strategic_planner,execution_planner,scheduler,resource_manager,meta_reasoner,routing,consensus,repair,prediction,budget,context_manager,knowledge_layer,reasoning_layer,validation_layer,contracts,execution_manager,execution_replay,experience_db,versioning,execution_manifest,feature_flags,skills}.py`
- `core/schemas.py`
- `api_gateway/{strategy,capabilities}.py`
- `config/capabilities/**`, `config/prompt_versions.json`

Implementation: `tools/check_architecture_version.py` invoked from CI; same script usable locally. The CI does not decide the version — it just enforces acknowledgment. Soft lint is rejected because it is too easy to ignore and the version field will rot.

## Final Resolved Decisions

| Question | Decision |
| --- | --- |
| Q1 Pydantic scope | Global `CalienneBaseModel` with `extra="ignore"`; critical contracts opt into `extra="forbid"`. |
| Q2 Capability file layout | Split: `config/capabilities/{model_capabilities,provider_limits,pricing,routing_defaults}.json` (+ `prediction_calibration.json`). |
| Q3 Concurrency source | Both — provider limits in `provider_limits.json`; per-model `max_concurrency` in `model_capabilities.json`; `ResourceManager` reconciles to `effective_parallel`. |
| Q4 Strategic Planner | Hybrid: deterministic complexity router → `needs_decomposition` → LLM planner; otherwise template graph. |
| Q5 Resource Manager scope | Global with per-route overrides; no per-tenant in v1. |
| Q6 Replay retention | Configurable, default 30 days. |
| Q7 MetaReasoner permissions | Merge / skip / downgrade / reorder only; no upgrade. `CALIENNE_ENABLE_META_ESCALATION` is the future-gate name. |
| Q8 Experience DB utilization | Strictly offline-only in v1. Manual-PR promotion only. |
| Q9 Feature-flag naming | `CALIENNE_ENABLE_<SUBSYSTEM>` namespace. |
| Q10 Prompt template versioning | Per-skill granularity, stored in `config/prompt_versions.json`. |
| OQ1 Resource-policy file name | `config/capabilities/routing_defaults.json` — route policy only. |
| OQ2 Meta-escalation flag name | `CALIENNE_ENABLE_META_ESCALATION`. |
| OQ3 Initial `architecture_version` | `0.1.0`. |
| OQ4 `git_commit` capture | `CALIENNE_GIT_COMMIT` → `GIT_COMMIT` → CI file → `"unknown"`. No subprocess at request time. |
| OQ5 Prompt version storage | `config/prompt_versions.json` with `CALIENNE_PROMPT_VERSIONS_PATH` override; env → default → `skills.py` fallback. |
| OQ-A `git_commit` precedence | CALIENNE-namespaced var wins. |
| OQ-B `prompt_versions.json` override | Yes; same pattern as `capabilities.json`. |
| OQ-C `architecture_version` enforcement | Hard CI fail, scoped to architectural files only. |
| OQ-D `ExecutionManifest` immutability | Frozen Pydantic model (`ConfigDict(frozen=True)`). |
| OQ-E Feature-flag snapshot in manifest | Full set with explicit booleans. |
| OQ-F Manifest location | Embedded as a frozen field on `TaskGraph` / `ExecutionPassport` / `Experience` / `ExecutionTrace`. |
| OQ-G `manifest_schema_version` initial | `1.0`. |
| OQ-H `prompt_versions.json` missing-file behavior | Fall back to `skills.py` defaults with a warning. |
| OQ-I CI architectural-file scope | See G4-enforcement watchlist. |
| OQ-J CI lint location | `tools/check_architecture_version.py` invoked from CI; same script usable locally. |
| OQ-K "Relevant" feature flags | Every flag declared in `orchestrator/feature_flags.py`'s typed accessor. |
| OQ-L `CALIENNE_ENABLE_META_ESCALATION` default | Off; requires deliberate flip. |
| New (this thread) | `manifest_schema_version` decoupled from `architecture_version`. |

## Open Implementation Details (non-blocking)

- **ID-1.** `CalienneBaseModel` location: `core/schemas.py` (where all schemas live) or a new `core/base.py`? My recommendation: `core/base.py`, imported by `core/schemas.py` and any future schema file.
- **ID-2.** `feature_flags.py` typed accessor: class with attributes vs. Pydantic model vs. `dataclass(frozen=True)`. My recommendation: `dataclass(frozen=True)` for minimal overhead and immutability by default.
- **ID-3.** VersionRegistry storage: in-memory dict at process start, or persisted to `telemetry/version_registry.jsonl`? My recommendation: in-memory for v1; persist once we have replay (P2-4) so traces can be cross-referenced after restarts.
- **ID-4.** `config/feature_flags.json` schema: top-level dict keyed by flag name, or per-flag objects with metadata? My recommendation: dict keyed by flag name for v1 simplicity; metadata can be added later without breaking.
- **ID-5.** When the CI bump check fails, should it point to the new version, or just fail with a "bump `architecture_version` in `orchestrator/versioning.py`" message? My recommendation: just fail with the message; do not guess the new version.
- **ID-6.** `ExecutionManifest` snapshot timing: at request start, or after the strategic plan is built (so `planner_version` is known)? My recommendation: at request start, with `planner_version` filled in as a default and overwritten once the strategic plan is built. Frozen from that point.

## Relevant Files

- `C:\Users\amand\Downloads\CALIENNE\plan.md` — this document.
- `C:\Users\amand\Downloads\CALIENNE\orchestrator\pipelines.py` — current `run_micro_mode` entry path; legacy pipeline toggle `calienne_LEGACY_PIPELINE_ENABLED`; `_is_claim_extraction_enabled` default-off; CRIT-001 enforces `DecisionEngine` as sole path.
- `C:\Users\amand\Downloads\CALIENNE\orchestrator\decisions.py` — `DecisionEngine`, `DecisionStrategy` (PARALLEL/SEQUENTIAL/CONDITIONAL), agent wrappers, decision metrics.
- `C:\Users\amand\Downloads\CALIENNE\orchestrator\evaluation.py` — `arbitrate_and_synthesize` judge call.
- `C:\Users\amand\Downloads\CALIENNE\orchestrator\memory.py` — `EpistemicMemory` failure tracking.
- `C:\Users\amand\Downloads\CALIENNE\orchestrator\memory_manager.py` — `MemoryManager` token compression, `SummarizationStrategy` enum.
- `C:\Users\amand\Downloads\CALIENNE\orchestrator\streaming.py` — SSE event types and `StreamingManager`.
- `C:\Users\amand\Downloads\CALIENNE\core\schemas.py` — `AgentOutput` and `calienneOutput` Pydantic contracts to extend; `CalienneBaseModel` lives here (or in `core/base.py` per ID-1).
- `C:\Users\amand\Downloads\CALIENNE\core\runtime.py` — `RuntimeEngine`, `RuntimeContract`, metrics reporting.
- `C:\Users\amand\Downloads\CALIENNE\core\passport.py` — `ExecutionPassport` for request tracking.
- `C:\Users\amand\Downloads\CALIENNE\api_gateway\strategy.py` — `ProviderStrategy`, `StrategyMode` (FREE/HYBRID/PAID), role-keyed fallback chains; target of capability-weight matrix and new roles.
- `C:\Users\amand\Downloads\CALIENNE\api_gateway\client.py` — model client used by orchestrator.
- `C:\Users\amand\Downloads\CALIENNE\api_gateway\rate_limiter.py` — `ResourceManager`, health metrics; extended by `orchestrator/resource_manager.py` (P2-2).
- `C:\Users\amand\Downloads\CALIENNE\agents\prompt_utils.py` — `assemble_*_prompt` helpers and `build_decision_dict`; integration point for skill fragments.
- `C:\Users\amand\Downloads\CALIENNE\server.py` — `/api/query` creates passport but does not pass it to `run_micro_mode`; streaming path uses `stream_micro_mode`.
- `C:\Users\amand\Downloads\CALIENNE\tests\test_pipeline.py`, `test_pipeline_repair.py`, `test_validators.py`, `test_state_machine.py`, `test_security.py`, `test_runtime_repair.py`, `test_providers_repair.py`, `test_phase2_cleanup.py`, `test_passport.py`, `test_database_repair.py`, `test_crit003_checkpoint_db.py`, `test_conversation.py`, `test_auth_repair.py` — existing regression tests; test plan in this document aligns new tests with these conventions.
- **New artifacts to be created during implementation:**
  - `config/capabilities/{model_capabilities,provider_limits,pricing,routing_defaults,prediction_calibration}.json`
  - `config/prompt_versions.json`
  - `config/feature_flags.json`
  - `tools/check_architecture_version.py`
  - `orchestrator/{strategic_planner,execution_planner,resource_manager,meta_reasoner,contracts,knowledge_layer,reasoning_layer,validation_layer,execution_replay,experience_db,prediction,budget,context_manager,execution_manager,scheduler,performance,uncertainty,repair,consensus,retrieval,memory_hierarchy,routing_feedback,versioning,execution_manifest,feature_flags,skills,planner,routing}.py`
  - `api_gateway/capabilities.py`
  - `core/base.py` (if ID-1 picks the separate file)
