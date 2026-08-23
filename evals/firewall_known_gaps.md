# Firewall known gaps — measured 2026-08-22 (Stage 3 corpus build)

> **v2 UPDATE (2026-08-22, Stage 4):** `score_support` landed in
> `orchestrator/claims.py` — support is now a measured 0-1 stemmed-coverage
> score, and `validate_claim` requires coverage ≥ 0.7 (or verbatim substring
> containment) before evidence can verify/contradict a claim. Result, measured
> against this exact table: **12 of the 14 rows below are now correctly
> unverified**; the frozen corpus grew to 66 rows and gate G3 stays green.
> The two RESIDUAL rows are marked inline — they need semantic matching
> (verb-antonym and completion-vs-removal distinctions), which is the
> acceptance case for a hosted verifier / HHEM-class model, not for more
> lexical rules.

Rows below were authored for `firewall_corpus.jsonl` but **excluded from the frozen
corpus** because the matcher's verdict disagrees with ground truth. They are the
quantified blind spots that justify firewall v2 (remediation plan Stage 4).
Each row: claim | evidence | ground truth | matcher verdict.

## Gap class A — false VERIFIED on co-occurring keywords (11 rows)

The matcher counts keyword overlap and number-subset; it has no notion of semantic
role. Any claim sharing 2+ content words with evidence is "verified" even when the
evidence says nothing about the claim's subject.

| Claim | Evidence (abridged) | Truth | Matcher |
|---|---|---|---|
| Revenue doubled in the third quarter. | hired 40 engineers, opened two offices in Q3 | unverified | **verified** |
| The model supports 200k token context windows. | released with a 128k context window | unverified (number mismatch) | **verified** |
| All users preferred the new interface. | redesign shipped to 5% of users | unverified | **verified** |
| Training completed in three days. | ran for two days on eight GPUs | unverified | **verified** |
| The contract was signed by both parties in March. | legal review began in March | unverified | **verified** |
| The feature flag was removed in version 9. | rollout completed in version 9 | unverified | **verified** — RESIDUAL under v2 (score 0.75) |
| The team doubled in size this year. | three requisitions opened | unverified | **verified** |
| Churn dropped after the pricing change. | pricing change launched in one region | unverified | **verified** |
| The migration is reversible. | migration adds one column with a default | unverified | **verified** |
| The new model is cheaper to serve. | requires fewer GPUs per replica | unverified | **verified** |
| Compliance review is complete. | scheduled after the security audit | unverified | **verified** |

## Gap class B — false VERIFIED on verb antonyms (3 rows)

Antonymy is invisible to keyword overlap and to the negation-word parity check.

| Claim | Evidence (abridged) | Truth | Matcher |
|---|---|---|---|
| Feature rollouts bypass the flag system. | rollouts go through the flag system | contradicted | **verified** — RESIDUAL under v2 (score 0.80) |
| The audit log is writable by the application service account. | append-only, writable solely by the audit collector | contradicted | **verified** |
| The design system includes dark mode. | documents typography, spacing, color tokens | unverified | **verified** |

## Gap class C — spurious CONTRADICTED from incidental negation (2 rows, fixed by rewording evidence)

A negation word anywhere in the evidence sentence flips parity even when it does
not scope over the matched content. Encountered during corpus generation
("stored in the evals directory, **not** the replay store" → verified claim read as
contradicted); the frozen corpus avoids the pattern rather than fixing the matcher.

## Consequence for gates

- G3 (frozen corpus, 56 rows) pins only verdicts where matcher and ground truth
  agree — a change making any of them flip is a real regression.
- The 14 rows above were the acceptance targets for firewall v2's `score_support`
  interface: v2 resolved 12/14 without regressing the frozen corpus (now 66
  rows). The 2 residuals define the remaining acceptance case for a semantic
  verifier (Stage 4+).
