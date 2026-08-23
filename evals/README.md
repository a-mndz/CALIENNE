# evals/ — measurement layer (Stage 3)

Built from `.research_tmp/retry_eval_ci.md` (Miller Eq. 10 analysis, verified
McNemar table, fork-PR secret constraint). Statistics rule enforced here:

- **No aggregate-score gate.** At n=50 an aggregate gate cannot detect <15.8 pp
  (Corr=0.68) / 19.8 pp (Corr=0.5). The exact McNemar test detects 6 net flips
  (12 pp) with zero variance/correlation assumptions.
- **Blocking = zero API calls.** Fork PRs receive no secrets and temperature 0 is
  not determinism, so nothing needing a provider key may be a required check.
- **Stochastic = separate, non-blocking workflow** (`.github/workflows/evals.yml`).

## Layout

| Path | Gate | What it is |
|---|---|---|
| `golden/v1.jsonl` + `MANIFEST.json` | G5 | 50 input queries, 10 clusters, SHA-256 frozen. Never edit v1 in place — create v2. |
| `firewall_corpus.jsonl` | G3 | 56 frozen (claim, evidence, expected_status) rows, 100% exact match required. |
| `firewall_known_gaps.md` | — | 14 measured matcher blind spots; acceptance targets for firewall v2. |
| `mcnemar.py` | G6 | Exact two-sided binomial sign test + paired run comparison + CLI. |
| `beta.py` | β | Dual-agent co-failure ceiling with Wilson CI + per-cluster breakdown. |
| `capture.py` | G6/G7 | Live runner: grader v1, redaction on capture, `--max-calls` cost ceiling, `--reruns` for the judge noise floor. |
| `validate.py` | G5 | Manifest hash, schema, fingerprint, cluster, leakage; corpus schema. `python -m evals.validate`. |
| `runs/` | — | Captured per-item outcomes (gitignored; one JSONL per label). |

## Commands

```bash
python -m evals.validate                        # G5 integrity (blocking)
python -m evals.capture --label baseline        # live capture (needs keys)
python -m evals.capture --label candidate       # second arm
python -m evals.mcnemar evals/runs/baseline.jsonl evals/runs/candidate.jsonl
python -m evals.beta evals/runs/baseline.jsonl  # β + benefit ceiling
python -m evals.capture --label noise --reruns 3 --limit 20   # G7 flip rate
```

McNemar reference thresholds (two-sided exact p ≤ 0.05): minimum b (regressed)
given c (improved) — c=0→6, c=1→8, c=2→10, c=3→12, c=4→13, c=5→15.

## β decision rule (dual-agent topology)

Run `evals.beta` on a captured run. β = P(both agents fail) — items no judge can
rescue. benefit ceiling = P(exactly one succeeds) — items arbitration could
rescue. If measured β leaves a benefit ceiling the judge does not convert, the
second agent is not earning its latency/cost; that data — not taste — decides
Stage 4's topology work. The DAG surface stays behind its flags (all OFF) until
this measurement exists; deleting vs reviving it is a Stage 4 decision.
