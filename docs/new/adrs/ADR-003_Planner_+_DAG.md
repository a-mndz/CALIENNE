# ADR-003: Planner + DAG Architecture

- **Status:** Accepted
- **Date:** 2026-07-13
- **Deciders:** CALIENNE architecture working group
- **Related RFCs:** RFC-003

## Context

CALIENNE's v1 orchestration is a linear pipeline
(`Breaker → Logician/Creative → Judge`) that does not decompose
multi-part requests, does not run independent work in parallel, and
cannot represent dependencies between sub-tasks. As requests grow
(complex coding tasks, multi-source research, math with derivations,
multi-stage creative work), this becomes the dominant source of latency,
duplicated work, and missed constraints.

Three plausible next architectures were considered:

- **State machine.** A finite set of named states with explicit
  transitions. Easy to test, hard to compose, scales poorly when the
  number of states grows with the request.
- **Single LLM planner.** A planner agent that emits the entire task
  graph in one shot. Powerful, but a single source of inaccuracy, a
  single source of latency, and effectively undebuggable.
- **Two-step planner (Strategic + Execution) producing a validated DAG.**
  Decomposition is separated from execution planning; the graph is
  validated against a schema before scheduling; deterministic templates
  are the fallback when the planner is skipped.

## Decision

CALIENNE uses a **two-step planner producing a validated DAG**:

- **`IntentAnalyzer` (deterministic, token-free).** Detects whether the
  request needs decomposition at all, and what kind of work it is.
  Lives in RFC-002.
- **`StrategicPlanner` (LLM-assisted, planning-only).** Consumes the
  `TaskProfile` and the user prompt; returns a `StrategicPlan` with
  goals, sub-problems, constraints, success criteria, and required
  skills. Rejects if it returns raw execution steps.
- **`ExecutionPlanner` (rule-based + lightweight, fast).** Consumes the
  `StrategicPlan`, `PipelineBudget`, `Prediction`, and `ResourceManager`
  state; produces a `TaskGraph` of `TaskNode`s with parallelism hints,
  model tiers, retries, and `InputContract`/`OutputContract`/
  `FailureContract` bindings.
- **Graph validator.** Rejects cycles, missing dependencies, unknown
  skills, unknown model tiers, missing final node, graphs over the
  complexity cap, and nodes without an objective and output contract.
  On rejection, falls back to a deterministic graph template.

The DAG is the **only** internal representation of "what work needs to
happen." The scheduler consumes the DAG and runs it as an event-driven
async graph (RFC-003). Determinism is preserved at the boundaries: the
planner is gated by `CALIENNE_ENABLE_PLANNER`; without it, route
templates and the deterministic fallback handle every request.

## Consequences

Easier:

- Independent work runs in parallel automatically; sequential
  dependencies are explicit.
- Each `TaskNode` has typed contracts, making nodes interchangeable
  (RFC-003).
- Pluggable planners: a future learned planner can replace the LLM
  planner without touching the scheduler.
- Replay is straightforward — the DAG is the source of truth.

Harder:

- Two planners means two failure modes. Mitigation: the validator +
  deterministic fallback.
- LLM planner output must be validated against a schema; this is
  non-trivial to get right. Mitigation: a single
  `TaskGraph.model_validate` boundary.
- Planner quality is now a system-level metric, not an agent-level
  metric. Mitigation: telemetry emits `planner.*` namespace and the
  experience DB (offline) tracks planner quality over time.

## Alternatives Considered

- **State machine.** Rejected: composability is poor, and the
  transition graph itself becomes the bottleneck.
- **Single LLM planner.** Rejected: un-debuggable; a single bad
  planner output corrupts the entire request.
- **Linear pipeline with more stages.** Rejected: does not address
  parallelism, decomposition, or contract-based node composition.
- **Workflow engine (Airflow / Temporal).** Rejected: external
  dependency, heavyweight deployment, doesn't match the in-process
  orchestration model CALIENNE already has.
