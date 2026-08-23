# RFC-003: Planner & Scheduler

- **Status:** Not Started
- **Architecture version:** `0.1.0`
- **Related ADRs:** ADR-002, ADR-003, ADR-004, ADR-006, ADR-007
- **Owning decisions:** DEC-003, DEC-004, DEC-012

## 1. Purpose

This RFC defines the **planning layer** (`StrategicPlanner` +
`ExecutionPlanner` + `MetaReasoner`), the **event-driven scheduler**,
the **reflection / repair loop**, the **weighted consensus engine**,
and the **agent contracts** that make nodes interchangeable. It does
not define the IntentAnalyzer (RFC-002), memory or RAG (RFC-004),
versioning or the manifest (RFC-005), feature flags (RFC-006), the
roadmap (RFC-007), or governance (RFC-008).

## 2. Planner Split: Strategic + Execution

The single `orchestrator/planner.py` of the prior design is split
into two modules.

### 2.1 `orchestrator/strategic_planner.py`

**LLM-assisted, planning-only, slow.** Consumes the `TaskProfile`
(from RFC-002 `IntentAnalyzer`) and the user prompt. Returns a
`StrategicPlan`. Rejects if it returns raw execution steps.

Responsibilities:

- Convert `TaskProfile` + user prompt into a bounded `StrategicPlan`.
- Identify independent work that can run in parallel.
- Identify sequential dependencies.
- Assign required skills to each sub-problem.
- Declare output contracts for downstream sub-problems.

Invoked only when `needs_decomposition` is `True` (high / critical
complexity, or multi-part requests). For low / medium tasks, the
`ExecutionPlanner` uses deterministic templates directly.

### 2.2 `orchestrator/execution_planner.py`

**Rule-based + lightweight, fast.** Consumes the `StrategicPlan`
(or skips it for template-based requests), `PipelineBudget`,
`Prediction`, and `ResourceManager` state. Produces a `TaskGraph`.

Responsibilities:

- Convert `StrategicPlan` (or template) into a `TaskGraph` of
  `TaskNode`s.
- Assign model tier per task node.
- Assign expected token and latency estimates per node.
- Assign retries and timeout policies.
- Bind `InputContract` / `OutputContract` / `FailureContract` per
  node (RFC-003 §3.4).

### 2.3 Validation

Every produced `TaskGraph` is validated. Reject:

- Cycles.
- Missing dependencies.
- Unknown skills.
- Unknown model tiers.
- Graphs without a final node.
- Node count over the complexity cap.
- Nodes without an objective and output contract.

On rejection, fall back to a safe deterministic graph template
(RFC-002 §9).

## 3. Schemas

All schemas inherit from `CalienneBaseModel` (RFC-001 §3). All
extended fields are `Optional` with documented defaults (ADR-001).

### 3.1 `TaskProfile`

```python
class TaskProfile(CalienneBaseModel):
    task_type: str
    complexity: str
    criticality: str
    requires_rag: bool = False
    requires_code_context: bool = False
    requires_math_check: bool = False
    requires_creativity: bool = False
```

### 3.2 `StrategicPlan`

```python
class StrategicPlan(CalienneBaseModel):
    goal: str
    sub_problems: list[str]
    constraints: list[str]
    success_criteria: list[str]
    required_skills: list[str]
    risk_notes: list[str] = []
```

### 3.3 `TaskNode`, `TaskGraph`

```python
class TaskNode(CalienneBaseModel):
    task_id: str
    objective: str
    skills_required: list[str]
    model_tier: str
    depends_on: list[str] = []
    can_run_parallel: bool = True
    expected_tokens: int | None = None
    expected_latency_ms: int | None = None
    priority: str = "normal"            # critical | high | normal | background (RFC-003 §4.3)
    input_contract: InputContract | None = None
    output_contract: OutputContract | None = None
    failure_contract: FailureContract | None = None

class TaskGraph(CalienneBaseModel):
    nodes: list[TaskNode]
    root_task_id: str
    final_task_id: str
    # Version stamps (RFC-005):
    graph_version: str | None = None
    graph_fingerprint: str | None = None    # SHA-256 of canonical DAG
    planner_version: str | None = None
```

### 3.4 `InputContract`, `OutputContract`, `FailureContract`

`orchestrator/contracts.py`:

- `InputContract`: required fields, allowed types, validation rules.
- `OutputContract`: produced fields, types, optional `ContractSchema`
  (JSON schema or Pydantic ref).
- `FailureContract`: failure modes (`timeout`,
  `validation_error`, `unsupported_claim`, `contradiction`, `oom`,
  `rate_limited`, `auth_error`, `provider_down`) and the response
  shape for each (e.g. `RepairRequest`, `ClarificationRequest`,
  `downgrade_request`).

API:

- `validate_inputs(node, incoming_outputs)` — runs before a node
  starts; produces `ContractViolation` on failure.
- `validate_outputs(node, produced)` — runs after a node completes.
- `to_failure_response(node, failure)` — emits the structured
  failure event.

### 3.5 Failure Classification

Per `plan.md`'s "Failure Classification" refinement, failures are
classified for the scheduler to act automatically:

```text
Recoverable / Retry:
  timeout, rate_limited, provider_down,
  oom (when budget allows),
  validation_error (repairable outputs)

Non-Recoverable / Abort:
  auth_error,
  unsupported_claim (after max repairs),
  contradiction (after max repairs),
  contract_violation (structural)
```

A `FailurePolicy` table in `orchestrator/contracts.py` maps
`FailureClass -> Action`:

```text
retry_with_backoff | downgrade_model | switch_provider
| request_repair | abort_branch | request_clarification
```

### 3.6 `Prediction`

Per the "Better Prediction" refinement,

```python
class PredictionInterval(CalienneBaseModel):
    value: float
    variance: float
    std_dev: float
    sample_size: int
    upper_bound: float    # derived: value + std_dev
    lower_bound: float    # derived: value - std_dev

class Prediction(CalienneBaseModel):
    expected_cost: PredictionInterval
    expected_latency_ms: PredictionInterval
    expected_tokens: PredictionInterval
    expected_confidence: PredictionInterval
    probability_of_failure: float
    probability_of_repair: float
    probability_of_retrieval_needed: float
    probability_of_clarification_needed: float
    probability_of_consensus_disagreement: float
    expected_repair_count: int
    calibration_confidence: float       # 0.0-1.0; how trustworthy the priors are
```

`ResourceManager` checks against `upper_bound`, so optimistic tails
don't oversubscribe.

### 3.7 `ClarificationRequest`

```python
from typing import Literal

class ClarificationRequest(CalienneBaseModel):
    status: Literal["needs_clarification"]
    question: str
    reason: str
    missing_context: list[str]
    options: list[str] = []
```

## 4. Event-Driven Scheduler

`orchestrator/scheduler.py` is refactored to an event loop.

### 4.1 Event types

- `NodeReady`, `NodeCompleted`, `NodeFailed`, `DependencyReleased`,
  `BudgetChanged`, `ResourceAcquired`, `ResourceDenied`,
  `EarlyExitRequested`, `ClarificationRequested`, `RepairScheduled`,
  `GraphMutated`, `NodeCancelled`.

### 4.2 Topology

- One `Scheduler` coroutine owns the ready-set.
- Workers are separate coroutines that pull from the ready-set via
  `asyncio.Condition`.
- `MetaReasoner` (RFC-003 §6) may inject `GraphMutated` events at any
  transition.
- For back-compat, `run_dag_blocking(graph)` drives the event loop
  with `asyncio.run` when no outer loop is running.

### 4.3 Priority bands

Per `plan.md`'s discussion:

```text
Critical -> High -> Normal -> Background
```

`ResourceManager` and `Scheduler` consume priority to pre-empt lower
bands when a higher-priority node is queued. **Starvation guard**:
`Background` is auto-promoted to `Normal` after a configurable
window. Default **60 seconds**, configurable via
`routing_defaults.json` (`starvation_promote_after_seconds`).

### 4.4 Cancellation and recovery

- Recoverable failures trigger `retry_with_backoff`,
  `downgrade_model`, `switch_provider`, or `request_repair` per the
  `FailurePolicy` (RFC-003 §3.5).
- Non-recoverable failures trigger `abort_branch` or
  `request_clarification`.
- Cancellation is delegated to `ResourceManager.release(reservation)`.
- **Async DAG trap rules** (from RFC-002 §8) are binding here.

## 5. Token Budget Manager

`orchestrator/budget.py`. Default budget starts at `15000` tokens,
allocated:

- Planning: 5%.
- Generation: 45%.
- Critique and repair: 20%.
- Judge: 15%.
- Memory / context: 10%.
- Final output: 5%.

Integrate with `MemoryManager.track_tokens()` and
`RuntimeContract.max_tokens`.

Pressure states:

- `normal`: no compression.
- `tight`: compress history.
- `critical`: merge agent prompts, reduce judge count, summarize
  intermediate outputs.
- `exhausted`: stop expansion and synthesize from verified state.

The budget manager is the **circuit breaker** for reflection / repair.
If a repair cycle would exceed the critique / repair budget, skip
repair and synthesize from the best available verified state.

## 6. Meta-Reasoner

`orchestrator/meta_reasoner.py`.

- Runs after `ExecutionPlanner` produces a graph, and again at any
  `NodeCompleted` transition (cheap re-check).
- Checks: redundancy, parallelism opportunities, stage skipping,
  contract compatibility, resource waste, budget pressure, consensus
  overkill.
- Mutates the graph via a constrained `GraphMutation` API:
  `merge_nodes`, `skip_stage`, `downgrade_tier`, `cancel_branch`,
  `reorder`.
- **No upgrade authority** in v1. Upgrading model tier is reserved
  for `PredictionLayer` + `ResourceManager`. Future gate:
  `CALIENNE_ENABLE_META_ESCALATION` (default off; per DEC-003).
- Bounded: max N mutations per run; mutation budget consumed from
  the critique / repair budget. Records a `mutation_audit_trail` on
  the trace.

## 7. Adaptive Early Exit

RFC-002 §10 specifies the thresholds. When all thresholds pass, skip
critique / judge and return. When contradictions are detected,
escalate complexity and add judges or repair.

This RFC owns the *implementation*; the *threshold values* live in
`routing_defaults.json`.

## 8. Dynamic Judge Allocation

Map `TaskProfile.complexity` to judge count:

- **Low**: 1 judge only if early-exit fails.
- **Medium**: 2 judges.
- **High**: 4 judges.
- **Critical**: full pipeline with independent model families,
  critique, consensus, and firewall.

A `JudgePlan` structure carries `judge_count`, `judge_roles`,
`requires_consensus`, and `model_weighting_strategy`.

For coding / math, replace `Creative` with route-specific
verifier / solver (no `Logician + Creative` for every route).

## 9. Reflection / Repair Loop

`orchestrator/repair.py` (or inside `ExecutionManager` initially).

```text
Generate -> Judge / Critique -> Reflect -> Repair -> Rejudge -> Done
```

Rules:

- Default `max_repairs = 2`.
- Repair is only triggered for actionable defects: contradiction,
  unsupported claim, failed code check, math error, missing
  requirement.
- The repair prompt receives the original task, generated output,
  judge critique, failed checks, and relevant task graph state.
- The repaired output is judged again.
- Token Budget Manager is the circuit breaker (RFC-003 §5).
- If repair would exceed the critique / repair budget, bypass repair
  and synthesize the best-available state with caveats.

## 10. Weighted Consensus Engine

`orchestrator/consensus.py`.

Inputs: outputs from Model A/B/C or multiple judges.

Compute:

- Raw agreement.
- Weighted agreement.
- Model capability weight by task type (from
  `config/capabilities/model_capabilities.json`).
- Agreement matrix.
- Disagreement clusters.
- Confidence spread.
- Stability across retries.
- Contradiction score.
- Majority-backed claims.
- **Minority views** with reasons (per `plan.md`'s discussion):
  `MinorityView = { claim, model_id, confidence, reason }`.
  Add a derived `minority_should_influence_final: bool` (`True`
  when `weighted_agreement < 0.6` and at least one minority view has
  high model capability weight).

Feed consensus result into the judge layer rather than letting one
judge decide alone.

## 11. Uncertainty Engine

`orchestrator/uncertainty.py`.

Decides whether the system should continue, retrieve, ask the user,
or stop. Possible outcomes:

- `continue_execution`.
- `run_retrieval`.
- `ask_user_clarification` (emits `ClarificationRequest`).
- `request_more_context`.
- `escalate_model`.
- `run_additional_checker`.
- `synthesize_with_uncertainty`.

This prevents the system from hallucinating at all costs. More
judges are not always the correct answer. If the prompt is
ambiguous, the correct output is a structured clarification request,
not an over-engineered guess.

## 12. Hallucination Firewall

The current `ClaimManager.validate_claim()` is effectively a
placeholder and claim extraction is disabled by default
(`calienne_DISABLE_CLAIM_EXTRACTION=1`). Add a real
`EvidenceChecker` or upgrade `ClaimManager`:

Required flow (lives in the Validation Layer per RFC-001 §2):

- Extract claims.
- Link each claim to source evidence, code evidence, math derivation,
  or model-only reasoning.
- Mark unsupported claims.
- Remove or qualify unsupported claims before final synthesis.
- Return `claim`, `evidence`, and `confidence` metadata.

For non-RAG tasks, evidence can be repo files, tests, calculations,
or prior conversation context.

## 13. Dynamic Skill Composition

`orchestrator/skills.py` (or `agents/skills.py`).

Skills are composable rather than fixed personas.

A skill defines:

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
- `academic`: formal structure / citations.
- `coder`: implementation and verification focus.
- `researcher`: retrieval and source synthesis.
- `devils_advocate`: challenge assumptions.
- `explainer`: beginner-friendly output.
- `security`: threat modeling and safe implementation focus.
- `performance`: latency, cost, and resource optimization.

The planner chooses skill bundles per `TaskNode`. User overrides can
force or block skills. Per-skill `prompt_versions` are declared in
`orchestrator/skills.py` (loaded from `config/prompt_versions.json`
per RFC-005 §5).

## 14. Invariants Owned by This RFC

- Planner + DAG, not linear (ADR-003).
- Every adaptive decision has a deterministic fallback (DEC-012).
- Validation Layer always runs in v1 (ADR-006).
- Deterministic templates with bounded planning (ADR-007).

## 15. Exit Criteria

This RFC is considered **Implemented** when ALL of the following are
true:

- [ ] `StrategicPlanner` and `ExecutionPlanner` are implemented in
      their respective modules; the single `orchestrator/planner.py`
      is replaced.
- [ ] `StrategicPlan`, `TaskProfile`, `TaskNode`, `TaskGraph`,
      `InputContract`, `OutputContract`, `FailureContract`,
      `Prediction`, `PredictionInterval`, `ClarificationRequest`
      schemas exist and inherit from `CalienneBaseModel`.
- [ ] Graph validation (cycles, missing deps, unknown skills, missing
      final node, cap by complexity) is implemented and unit-tested.
- [ ] Event-driven scheduler is implemented with `asyncio.Condition`,
      priority bands, and the 60s starvation guard; the
      `run_dag_blocking` façade is preserved.
- [ ] Failure classification + `FailurePolicy` table is implemented.
- [ ] `MetaReasoner` is implemented with `merge` / `skip` /
      `downgrade` / `reorder` only; no upgrade path.
- [ ] Reflection / repair loop is implemented with `max_repairs = 2`
      and the budget circuit breaker.
- [ ] Weighted consensus engine emits `MinorityView` with reasons and
      a derived `minority_should_influence_final` flag.
- [ ] Uncertainty engine emits `ClarificationRequest` for ambiguous
      prompts.
- [ ] Hallucination firewall replaces the placeholder
      `ClaimManager.validate_claim()`.
- [ ] Skill registry is implemented with all 9 initial skills and
      per-skill `prompt_versions` from `config/prompt_versions.json`.
- [ ] Telemetry emits `planner.*` and `scheduler.*` namespaces
      (spec in RFC-005 §4).
- [ ] Integration tests prove deterministic fallback is used when
      planner output is invalid.
- [ ] `docs/decision_register.md` rows for DEC-003, DEC-004, DEC-012
      are updated; `docs/maturity.md` row for this RFC moves to
      `Experimental`.
- [ ] ADR-002, ADR-003, ADR-004, ADR-006, ADR-007 are
      `Status: Accepted`.
- [ ] Code owner has signed off.
