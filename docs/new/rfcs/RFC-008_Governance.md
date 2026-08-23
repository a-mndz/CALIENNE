# RFC-008: Governance

- **Status:** Not Started
- **Architecture version:** `0.1.0`
- **Related ADRs:** ADR-001..ADR-008
- **Owning decisions:** DEC-014, DEC-015

## 1. Purpose

This RFC owns the **governance layer**: how architectural changes are
acknowledged, how calibration is promoted, how the Decision Register
and Maturity Matrix are maintained, how feature flags are added /
retired / deprecated, and how the RFC and ADR documents themselves
evolve. It does not define the architecture (RFC-001), the execution
pipeline (RFC-002), the planner (RFC-003), memory (RFC-004),
versioning (RFC-005), the roadmap (RFC-007), or feature flag
*specification* (RFC-006).

Governance is intentionally isolated from technical implementation
files so operational compliance parameters can be updated by senior
tech leads without rewriting technical specs.

## 2. Architecture Version Bump Policy

### 2.1 Ownership

Manual (PR) determines *what* the new version should be. CI enforces
that architectural changes acknowledge versioning.

```text
Developer changes Planner / Scheduler / Routing / Execution /
  Consensus / Schemas / Versioning / etc.
  -> CI detects architectural files changed
  -> architecture_version bumped in orchestrator/versioning.py?
        YES -> continue
        NO  -> fail build (hard fail, not a lint)
```

### 2.2 Architectural Watchlist

Files whose change requires an `architecture_version` bump:

```text
orchestrator/{planner,strategic_planner,execution_planner,scheduler,
  resource_manager,meta_reasoner,routing,consensus,repair,prediction,
  budget,context_manager,knowledge_layer,reasoning_layer,
  validation_layer,contracts,execution_manager,execution_replay,
  experience_db,versioning,execution_manifest,feature_flags,skills}.py
core/schemas.py
api_gateway/{strategy,capabilities}.py
config/capabilities/**
config/prompt_versions.json
```

Implementation: `tools/check_architecture_version.py` invoked from CI;
same script usable locally. The CI does not decide the version; it
just enforces acknowledgment. A soft lint is rejected because it is
too easy to ignore and the version field will rot.

### 2.3 Promotion Pipeline for Calibration (Manual-PR Only)

Per DEC-015:

```text
Experience DB
  -> Offline Evaluation
  -> Benchmark
  -> Shadow Run
  -> Manual Review
  -> Merge
  -> Release
```

`CALIENNE_ENABLE_SELF_LEARNING` exists but only gates adaptive
routing in v2; it does **not** auto-promote in v1. No
`CALIENNE_AUTO_CALIBRATE` flag exists; auto-promotion in production
is dangerous, especially for routing.

A nightly CLI (`python -m calienne calibrate --since 30d`) compares
predicted vs actual per `(model, task_type)` and writes a *proposed*
`*.proposed.json`; promotion is a PR. `ProviderStrategy.version`
reads the matrix's `version` field; a bump invalidates in-flight
graphs whose `strategy_version` doesn't match.

## 3. Decision Register Lifecycle

`docs/decision_register.md` is the running ledger of architectural
decisions. Distinguished from ADRs, RFCs, and `plan.md`:

- **ADRs** are *immutable per decision*; the register is *mutable per
  status* (e.g. `Deferred -> Accepted` later). Different lifecycle.
- **RFCs** are *forward-looking design*; the register is a *ledger of
  decisions across all artifacts*. Different scope.
- **`plan.md`** is *implementation roadmap*; the register is
  *decision ledger*. Different audience.

### 3.1 Schema

| Column | Meaning |
| --- | --- |
| `ID` | `DEC-NNN` (zero-padded, monotonic). |
| `Decision` | Short human title. |
| `Status` | `Proposed | Accepted | Deferred | Rejected | Superseded`. |
| `Owner` | Role or name responsible. |
| `Date` | YYYY-MM-DD of the status set here. |
| `RFC` | Owning RFC number(s). |
| `ADR` | Backfilled ADR, or `—`. |
| `Implemented?` | Yes / No / Partial. |
| `Notes` | Free-form context. |

### 3.2 Aging Policy

Any `Proposed` decision older than **90 days** fails
`tools/check_decision_register.py` in CI. Promote to `Accepted`,
`Deferred`, or `Rejected`, or extend the deadline with a recorded
reason.

### 3.3 Superseding

A decision may supersede a prior decision by ID. The superseded
decision is moved to `Superseded` and a `Supersedes: DEC-NNN` line is
added.

## 4. Maturity Matrix Lifecycle

`docs/maturity.md` tracks per-subsystem lifecycle stage. Stages:

```text
Not Started -> Experimental -> Shadow -> Beta -> Stable -> Deprecated
```

Stars are intentionally rejected: subjective ratings decay in meaning
as the project grows. Stages are unambiguous.

A subsystem row moves stage when:

- The relevant RFC §Exit Criteria is fully checked.
- `docs/decision_register.md` is updated to reflect any new
  deferred / rejected decisions surfaced during the move.
- The PR description references the relevant RFC and ADR.

Without this discipline the matrix goes stale.

## 5. Feature Flag Lifecycle

The feature flag *specification* lives in RFC-006. The *policy* for
adding, retiring, and deprecating flags lives here.

- **Adding**: a new flag requires a row in RFC-006 §3 (with default
  `off`) and a `decision_register.md` entry.
- **Retiring**: a flag is moved to `Deprecated` in RFC-006 §3, with a
  recorded `decision_register.md` entry citing the removal RFC and
  the date.
- **Deprecating**: a deprecated flag continues to be read for one
  release, then removed. Removal is a hard CI fail in
  `tools/check_architecture_version.py` if any code path still reads
  the removed flag name.

## 6. RFC and ADR Lifecycle

### 6.1 RFCs

- One RFC number = one file (DEC-008). No `RFC-NNa`/`RFC-NNb` splits.
- If a topic grows past its file's bounds, it becomes `RFC-009`, not
  a fractional split.
- RFCs are forward-looking design; changes to an RFC's design are
  recorded in `decision_register.md` with a `DEC-NNN` mapping back to
  the RFC section that was changed.
- An RFC's `§Exit Criteria` checklist is the only authoritative
  signal that the RFC is Implemented. Without all checkboxes ticked,
  the RFC is not Implemented.

### 6.2 ADRs

- ADRs are *immutable per decision*: the `Decision` and
  `Alternatives Considered` sections do not change after `Accepted`.
- ADRs may only be `Superseded` by a later ADR (via the `Supersedes`
  field); they are never edited in place beyond `Status`.
- Backfill policy: selective, ~7-8 ADRs covering the foundational
  decisions (per N4b). New ADRs accumulate as decisions are made;
  no proactive backfill of every historical choice.

### 6.3 `plan.md`

- `plan.md` is the **master index**, not a design document.
- It is manually maintained; it is not generated from the RFCs or
  ADRs (per D4).
- Its section order is fixed: Executive Summary → RFC Pointer Table →
  ADR Pointer Table → Decision Register Pointer → Architecture
  Maturity Pointer → Milestone / Progress → Cross-RFC Invariants →
  Future Horizons.

## 7. Replay Retention

Replay traces live under `telemetry/`, indexed by `(graph_version,
prompt_fingerprint)`. **Default retention: 30 days**, configurable.
7 days is too short for comprehensive offline optimization studies;
90 days wastes storage. 30 days is a healthy engineering default.

PII / sensitive data: redacted before storage. The redaction policy
is owned here; the implementation lives in `orchestrator/execution_replay.py`
(RFC-004 §6).

## 8. Configuration Ownership

The following config files have a single owner and a single review
path. Adding fields to any of them is a non-breaking change; removing
fields is breaking and requires a `decision_register.md` entry.

| File | Owner | Reviewers |
| --- | --- | --- |
| `config/capabilities/model_capabilities.json` | RFC-003 | Architecture |
| `config/capabilities/provider_limits.json` | RFC-002 | Infrastructure |
| `config/capabilities/pricing.json` | RFC-002 | Finance + Architecture |
| `config/capabilities/routing_defaults.json` | RFC-002 | Architecture |
| `config/capabilities/prediction_calibration.json` | RFC-003 | Architecture |
| `config/prompt_versions.json` | RFC-005 (per-skill) | Architecture + Skills owners |
| `config/feature_flags.json` | RFC-006 + RFC-008 | Architecture |

## 9. Deprecation Policy

When a schema field is promoted from `Optional` to required (per
ADR-001): bump the schema's `version` and route old payloads through
a migrator. Document the migration in the owning RFC and an ADR.

When a feature flag is removed: per §5, the deprecated flag is read
for one release and then removed. Removal is enforced by
`tools/check_architecture_version.py`.

When an RFC is fully deprecated: it is moved to `Deprecated` status
in `plan.md` §2, its content is preserved, and `docs/maturity.md`
records the deprecation date and the replacing RFC.

## 10. Invariants Owned by This RFC

- Calibration promotion is manual-PR only, always (DEC-015).
- `CALIENNE_ENABLE_SELF_LEARNING` gates adaptive routing in v2 and
  does not auto-promote in v1 (DEC-005).
- Hard CI fail on architectural change without `architecture_version`
  bump (DEC-014).
- The Decision Register is the canonical ledger; ADRs are immutable
  records; RFCs are forward-looking specs; `plan.md` is the index.

## 11. Exit Criteria

This RFC is considered **Implemented** when ALL of the following are
true:

- [ ] `tools/check_architecture_version.py` exists and fails CI on
      any architectural-file change without a bump in
      `orchestrator/versioning.py`.
- [ ] `tools/check_decision_register.py` exists and fails CI on any
      `Proposed` decision older than 90 days without an extension.
- [ ] `tools/check_rfc_index.py` and `tools/check_adr_index.py`
      exist and enforce the pointer tables in `plan.md`.
- [ ] `docs/decision_register.md` is initialized with the 15
      canonical decisions from the planning thread.
- [ ] `docs/maturity.md` is initialized with the 12-row stage
      matrix.
- [ ] The architectural watchlist (§2.2) is the actual list enforced
      by `tools/check_architecture_version.py`.
- [ ] The nightly calibration CLI exists (or is a documented
      no-op with a warning if `CALIENNE_ENABLE_EXPERIENCE_DB=false`).
- [ ] `CALIENNE_ENABLE_SELF_LEARNING` exists but logs a warning when
      set to `True` in v1; no behavioral effect.
- [ ] `docs/decision_register.md` rows for DEC-005, DEC-014,
      DEC-015 are `Implemented? Yes`; `docs/maturity.md` row for
      this RFC moves to `Stable` (governance doesn't have runtime
      behavior to shadow).
- [ ] Code owner has signed off.
