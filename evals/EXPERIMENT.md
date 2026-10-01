# Running the experiment — from zero to a defensible number

This is the procedure the repo's own decision rule (`evals/README.md`) has
required since 2026-08-22 and which had only ever been run ONCE (n=50,
β=0.54, never replicated).

## 0. Preconditions

- Provider keys loaded (keyring via `secrets_bootstrap`, or `CALIENNE_*` env).
- No Postgres needed: capture runs fully in-memory.
- Commit your working tree first: every run row stamps `git_commit`.

## 1. Smoke (≈15 calls, prove the plumbing)

```bash
python -m evals.run_experiment --label-prefix smoke --limit 3 --allow-simulation
# numbers from a --allow-simulation run prove NOTHING about correctness —
# rows are labelled *sim and excluded from live comparisons
```

Then a live smoke (real spend, tiny):

```bash
python -m evals.run_experiment --label-prefix smoke2 --limit 3 --max-calls 60
```

## 2. The full comparison (~550 calls)

```bash
python -m evals.run_experiment --label-prefix exp1
```

Steps executed: triad vs single on golden v2, triad vs single on gsm8k_v1,
and a 3-rep noise floor on v2.

## 3. Read the results

```bash
python -m evals.report evals/runs/exp1-triad-v2.jsonl evals/runs/exp1-single-v2.jsonl \
    evals/runs/exp1-triad-gsm.jsonl evals/runs/exp1-single-gsm.jsonl \
    evals/runs/exp1-noise-v2.jsonl
python -m evals.mcnemar evals/runs/exp1-single-v2.jsonl evals/runs/exp1-triad-v2.jsonl
python -m evals.mcnemar evals/runs/exp1-single-gsm.jsonl evals/runs/exp1-triad-gsm.jsonl
python -m evals.beta evals/runs/exp1-triad-v2.jsonl
```

Exit code 1 from mcnemar means significant regression (single > triad).

## 4. Interpret honestly

- **SUSPECT validation_score** → the judge metric is inert; fix the judge
  path before quoting any quality number.
- **Noise floor high** → differences below the flip rate are not signal.
- **Triad ≈ single** → by the repo's own decision rule, the dual-agent
  architecture is not earning its 4× cost. Report that. It is a result.
- **Commit the run files** (`evals/runs/`) with the label and the report —
  an uncommitted run is unreproducible and therefore not evidence.

## 5. What the numbers mean

| Metric | Meaning | Feeds |
|---|---|---|
| pass (v2) | liveness AND reference checks | the headline correctness number |
| pass (gsm8k) | exact numeric answer match | external validity |
| β̂ | fraction of items where BOTH agents fail (liveness) | architecture cost/benefit |
| mcnemar p | is triad vs single significant? | the decision rule |
| G7 noise floor | verdict flip rate across reps | required context for every other number |
