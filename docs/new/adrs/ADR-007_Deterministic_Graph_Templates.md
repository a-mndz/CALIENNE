# ADR-007: Deterministic Graph Templates with Bounded Planning

- **Status:** Accepted
- **Date:** 2026-07-13
- **Deciders:** CALIENNE architecture working group
- **Related RFCs:** RFC-003

## Context

Fully dynamic, on-the-fly pipeline generation — where an LLM invents
the entire workflow architecture from scratch — is too unstable for
production. It introduces high variance, makes testing and debugging
difficult, and creates a system where the same prompt can produce
wildly different request shapes.

Two plausible alternative models were considered:

- **Pure deterministic routing.** Every request goes through a fixed
  template based on its `TaskProfile`. Predictable, fast, but
  inflexible: a complex multi-part request that doesn't fit a
  template is forced into the closest one and produces a worse
  answer.
- **Pure LLM-driven planning.** The LLM plans the entire DAG in one
  shot. Flexible, but un-debuggable and high-variance.

## Decision

CALIENNE uses a **hybrid** model with strict boundaries:

- **Deterministic route families** are the foundation. Five routes:
  `coding`, `research`, `math`, `creative`, `general`. Each route has
  a deterministic graph template.
- **The `IntentAnalyzer` (RFC-002) classifies** every request into
  one of these routes deterministically (token-free regex / string
  matching). No LLM call is made for routing.
- **The `StrategicPlanner` is invoked only when `needs_decomposition`
  fires** — i.e. for high or critical complexity, or when a request
  explicitly doesn't match a known route. The LLM planner emits a
  `StrategicPlan`, not a `TaskGraph`.
- **The `ExecutionPlanner` is the only path that produces a
  `TaskGraph`.** It is rule-based + lightweight; it may consult the
  `StrategicPlan` and the `PredictionLayer`, but it does not call an
  LLM. The graph it produces is validated against a schema.
- **A `graph_version` (monotonic) and a `graph_fingerprint`
  (SHA-256 of the canonical DAG)** are stamped on every graph for
  A/B filtering and cache lookup.
- **The validator rejects** cycles, missing dependencies, unknown
  skills, unknown model tiers, missing final node, graphs over the
  complexity cap, and nodes without an objective and output
  contract. On rejection, the deterministic template is the
  fallback.

The "bounded planning" rule: the LLM planner's output is validated
and capped. It cannot invent a new route, a new skill outside the
registry, or a node type that the validator doesn't know about. The
planner is a *composer*, not an *architect*.

## Consequences

Easier:

- A small, well-understood set of graph shapes.
- A bounded, testable LLM surface; the planner's output is validated
  against a schema, not parsed from free text.
- A deterministic fallback when the planner is unavailable, slow, or
  invalid.
- Telemetry emits `planner.*` namespace; planner quality is
  measurable.

Harder:

- Adding a new route requires adding a template, a classifier rule,
  and a registry entry. Acceptable.
- The LLM planner's quality is now a system-level metric, not an
  agent-level metric. Mitigation: shadow mode, calibration priors,
  and the experience DB track planner quality over time.
- The "bounded planning" rule limits expressiveness. Acceptable
  trade-off for production stability.

## Alternatives Considered

- **Pure deterministic routing.** Rejected: inflexible for complex
  requests.
- **Pure LLM-driven planning.** Rejected: un-debuggable, high
  variance.
- **State machine.** Rejected: poor composability.
