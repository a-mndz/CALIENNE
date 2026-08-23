# ADR-006: Validation Layer Always Runs

- **Status:** Accepted
- **Date:** 2026-07-13
- **Deciders:** CALIENNE architecture working group
- **Related RFCs:** RFC-003, RFC-005

## Context

Two reasonable-sounding shortcuts emerged during design:

- A **graph-fingerprint cache**: if the same DAG fingerprint has been
  seen with a high empirical success rate, return the cached output
  instead of re-running.
- A **validation-skip on cache hit**: if the cache hit is at 100%
  calibration confidence, skip the Validation Layer entirely.

Both are dangerous for the same reason: **environment and provider
drift**. The fingerprint hashes the structural DAG (nodes, edges,
contracts). It does not hash:

- Which provider handled the call (a provider can fail over).
- Which specific model version served the call (silent upgrades).
- Which capability-matrix version was used (capabilities change
  when models are upgraded).
- Which prompt template version served the call.

A fingerprint hit with all four differences produces a stale output
that passes the cache check. Skipping the Validation Layer compounds
the error: even if the cached output was wrong, validation would have
caught it.

## Decision

The Validation Layer **always runs** in v1, regardless of fingerprint
hits. Caching is allowed for **deduplication, telemetry, replay, and
analytics**, but cached outputs are treated as a *suggestion*, not a
*result*. The Validation Layer is the only path that may mark an
output as final.

Specifically:

- The fingerprint cache may be used to short-circuit *work*, but not
  to short-circuit *validation*.
- The Calibration Layer may be used to inform the Validation Layer's
  resource allocation (e.g. a high-confidence fingerprint hit can
  request a single cheap judge instead of a full multi-judge
  consensus), but the Validation Layer still runs.
- Any future bypass needs its own dedicated RFC (e.g.
  `RFC-009 Execution Cache`), with shadow testing, replay validation,
  and a safety-metrics rollout policy. No silent shortcuts in v1.

## Consequences

Easier:

- The Validation Layer is a single, well-understood gatekeeper. Every
  cached output is re-validated; the worst case is "we re-ran a
  validator we could have skipped," not "we shipped a stale answer."
- Telemetry is honest: every final output is recorded as having
  passed validation in this run.
- Replay is deterministic: a replay always re-runs validation against
  the recorded inputs.

Harder:

- A small latency cost on cache hits. Mitigation: in v2, a future
  `RFC-009` may formalize a *gated* skip path; the gating condition
  will require shadow-test parity and a safety-metrics threshold.
- Cannot claim "100% cache hit rate" in dashboards; the metric is
  "cache hit rate that still passed validation."

## Alternatives Considered

- **Skip validation on 100% calibration fingerprint hit.** Rejected:
  environment drift makes this unsafe; see Context.
- **Skip validation when the cached output was produced by a stronger
  model than the current run.** Rejected: stronger model is not a
  guarantee; the prompt template, capability matrix, and provider
  may differ.
- **Run validation asynchronously and race the result against the
  user-visible response.** Rejected: a "validated later" output
  cannot be relied upon for safety-sensitive tasks, and the race
  condition is harder to reason about than always running
  validation.

## Supersedes

None.
