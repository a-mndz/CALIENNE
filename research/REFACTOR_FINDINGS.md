# CALIENNE Refactor Findings & Implementation Plan

> **Branch:** `refactor/architecture-fixes` (created 2026-08-19)
> **Base:** `main` at commit `cef2ed3` ("updates")
> **Status:** Steps 0-4 complete and verified. **Nothing committed** — all changes are working-tree only.
> **Last verified against code:** 2026-08-20 — `412 passed, 2 skipped` (Docker), `ruff check .` clean

---

## Completed This Session (uncommitted)

| Step | What landed | Verified by |
|---|---|---|
| 0 | Finished provider-side rename → `ProviderResourceManager` (option A, 4 files) | imports resolve; 398 passed |
| 1 | Deleted legacy inline pipeline: 1077 → 748 lines (−329) | ruff clean; 398 passed |
| 2 | Declared `structlog` + `prometheus-client` in `requirements.txt` | — |
| 3 | `core.config.configure_logging()` — JSON in prod, console in dev | `tests/test_observability.py` (5 tests) |
| 4 | `orchestrator/metrics.py` + authenticated `GET /metrics` | `tests/test_observability.py` (9 tests) |

Files touched: `api_gateway/rate_limiter.py`, `orchestrator/resource_manager.py`,
`orchestrator/calienne_orchestrator.py`, `orchestrator/pipelines.py`, `orchestrator/metrics.py` *(new)*,
`core/config.py`, `main.py`, `server.py`, `requirements.txt`,
`tests/test_providers_repair.py`, `tests/test_pipeline.py`, `tests/test_pipeline_repair.py`,
`tests/test_observability.py` *(new)*.

### Decisions taken during implementation

1. **Rename scope: option A only.** `ProviderResourceManager` alone removes the collision — no two
   classes share a name. `orchestrator.resource_manager.ResourceManager` was left alone; its module
   path disambiguates it and the `DagResourceManager` alias at `calienne_orchestrator.py:126`
   documents intent. Saved 4 files of churn. Option B remains available if that class grows public API.

2. **`/metrics` gets its own bearer token, not `require_role("admin")`.** Prometheus cannot present
   the httpOnly JWT cookie the admin endpoints use. New setting `CALIENNE_METRICS_TOKEN`:
   mandatory in production (**503 when unset** — fails closed rather than exposing internals),
   optional elsewhere so local scraping needs no setup. Compared with `secrets.compare_digest`.

3. **`show_locals=False` on production tracebacks — security, not style.** structlog's default
   `dict_tracebacks` serialises every local in scope at raise time, which would have written API
   keys, JWTs, and DB passwords into the log aggregator. Replaced with
   `ExceptionRenderer(ExceptionDictTransformer(show_locals=False))`; frames are kept, locals dropped.
   Regression-tested in `test_production_traceback_omits_locals`.

4. **Metrics are pull-based.** Gauges refresh from the live `DecisionEngine`/`ProviderPool` at scrape
   time, so the hot request path performs no metric writes. A private `CollectorRegistry` avoids
   "Duplicated timeseries" on re-import and keeps the scrape to CALIENNE series only.

5. **Inactive provider statuses are emitted as `0`, not omitted.** A vanishing series is
   indistinguishable from a dead scrape target, which would make `status="dead"` alerts unfireable.

6. **OpenTelemetry deliberately left undeclared.** Installed in `.venv`, imported by nothing.
   Declaring it now would be speculative; it lands with the tracing step. Note for that step: the
   installed exporter is `opentelemetry-exporter-otlp-proto-**http**==1.42.1`, not the grpc variant.

7. **`LOG_FORMAT` retained** as the plain-text fallback path only (used if `structlog` is somehow
   missing). Field description updated to say so rather than deleting a setting operators may set.

---

## ⚠️ Historical: The Break This Session Opened With

The uncommitted 1-line diff in `api_gateway/rate_limiter.py:543` had renamed the class but left
every importer on the old name. **Fixed in Step 0**; recorded here because the earlier plan listed
the rename as merely "IN PROGRESS" and gave no sign the tree would not import.

```
ImportError: cannot import name 'ResourceManager' from 'api_gateway.rate_limiter'
  orchestrator/resource_manager.py:36
```

Broken importers, all now updated: `orchestrator/resource_manager.py:37` (**missing from every
earlier doc's touch map** — and the file that actually threw),
`orchestrator/calienne_orchestrator.py:52,98,100`, `tests/test_providers_repair.py:17,39,43,54,66`.
`api_gateway/__init__.py` does not re-export it — no change was needed there.

---

## Corrections To The Earlier Docs

`ISSUES_AND_FIXES.md` and `CALIENNE_DEEP_RESEARCH.md` were written from documentation +
inspection. Six claims were stale or wrong; the rest verified accurate.

1. **Naming inconsistency across docs.** Deep research §3.2 says `DagResourceManager (or
   ConcurrencyManager)`; `ISSUES_AND_FIXES.md` line 53 says `DagConcurrencyManager` but line 65
   says `DagResourceManager`. **Resolved: option A — the second rename was not done.** See
   "Decisions taken" #1.

2. **`core/runtime.py` needed no change.** Lines 115 and 141 are a class docstring and a param
   docstring. No import, no annotation.

3. **`orchestrator/resource_manager.py` was a *source* file requiring change**, not just the
   definition site. It consumes the provider-level class as `RateLimiter`.

4. **Removing the legacy pipeline broke three tests.** Neither doc mentioned this:
   - `tests/test_pipeline.py:29` — `assert callable(pipelines._legacy_pipeline_blocked_msg)`
   - `tests/test_pipeline_repair.py:23` — imported `_legacy_pipeline_blocked_msg`
   - `tests/test_pipeline_repair.py:39-43` — asserted `_is_legacy_pipeline_opted_in()` behaviour

   All three rewritten to assert the *new* contract: `decision_engine` is required, the removed
   symbols are gone, and setting `calienne_LEGACY_PIPELINE_ENABLED=true` no longer resurrects the path.

5. **Observability deps were present in `.venv` but undeclared.** So Steps 3-4 were smaller than the
   docs assumed — but CI would have installed a different environment than local. Now pinned.

6. **Stale worktree pollutes all searches.**
   `.claude/worktrees/calienne-pipeline-hardening-2026-08-10/` is a full duplicate checkout. Every
   `grep -r` returns doubled hits. Use `--exclude-dir=.claude --exclude-dir=.venv --exclude-dir=.ua`
   or delete the worktree.

**Verified accurate** (no change): legacy branch really was `pipelines.py:209-493` (~285 lines, 329
including the now-dead helpers) inside `run_micro_mode`; `decisions.py` = 621 lines; dual-path
claim/validation via `_process_claims_for_outputs` / `_apply_output_firewall` vs
`validation_layer.py` (226 lines); `test_runtime_repair.py:149,185` mocks are local — not renamed.

---

## What Landed, In Detail

### Step 0 — Provider rename (done)

```
api_gateway/rate_limiter.py:543           class ProviderResourceManager
orchestrator/resource_manager.py:37       ProviderResourceManager as RateLimiter
orchestrator/calienne_orchestrator.py     :52 docstring, :98 import, :100-101 construct + log
tests/test_providers_repair.py            import + 4 usages
```

- [x] `python -c "import orchestrator.calienne_orchestrator, server, main"` succeeds
- [x] Remaining `ResourceManager` matches are all DAG-level or the 2 local mocks — zero collision
- [x] Full suite green

### Step 1 — Legacy pipeline removed (done)

Deleted from `orchestrator/pipelines.py`: `_LEGACY_PIPELINE_ENV`,
`_legacy_pipeline_blocked_msg()`, `_is_legacy_pipeline_opted_in()`, `_ABSENCE_SENTINEL`,
`_is_knowledge_absent()`, and the inline branch at `:209-493`. The guard is now a plain
`RuntimeError` naming CRIT-001 and the missing `decision_engine`.

Imports orphaned by the deletion and removed: `parse_and_repair`, `assemble_generation_prompts`,
`SecurityValidationError`, `arbitrate_and_synthesize`, `SequenceMatcher`.
Kept (still used by `_run_with_decision_engine`): `_process_claims_for_outputs`,
`_apply_output_firewall`, `_calculate_confidence_delta`, `_ensure_agent_output`,
`_mark_conversation_failed`.

- [x] 1077 → **748** lines
- [x] Only surviving `stream_micro_mode` mention is the `streaming.py:332` docstring (harmless)
- [x] Missing `decision_engine` still raises with a clear message (regression-tested)

### Steps 3-4 — Observability (done)

`core/config.py` gained `configure_logging(settings=None, *, force=False)`. It installs one
`ProcessorFormatter` handler on the root logger, so the codebase's existing
`logging.getLogger(__name__)` calls with `%`-style args flow through the same chain as
structlog-native calls — **no call sites changed**. Idempotent, since both `main.py` and
`server.py`'s lifespan call it.

`orchestrator/metrics.py` exports (names mirror `DecisionMetrics`):
`calienne_breaker_pass_rate`, `calienne_judge_agreement_rate`, `calienne_synthesis_quality_avg`,
`calienne_total_decisions`, `calienne_provider_health{provider,status}`,
`calienne_provider_consecutive_failures{provider}`, `calienne_provider_available{provider}`.
`refresh()` swallows and logs component errors — a scrape must never take down the process it
scrapes — and tolerates `None` components so a scrape during startup returns what it can.
`python -m orchestrator.metrics` runs the self-check.

---

## Next Up (unchanged from `ISSUES_AND_FIXES.md`)

DecisionEngine decomposition (keystone, 2d) → unify claim/validation paths (1d) → config
unification (1d) → OTel tracing (3d) → alerting rules. Those sections of `ISSUES_AND_FIXES.md`
are still valid as written.

The alerting rules in `ISSUES_AND_FIXES.md` §Observability-4 will work against the metric names
above as-is — `calienne_provider_health{status="dead"} == 1` fires correctly because inactive
statuses are emitted as `0` rather than omitted.

---

## Verification Commands

```bash
cd /c/Users/amand/Downloads/CALIENNE

python -c "import orchestrator.calienne_orchestrator, server, main"
python -m orchestrator.metrics          # metrics self-check
python -m ruff check .
python -m pytest -q tests/              # full run — use -x only when iterating on one failure
python -m pytest -q tests/test_observability.py

# grep without the stale-worktree / venv noise:
GREP="grep -rn --include=*.py --exclude-dir=.venv --exclude-dir=.claude --exclude-dir=.ua"
$GREP "class ResourceManager" .
```

---

## Notes For Next Session

1. **Branch `refactor/architecture-fixes` has uncommitted work for Steps 0-4.** Review then commit;
   nothing was committed or pushed.
2. **Do not rename** the local mock classes at `tests/test_runtime_repair.py:149,185`.
3. **Always exclude** `.claude/worktrees/`, `.venv/`, `.ua/` from greps — the worktree is a full
   duplicate checkout and doubles every result.
4. `CALIENNE_METRICS_TOKEN` must be set before any production deploy, or `/metrics` returns 503.
5. OpenTelemetry is installed locally but undeclared on purpose — declare it with the tracing step,
   and note the installed exporter is the **http** OTLP variant, not grpc.

