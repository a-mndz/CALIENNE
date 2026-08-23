# RFC-001: System Architecture

- **Status:** Experimental
- **Architecture version:** `0.1.7`
- **Related ADRs:** ADR-001, ADR-007
- **Owning decisions:** DEC-010, DEC-012, DEC-022

## 1. Purpose

This RFC defines the **layer separation** for the CALIENNE adaptive
runtime, the **base schema class** all Pydantic models inherit from,
and the **critical contracts** that opt out of the global
`extra="ignore"` policy. It does not define execution mechanics
(RFC-002), planning (RFC-003), memory (RFC-004), versioning (RFC-005),
feature flags (RFC-006), the roadmap (RFC-007), or governance
(RFC-008).

## 2. Layer Separation

The runtime is organized into three explicit layers, owned by separate
modules. Each layer is a pure consumer of the layer above it and a pure
producer for the layer below.

```text
Knowledge Layer   (orchestrator/knowledge_layer.py)
  -> facts with provenance: SourceCandidate, RAG, code-context gatherer,
     file lookup.
  -> No reasoning; no judging.

Reasoning Layer   (orchestrator/reasoning_layer.py)
  -> consumes knowledge, runs plan + agents, produces candidate outputs.
  -> No retrieval calls; no judging.

Validation Layer  (orchestrator/validation_layer.py)
  -> judge, consensus, repair, firewall.
  -> Owns StageAssessment and ClarificationRequest.
```

This replaces the current smeared RAG + `DecisionEngine` flow and is
staged behind `CALIENNE_ENABLE_KNOWLEDGE_LAYER`. The refactor is a
constraint, not a rewrite: the existing `DecisionEngine` (in
`orchestrator/decisions.py`) continues to function and is wrapped by
the new layers until each is feature-complete.

## 3. Base Schema (`core/base.py`)

```python
# core/base.py
from pydantic import BaseModel, ConfigDict

class CalienneBaseModel(BaseModel):
    """All CALIENNE schemas inherit from this. Critical contracts opt
    into extra='forbid' explicitly via model_config = ConfigDict(extra='forbid').
    """
    model_config = ConfigDict(extra="ignore")
```

All schemas in `core/schemas.py`, `core/passport.py`, and any new
schema file must inherit from `CalienneBaseModel`. Adding a Pydantic
model that does **not** inherit from `CalienneBaseModel` is a
breaking change and is caught by `tools/check_architecture_version.py`
in CI.

## 4. Critical Contracts (opt into `extra="forbid"`)

The following contracts are external boundaries or safety-critical and
must reject unknown fields:

- `ProviderConfig` (in `api_gateway/strategy.py` or `api_gateway/capabilities.py`)
- `ExecutionManifest` (in `orchestrator/execution_manifest.py`) — per RFC-005
- Any contract class in `orchestrator/contracts.py` marked `critical=True`
- Public API ingress payloads in `server.py` (added during Step 1
  passport plumbing)

The list of critical contracts lives in this section and is the
single source of truth. Adding a contract to this list is a
non-breaking change; removing one is breaking and requires a
`decision_register.md` entry.

## 5. Schemas to Extend (in `core/schemas.py`)

The following schemas are extended as part of the v1 build. Every
extended field is `Optional` with a documented default (per ADR-001).
Gating fields default to `None`, not optimistic values.

### 5.1 `StageAssessment`

```python
class StageAssessment(CalienneBaseModel):
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

    @classmethod
    def from_minimal(cls, confidence: float) -> "StageAssessment":
        """Accept the legacy 3-field shape and return a fully-defaulted
        assessment. Used by regression tests and unmigrated callers."""
        return cls(confidence=confidence)
```

### 5.2 Other extended schemas

See RFC-003 §3 for `TaskProfile`, `PipelinePlan`, `TaskNode`,
`TaskGraph`, `StrategicPlan`, `ClarificationRequest`. See RFC-005 §3
for `VersionStamp`, `ExecutionManifest`. See RFC-004 §3 for
`SourceCandidate`. See RFC-003 §3 for `InputContract`,
`OutputContract`, `FailureContract`.

## 6. Invariants Owned by This RFC

- All schemas inherit from `CalienneBaseModel` (ADR-001).
- Every adaptive decision has a deterministic fallback (DEC-012).
- All adaptive behavior must be observable (telemetry; per `plan.md`
  §7 invariant viii).
- All persistence goes through repository interfaces (per `plan.md`
  §7 invariant viii); this RFC owns the schema side, RFC-004 owns the
  persistence side.

## 7. Exit Criteria

This RFC is considered **Implemented** when ALL of the following are
true:

- [x] `core/base.py` exists with `CalienneBaseModel`.
- [x] Every schema in `core/schemas.py` inherits from `CalienneBaseModel`.
- [x] `StageAssessment.from_minimal(...)` exists and is unit-tested.
- [x] Every extended field in `StageAssessment` is `Optional` with the
      documented default.
- [x] The list of critical contracts in §4 is exhaustive and each
      listed contract opts into `extra="forbid"`.
- [x] Knowledge / Reasoning / Validation layer modules exist with their
      documented responsibilities; `CALIENNE_ENABLE_KNOWLEDGE_LAYER`
      flag exists (RFC-006) and defaults to off.
- [x] Unit tests pass: every existing regression test that parsed a
      legacy `AgentOutput` / `calienneOutput` payload still parses
      unchanged.
- [x] `tools/check_architecture_version.py` flags any new schema that
      does not inherit from `CalienneBaseModel`.
- [x] Documentation updated: `docs/decision_register.md` rows for
      DEC-010, DEC-012 are `Implemented? Yes`; `docs/maturity.md`
      row for this RFC moves to `Experimental`.
- [x] ADR-001 and ADR-007 are `Status: Accepted` (not `Proposed`).
- [ ] Code owner has signed off.
