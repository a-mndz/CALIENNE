# ADR-004: Resource Ceiling Management

- **Status:** Accepted
- **Date:** 2026-07-13
- **Deciders:** CALIENNE architecture working group
- **Related RFCs:** RFC-002

## Context

Concurrency, rate limits, and resource budgets are scattered across
`api_gateway/rate_limiter.py`, `core/runtime.py`, and ad-hoc counters
inside individual agents. The scheduler has no global awareness of
provider rate limits, model tier ceilings, or system memory pressure.
Two agents can oversubscribe the same provider simultaneously; a
long-running consensus run can exhaust the per-minute token budget
without any module noticing until a 429 arrives.

Three plausible ownership models were considered:

- **Each agent owns its own rate-limit state.** Rejected: per-agent
  state cannot enforce a global ceiling, and per-agent limits are
  incoherent when the same provider is called by multiple agents.
- **The scheduler owns concurrency.** Rejected: the scheduler is
  concerned with graph topology, not resource budgets. Mixing the two
  makes both harder to test and reason about.
- **A dedicated `ResourceManager` owns concurrency, ceilings, and
  rate limits; the scheduler is a client.** Accepted.

## Decision

A new `orchestrator/resource_manager.py` (singleton owned by
`ExecutionManager`) is the **sole owner** of:

- `gpu_budget`, `api_budget_per_minute`, `concurrency_slots` (per
  route, per provider), `rate_limit_quotas`, `memory_ceiling` (token
  + RAM), and per-provider circuit-breaker state.
- API: `acquire(node) -> Reservation | Reject(reason)`,
  `release(reservation)`, `snapshot() -> ResourceState`,
  `recompute_plan(graph, prediction)`.

Configuration provides **limits**; `ResourceManager` computes
**effective concurrency** at runtime:

```python
effective_parallel = min(
    provider.parallel_limit,    # from provider_limits.json
    model.max_concurrency,      # from model_capabilities.json
    system.cpu_limit,
    system.memory_limit,
    budget.parallel_limit,
    rate_limit.remaining
)
```

Scope: global with per-route overrides; no per-tenant in v1.

The scheduler (RFC-003) becomes a *client* of the `ResourceManager`;
it does not own global limits. The existing
`api_gateway/rate_limiter.py` `ResourceManager` is extended, not
duplicated.

## Consequences

Easier:

- Real global awareness; no module can oversubscribe a provider
  without the `ResourceManager` knowing.
- A single source of truth for "how many parallel calls can we make
  to model X right now?"
- Cleanly testable with a fake clock and counters.
- Per-route overrides (e.g. `coding` gets a higher ceiling than
  `research` in the same process) become a one-line config change.

Harder:

- Another singleton; tests must use a fake `ResourceManager`.
- `acquire`/`release` discipline must be enforced in the scheduler
  via a `try/finally` pattern; missing `release` leaks a slot.
- Effective-concurrency calculation has a small but real cost per
  acquire. Mitigation: cache the result for a short window per
  `(model, provider)` key.

## Alternatives Considered

- **Distributed rate limiter (Redis-backed).** Deferred to v2; v1 is
  in-process, single-instance.
- **Per-agent budgets only.** Rejected: cannot enforce a global
  ceiling.
- **Scheduler owns concurrency.** Rejected: couples topology to
  budget policy, and makes the scheduler harder to test in isolation.
