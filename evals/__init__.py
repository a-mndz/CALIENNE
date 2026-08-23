"""AETHERIS evaluation harness (remediation plan Stage 3, 2026-08-22).

Blocking gates (zero API calls, run under pytest / ``python -m evals.validate``):
  G1 judge-prompt containment   — tests/test_judge_prompt_g1.py
  G2 consensus invariants       — tests/test_consensus_invariants.py
  G3 claim-firewall corpus      — evals/firewall_corpus.jsonl, checked by tests + validate
  G4 dependency pinning         — tools/check_pins.py
  G5 golden-set integrity       — evals/golden/, checked by tests + validate

Stochastic (live models, NON-blocking; separate workflow, never required):
  G6 paired judge regression    — evals.mcnemar on two captured run files
  G7 judge noise floor          — evals.capture --reruns K, agreement across reruns

Design constraints (research/AETHERIS_RESEARCH_2026-08-21.md + retry_eval_ci.md):
  - No aggregate-score gate: at n=50 an aggregate gate cannot see <15.8 pp.
  - The exact McNemar test on discordant pairs needs two integers and
    math.comb — no scipy, no variance estimate, no correlation assumption.
  - Fork PRs get no secrets, so nothing in here needs an API key to gate.
"""
