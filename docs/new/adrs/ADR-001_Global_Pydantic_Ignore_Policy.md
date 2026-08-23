# ADR-001: Global Pydantic `extra="ignore"` Policy

- **Status:** Accepted
- **Date:** 2026-07-13
- **Deciders:** CALIENNE architecture working group
- **Related RFCs:** RFC-001

## Context

CALIENNE is migrating from a linear pipeline to a planner-driven, DAG-based
runtime. During the migration, upstream orchestration components may emit
rich adaptive fields (e.g. `calibration`, `evidence_strength`,
`contradiction_score`) on `StageAssessment`, `AgentOutput`, and
`calienneOutput` that legacy downstream nodes have not been refactored to
parse. A structural `ValidationError` at the boundary of an un-migrated
node would block the entire request and break every existing regression
test that uses the legacy payload shape.

At the same time, some contracts are *external* — provider configurations,
gateway passport validation, public API ingress payloads — and must
**fail** on unknown fields to catch upstream drift.

The two needs are in tension. A single global policy cannot serve both.

## Decision

All schemas in `core/schemas.py` (and any new schema file) inherit from a
shared `CalienneBaseModel`:

```python
from pydantic import BaseModel, ConfigDict

class CalienneBaseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
```

Critical contracts opt into `extra="forbid"` explicitly:

```python
class ProviderConfig(CalienneBaseModel):
    model_config = ConfigDict(extra="forbid")
    ...
```

Rules:

- Every extended field in `StageAssessment` is `Optional` with a documented
  default (`None` for `calibration`/`evidence_strength`/`novelty`/
  `agreement`/`stability`/`reasoning_quality`; `0` for `evidence_count`;
  `0.0` for `contradiction_score`; `0` for `unsupported_claim_count`).
- Defaults for *gating* fields (calibration, evidence_strength) are `None`,
  not optimistic, so early-exit logic can detect "not measured."
- A `StageAssessment.from_minimal(...)` classmethod accepts the legacy
  3-field shape (`confidence` only) and returns a fully-defaulted
  assessment for regression tests and unmigrated callers.
- Deprecation policy: when a field is promoted from `Optional` to required,
  bump the schema's `version` and route old payloads through a migrator.

## Consequences

Easier:

- Backward compatibility for every existing test fixture and serialized
  output.
- Incremental migration: a downstream node that hasn't been refactored to
  read a new field simply ignores it.
- A single mental model: every model ignores extras unless it explicitly
  forbids them.

Harder:

- A typo in a new field on a `extra="ignore"` model is silent. Mitigation:
  unit tests that explicitly assert the new field is present on the
  producing side.
- "Critical contracts" need to be enumerated and reviewed. Mitigation:
  the list lives in RFC-001 §Critical Contracts.

## Alternatives Considered

- **Per-class opt-in (no global).** Rejected: every new schema would need
  to remember to add the base class, and any schema that forgot would
  silently break the migration. Higher review burden than the global
  default.
- **Global `extra="forbid"`.** Rejected: immediately breaks every existing
  regression test that parses legacy payloads, and any unmigrated
  consumer of `StageAssessment`/`AgentOutput`/`calienneOutput` would
  start failing in production.
- **Custom `__setattr__` validation layer outside Pydantic.** Rejected:
  duplicates the validation framework, harder to test, easier to bypass.
  Pydantic v2's `ConfigDict` is the idiomatic layer.
