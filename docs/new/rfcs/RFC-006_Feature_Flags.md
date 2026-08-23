# RFC-006: Feature Flags

- **Status:** Not Started
- **Architecture version:** `0.1.0`
- **Related ADRs:** (none — feature flags are governance-complete)
- **Owning decisions:** DEC-003, DEC-005

## 1. Purpose

This RFC defines the **feature flag namespace**, the **per-subsystem
default state**, the **typed accessor** in `orchestrator/feature_flags.py`,
and the **flag snapshot** carried by the `ExecutionManifest`. The
*lifecycle policy* for adding / retiring / deprecating flags is owned
by RFC-008 (Governance).

## 2. Namespace Convention

All flags use the `CALIENNE_ENABLE_<SUBSYSTEM>` namespace. This
namespace is **strict** — no other prefix is used. Rationale: easier
search, easier documentation, no env-var collisions.

## 3. v1 Subsystems

Every new subsystem defaults to **off**. The existing `DecisionEngine`
path stays on by default; any new subsystem that replaces or augments
it is off until explicitly flipped.

| Flag | Default | Owns | Gated subsystem |
| --- | --- | --- | --- |
| `CALIENNE_ENABLE_PLANNER` | off | StrategicPlanner + ExecutionPlanner invocation | RFC-003 §2 |
| `CALIENNE_ENABLE_DAG` | off | TaskGraph execution path; falls back to `run_micro_mode` when off | RFC-002 §3 |
| `CALIENNE_ENABLE_CONSENSUS` | off | Weighted consensus engine; judge-only when off | RFC-003 §10 |
| `CALIENNE_ENABLE_RAG` | off | Smart RAG retrieval; route-gated when on | RFC-004 §3 |
| `CALIENNE_ENABLE_REPAIR` | off | Reflection / repair loop | RFC-003 §9 |
| `CALIENNE_ENABLE_PREDICTION` | off | Prediction layer; deterministic fallback when off | RFC-003 §3.6 |
| `CALIENNE_ENABLE_CONTEXT` | off | Context manager; minimal window when off | RFC-004 §4 |
| `CALIENNE_ENABLE_SKILLS` | off | Dynamic skill composition; single-agent when off | RFC-003 §13 |
| `CALIENNE_ENABLE_EXPERIENCE_DB` | off | Experience DB writes | RFC-004 §7 |
| `CALIENNE_ENABLE_KNOWLEDGE_LAYER` | off | Knowledge / Reasoning / Validation split; merged when off | RFC-001 §2 |
| `CALIENNE_ENABLE_REPLAY` | off | Replay trace recording + `/api/debug/replay/{trace_id}` | RFC-004 §6 |
| `CALIENNE_ENABLE_META_ESCALATION` | off | MetaReasoner model-tier escalation; reserved for v2 | RFC-003 §6 (DEC-003) |
| `CALIENNE_ENABLE_SELF_LEARNING` | off | Adaptive routing (v2 only); never auto-promotes | RFC-008 (DEC-005) |

## 4. Typed Accessor

`orchestrator/feature_flags.py` exposes a typed accessor. Code reads
`if flags.planner:` not `if os.getenv(...)`. Recommended `dataclass`:

```python
from dataclasses import dataclass
import os

@dataclass(frozen=True)
class FeatureFlags:
    planner: bool
    dag: bool
    consensus: bool
    rag: bool
    repair: bool
    prediction: bool
    context: bool
    skills: bool
    experience_db: bool
    knowledge_layer: bool
    replay: bool
    meta_escalation: bool
    self_learning: bool

def load_flags(env: dict | None = None) -> FeatureFlags:
    e = env or os.environ
    return FeatureFlags(
        planner=_bool(e, "CALIENNE_ENABLE_PLANNER"),
        dag=_bool(e, "CALIENNE_ENABLE_DAG"),
        consensus=_bool(e, "CALIENNE_ENABLE_CONSENSUS"),
        rag=_bool(e, "CALIENNE_ENABLE_RAG"),
        repair=_bool(e, "CALIENNE_ENABLE_REPAIR"),
        prediction=_bool(e, "CALIENNE_ENABLE_PREDICTION"),
        context=_bool(e, "CALIENNE_ENABLE_CONTEXT"),
        skills=_bool(e, "CALIENNE_ENABLE_SKILLS"),
        experience_db=_bool(e, "CALIENNE_ENABLE_EXPERIENCE_DB"),
        knowledge_layer=_bool(e, "CALIENNE_ENABLE_KNOWLEDGE_LAYER"),
        replay=_bool(e, "CALIENNE_ENABLE_REPLAY"),
        meta_escalation=_bool(e, "CALIENNE_ENABLE_META_ESCALATION"),   # always False in v1 runtime
        self_learning=_bool(e, "CALIENNE_ENABLE_SELF_LEARNING"),       # always False in v1 runtime
    )
```

Flags load from env with precedence: env > `config/feature_flags.json`
> hardcoded default (off).

## 5. Manifest Snapshot

The `ExecutionManifest.feature_flags` field (RFC-005 §3) carries the
**full set with explicit booleans** (per OQ-E). Missing key =
"didn't exist" or "wasn't loaded." This preserves the distinction
between "disabled" / "didn't exist" / "wasn't loaded" for
replay-debugging reproducibility.

Example:

```json
{
  "feature_flags": {
    "CALIENNE_ENABLE_PLANNER": true,
    "CALIENNE_ENABLE_DAG": true,
    "CALIENNE_ENABLE_CONSENSUS": false,
    "CALIENNE_ENABLE_REPAIR": true,
    "CALIENNE_ENABLE_SELF_LEARNING": false
  }
}
```

## 6. Lifetime and Deprecation

Adding, retiring, and deprecating flags is governed by RFC-008. A
flag that is scheduled for removal is marked `Deprecated` in this
RFC's table (§3) and the relevant decision is recorded in
`decision_register.md`.

## 7. Invariants Owned by This RFC

- The `CALIENNE_ENABLE_<SUBSYSTEM>` namespace is strict.
- The manifest carries the **full** flag set with explicit booleans.

## 8. Exit Criteria

This RFC is considered **Implemented** when ALL of the following are
true:

- [ ] `orchestrator/feature_flags.py` exists with the `FeatureFlags`
      dataclass and `load_flags()` function.
- [ ] `config/feature_flags.json` exists with all 13 flags declared.
- [ ] Every code path that branches on a flag uses the typed
      accessor (`if flags.planner:`), not `os.getenv`.
- [ ] `ExecutionManifest.feature_flags` carries the full set with
      explicit booleans; missing flags are reported as `false` (i.e.,
      the snapshot is complete regardless of which flags were active
      at request start).
- [ ] `CALIENNE_ENABLE_META_ESCALATION` and
      `CALIENNE_ENABLE_SELF_LEARNING` log a warning when set to `True`
      in v1 and have no behavioral effect.
- [ ] Unit tests proving the precedence chain:
      env > `config/feature_flags.json` > hardcoded default.
- [ ] `docs/decision_register.md` rows for DEC-003, DEC-005 are
      updated; `docs/maturity.md` row for this RFC moves to
      `Experimental`.
- [ ] Code owner has signed off.
