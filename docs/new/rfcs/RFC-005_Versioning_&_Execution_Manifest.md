# RFC-005: Versioning & Execution Manifest

- **Status:** Not Started
- **Architecture version:** `0.1.0`
- **Related ADRs:** ADR-006
- **Owning decisions:** DEC-006, DEC-009, DEC-014

## 1. Purpose

This RFC defines the **version stamp model** (graph, planner,
scheduler, budget, routing, capabilities, contracts, resource
policy, prediction, prompt-per-skill), the **graph fingerprint**
(SHA-256 of the canonical DAG), the **Architecture Version**
semantics (SemVer, starts at `0.1.0`), the **`git_commit` capture**
chain, the **`ExecutionManifest`** (frozen, `manifest_schema_version`
decoupled), and the **metric namespace specification**. It does not
define the planner or scheduler (RFC-003), memory or RAG (RFC-004),
feature flags (RFC-006), the roadmap (RFC-007), or governance
(RFC-008).

## 2. VersionStamp

`orchestrator/versioning.py` owns all of the following. Every
version is set by its **producer**, not its consumer.

```python
class VersionStamp(CalienneBaseModel):
    architecture_version: str          # "0.1.0"
    planner_version: str | None
    scheduler_version: str | None
    budget_version: str | None
    routing_version: str | None         # includes MODEL_CAPABILITY_WEIGHTS version
    capabilities_version: str | None
    prompt_versions: dict[str, str]    # per-skill; e.g. {"coder": "7"}
    consensus_version: str | None
    contracts_version: str | None
    resource_policy_version: str | None
    prediction_model_version: str | None
    graph_version: str | None           # monotonic counter
    graph_fingerprint: str | None       # SHA-256 of canonical DAG
```

### 2.1 Architecture Version

- `architecture_version: "0.1.0"` initial value.
- Progression: `0.1.0 -> 0.2.0 -> 0.5.0 -> 0.8.0 -> 1.0.0`.
- `1.0.0` is reserved for "stable, backward-compatible."
- Lives as a constant in `orchestrator/versioning.py`. Bumping is a
  breaking change and must be recorded in `decision_register.md`
  and an ADR.

### 2.2 git_commit Capture

Never raises, no subprocess at request time. Priority chain:

```python
git_commit = (
    os.getenv("CALIENNE_GIT_COMMIT")
    or os.getenv("GIT_COMMIT")
    or _read_ci_metadata()      # reads .git_commit_sha
    or "unknown"
)
```

Captured at process start, not per request. Works for local dev,
Docker, GitHub Actions, GitLab CI, and self-hosted runners.

### 2.3 Graph Version vs Graph Fingerprint

Two different keys, two different uses:

| Key | Type | Use |
| --- | --- | --- |
| `graph_version` | monotonic counter | A/B bucket routing, database filtering, reports |
| `graph_fingerprint` | SHA-256 of canonical DAG | Cache lookup, replay, deduplication, observation |

Fingerprint is `sha256(canonical_json({nodes, edges, contracts}))`.
The **`TopologyNormalizer`** orders nodes topologically and assigns
positional IDs before hashing. Two planners independently generating
the same DAG produce the same fingerprint.

Fingerprint is **not** used to skip validation in v1 (ADR-006); it is
used for deduplication, replay, analytics, and caching only.

### 2.4 `VersionRegistry`

`graph_version` is a monotonic counter from a small `VersionRegistry`
keyed by `(planner_version, strategy_version, contract_version)`. In
v1, the registry is in-memory at process start; persisted to
`telemetry/version_registry.jsonl` once replay (RFC-004 §6) is live.

## 3. ExecutionManifest

`orchestrator/execution_manifest.py`. A single immutable manifest per
request, attached to `TaskGraph`, `ExecutionTrace`, `Experience`, and
`ExecutionPassport`.

### 3.1 Schema

```python
class ExecutionManifest(CalienneBaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")   # critical contract (RFC-001 §4)
    manifest_schema_version: str        # "1.0"; decoupled from architecture_version (DEC-009)
    architecture_version: str           # "0.1.0"
    planner_version: str | None
    scheduler_version: str | None
    routing_version: str | None
    capabilities_version: str | None
    prompt_versions: dict[str, str]
    feature_flags: dict[str, bool]     # full set with explicit booleans
    git_commit: str
    host: HostPrimitives               # environment snapshot for replay
```

### 3.2 `HostPrimitives`

Replay often fails due to environment differences, not code
differences. Capture once at process start; never at request time.

```python
class HostPrimitives(CalienneBaseModel):
    os: str
    os_version: str | None
    python_version: str | None
    python_implementation: str | None
    cuda_version: str | None           # None when torch.cuda.is_available() is False
    platform_machine: str | None
    container: bool
    container_runtime: str | None
```

### 3.3 Feature flag snapshot

The **full set** of relevant flags with explicit booleans (per
OQ-E). Missing key = "didn't exist" or "wasn't loaded," never
ambiguous. "Relevant" = every flag declared in
`orchestrator/feature_flags.py`'s typed accessor.

### 3.4 Immutability

Frozen Pydantic model (`ConfigDict(frozen=True)`). Built once at
request start and overwritten once when the strategic plan is built
(so `planner_version` is known). Frozen from that point. No custom
`__setattr__`.

### 3.5 `manifest_schema_version`

Independent from `architecture_version` (DEC-009). The manifest can
evolve (new fields, renamed keys, additional telemetry) without
forcing an architecture bump. Parsers can interpret older manifests
correctly.

## 4. Metric Namespace Specification

This RFC owns the **specification** of the metric namespaces. The
**emission** of each metric is owned by the component RFC (per N2
discussion).

### 4.1 Namespaces

| Namespace | Owned by RFC | Examples |
| --- | --- | --- |
| `execution.*` | RFC-002 | `execution.node.started`, `execution.node.completed`, `execution.node.failed`, `execution.retries`, `execution.repairs` |
| `quality.*` | RFC-001, RFC-003 | `quality.confidence`, `quality.calibration`, `quality.evidence_strength`, `quality.contradiction_score`, `quality.unsupported_claim_count` |
| `resources.*` | RFC-002 | `resources.tokens.consumed`, `resources.tokens.remaining`, `resources.concurrency.active`, `resources.concurrency.cap`, `resources.rate_limit.headroom`, `resources.gpu`, `resources.cpu`, `resources.memory`, `resources.connection_pool.size` |
| `prediction.*` | RFC-003 | `prediction.cost.predicted`, `prediction.cost.actual`, `prediction.latency.predicted`, `prediction.latency.actual`, `prediction.calibration_confidence`, `prediction.repair.likelihood` |
| `learning.*` | RFC-003, RFC-004 | `learning.graph.fingerprint`, `learning.planner.quality`, `learning.mutation.audit`, `learning.user_satisfaction` |
| `environment.*` | RFC-005 | `environment.os`, `environment.python_version`, `environment.cuda_version`, `environment.container` |
| `manifest.*` | RFC-005 | `manifest.architecture_version`, `manifest.graph_version`, `manifest.graph_fingerprint`, `manifest.git_commit` |
| `scheduler.*` | RFC-003 | `scheduler.node.queued`, `scheduler.node.released`, `scheduler.priority_band`, `scheduler.starvation_promoted` |
| `planner.*` | RFC-003 | `planner.invocation`, `planner.output.valid`, `planner.output.invalid`, `planner.template.fallback`, `planner.fingerprint.hash` |

### 4.2 Naming convention

`<namespace>.<component>.<event_or_metric>` — lowercase, dot-separated,
no acronyms unless industry-standard (`cpu`, `gpu`, `ram`, `tpm`,
`rpm`).

### 4.3 Schema, versioning, retention

Specified in this RFC §4. Emission specified in each component RFC.

## 5. Prompt Versions (per-skill)

`config/prompt_versions.json` (NOT inside `skills.py`):

```json
{
  "coder": { "version": "7", "template": "coder_v7" },
  "security": { "version": "5", "template": "security_v5" },
  "academic": { "version": "3", "template": "academic_v3" },
  "researcher": { "version": "12", "template": "researcher_v12" }
}
```

Resolution order (per OQ5 and OQ-H): env override (`CALIENNE_PROMPT_VERSIONS_PATH`)
→ default `config/prompt_versions.json` → `skills.py` built-in defaults
(with a warning).

Update prompt versions without code changes; easier A/B; easier
replay; cleaner separation of concerns. `skills.py` defines behavior
and composition; `prompt_versions.json` defines which template
revision is active.

## 6. Capabilities Loader

`api_gateway/capabilities.py`. Loads from
`config/capabilities/` (per ADR-005 / RFC-002 §5). On load failure,
falls back to neutral default `0.5` and emits
`capability_load_failed` metric. **Never** raises into the request
path.

`ProviderStrategy.version` reads the matrix's `version` field; a
bump invalidates in-flight graphs whose `strategy_version` doesn't
match ( rollback rule per `plan.md` §7.6).

## 7. Invariants Owned by This RFC

- `manifest_schema_version` is decoupled from `architecture_version`
  (DEC-009).
- Manifest is frozen and contains the full feature-flag map with
  explicit booleans (per OQ-E).
- The fingerprint is for dedup/replay/analytics/caching only — never
  validation skip in v1 (ADR-006, DEC-004).
- Every scheduler task gets an explicit name and a cancellation
  boundary hook (per `plan.md` §7.7).

## 8. Exit Criteria

This RFC is considered **Implemented** when ALL of the following are
true:

- [ ] `orchestrator/versioning.py` exists with `VersionStamp`,
      `VersionRegistry`, the `architecture_version` constant
      (`"0.1.0"`), and the `git_commit` capture chain.
- [ ] `orchestrator/execution_manifest.py` exists; `ExecutionManifest`
      is `frozen=True` and `extra="forbid"`.
- [ ] `HostPrimitives` is captured once at process start;
      `cuda_version` is `None` when CUDA is unavailable.
- [ ] `graph_fingerprint` (SHA-256) is implemented via
      `TopologyNormalizer`; two structurally identical DAGs hash to
      the same value (unit-tested).
- [ ] `graph_version` (monotonic) is implemented via
      `VersionRegistry`; in-memory in v1.
- [ ] `config/prompt_versions.json` exists with per-skill entries;
      `orchestrator/skills.py` loads via
      `CALIENNE_PROMPT_VERSIONS_PATH` → default → built-in fallback.
- [ ] Metric namespace spec is documented (this RFC §4.1).
- [ ] Every component RFC's emission rules are referenced from this
      spec (cross-links).
- [ ] `tools/check_architecture_version.py` fails when an
      architectural file is changed without a bump in
      `orchestrator/versioning.py`.
- [ ] Unit tests for: fingerprint determinism, version registry
      monotonicity, manifest frozen enforcement, `git_commit` fallback
      chain.
- [ ] `docs/decision_register.md` rows for DEC-006, DEC-009, DEC-014
      are updated; `docs/maturity.md` row for this RFC moves to
      `Experimental`.
- [ ] ADR-006 is `Status: Accepted`.
- [ ] Code owner has signed off.
