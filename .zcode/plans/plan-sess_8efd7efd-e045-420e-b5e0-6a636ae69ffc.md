# Calienne: Improve, Judge, Audit — Implementation Plan

**Scope (your choices):** Quarantine dead modules to `attic/` · Prepare evals only, YOU trigger live runs · Focused (eval + metrics + README, no god-file splits, minimal security) · Commit per phase.

Working tree note: the surgical audit fixes from the previous session (config aliases, score default 0.0, kill-switch rename, secrets_bootstrap, server.py, tools.py sim result) are still uncommitted — they land as Phase A.

---

## Phase A — Commit existing audit fixes
The 8-file diff already in the working tree (`core/config.py`, `core/schemas.py`, `core/tools.py`, `orchestrator/pipelines.py`, `orchestrator/calienne_orchestrator.py`, `secrets_bootstrap.py`, `server.py`, `tests/test_pipeline_repair.py`).
Commit: `fix: audit surgical fixes — score default, kill-switch case, rename debris`

## Phase B — Quarantine dead modules (commit 2)
1. Create `attic/README.md`: what each module was, why quarantined (test-only importers, unreachable from live path), how to revive.
2. `git mv` into `attic/`: `orchestrator/mcts.py`, `orchestrator/embeddings.py`, `core/tools.py`, `core/chunking.py`, `evals/rubric.py`, plus their paired tests (`tests/test_mcts.py`, `tests/test_embeddings.py`, `tests/test_agent_tools.py`, chunking test, `tests/test_evals_rubric.py`) → `attic/tests/` (not collected: `pytest.ini` testpaths=tests).
3. Grep-verify zero remaining importers outside attic; adjust any re-export shim.
4. Full pytest + ruff → green.
Commit: `refactor: quarantine unreachable modules to attic/`

## Phase C — Metrics & judge honesty fixes (commit 3)
1. **Real token accounting**: thread `get_last_provider_usage()` (already in `api_gateway/client.py`) into `track_execution_metrics` (`core/runtime.py:405` hardcodes `tokens=0`) and the passport; keep len//4 as simulation fallback.
2. **Retry classification** (`api_gateway/rate_limiter.py:942-994`): retry only 429/5xx/timeouts/network errors; no jitter sleep before first attempt.
3. **max_tokens pass-through**: add optional param through `execute_with_contracts` (`core/runtime.py:236-248`) → dispatch → client; send 8192 on both judge paths (`orchestrator/evaluation.py:134-164`) to kill the live truncation regression.
4. **Per-role temperature**: add role→temperature map (breaker 0.0, judge 0.1, logician 0.2, creative 0.8) wired through dispatch → client, overridable via config; kills the "diversity = two identical-temp self-reports" fiction.
5. **Gate multi-judge consensus** behind `flags.consensus` (flag already exists, default False) in `orchestrator/decisions.py:192-298` — stops up to 6 ungated extra calls per "password"-keyword query. (Making consensus *heterogeneous* is deferred until your eval says judge quality is the bottleneck.)
6. New unit tests for all of the above.
Commit: `fix: honest metrics — token usage, retry classes, judge max_tokens, role temperatures, consensus gate`

## Phase D — Eval/judging upgrade (commit 4) — the research core
1. **Multi-version manifest**: `evals/golden/MANIFEST.json` → per-version entries; update `evals/validate.py:load_golden` (v1 hash unchanged → still validates).
2. **Golden v2 with reference answers**: same 50 v1 queries + `expect.checks` — small deterministic vocabulary (`numeric`, `contains_all` key facts, `regex`, `no_failure_marker`). Authored by me from each query, leakage-scanned by existing validate.py.
3. **External math arm**: `evals/tools/fetch_gsm8k.py` (httpx → public HF datasets-server, zero new deps) → `evals/golden/gsm8k_v1.jsonl` (~50 items, exact numeric answers). I run the fetch during implementation (public data, no LLM spend).
4. **Single-model baseline arm**: `--arm {triad,single}` on `evals/capture.py` + injectable runner in `capture()` (triad entry currently hardcoded at line 132). Single arm = one direct `AsyncAPIGateway.post_request` per item, cost cap ×1, same row schema.
5. **Run provenance**: rows gain `git_commit`, `model_ids`, `temperature`, `simulated`; implement the `*sim` label tagging that capture.py's help text already promises.
6. **Noise-floor fix**: `evals/mcnemar.py` crashes on `--reruns>1` files — add id-aggregation (majority pass).
7. **`evals/report.py`**: markdown summary — pass rates, per-cluster, validation_score distribution + SUSPECT invariant (all-zero/constant scores void the run), mcnemar/beta passthrough.
8. **`evals/run_experiment.py`** orchestrator + `evals/EXPERIMENT.md` with the exact commands for YOUR live runs (validate → triad → single → noise floor → mcnemar → beta → report).
9. Tests: manifest multi-version, arm selection (sim mode), report invariant, mcnemar aggregation.
Commit: `feat: real eval arms — golden v2 references, gsm8k arm, single-model baseline, provenance, report`

## Phase E — README honesty rewrite (commit 5)
Rewrite README.md to describe what actually boots: triad pipeline + breaker + fallback/circuit-breaking + auth + eval harness. Remove/mark: MCTS-PRM, consensus-as-feature, pgvector embeddings claims, "calibrated LLM-judge rubrics", agent tools. Add a "What is NOT implemented" section linking `attic/` and AUDIT_AND_GAPS.md.
Commit: `docs: README describes the system that actually runs`

## Phase F — Final judge & audit (report, no commit)
1. Full pytest + ruff + `python -m evals.validate` → all green.
2. Re-audit the changed surface (focused agents) for regressions I introduced.
3. Final plain-English report: what changed, what the numbers machinery now measures, the exact live-run commands for you, remaining risks ranked.

**Out of scope (documented, not fixed):** god-file splits, security hardening (admin bootstrap, sandbox, injection rework), heterogeneous consensus, live eval execution (yours to trigger).

**Risks:** core/tools.py re-exports may have hidden importers (grep before move; suite after each phase); client tests asserting temperature=0.1 may need updating; capture.py has existing tests that must keep passing.
