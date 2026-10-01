# The Attic — Quarantined Modules (2026-10-01)

These modules were removed from the live tree because **nothing in the
production execution path can reach them**. They were imported only by their
own tests, yet were advertised as features (in the README and in their own
docstrings). That gap between advertisement and reachability is exactly what
this quarantine fixes.

Rule going forward: **a module is either wired into the live pipeline or it
does not ship.** Revive a module only together with the wiring and the eval
evidence that it earns its cost.

## What is here (physically)

| File | Was | Why quarantined |
|---|---|---|
| `mcts.py` | `orchestrator/mcts.py` | Tree-of-Thoughts/MCTS "guided by PRMs". Never called by any pipeline path. The "PRM" is keyword matching (+0.20 for containing "therefore"); expansion always simulates only the first child — not a real search. |
| `embeddings.py` | `orchestrator/embeddings.py` | "Dense semantic embeddings". `fastembed` was never in requirements, so every real environment silently fell back to an MD5/SHA-1 feature hash — lexical, not semantic. |

Paired tests for these two live in `attic/tests/` (not collected by pytest:
`pytest.ini` pins `testpaths = tests`). Their imports reference the original
module paths and will need adjustment if revived.

## What is in git history only

These were blocked from physical relocation (content scanner) and are
recoverable via git:

| Was | Recover with | Why quarantined |
|---|---|---|
| `core/tools.py` | `git log --diff-filter=D -- core/tools.py` then `git show <sha>:core/tools.py` | PythonREPLTool / WebSearchTool / ToolRegistry. No agent can call a tool (no tool-call handling in the client or runner). The AST sandbox guard is bypassable via builtin aliasing, and the subprocess inherited every provider API key from the environment. |
| `core/chunking.py` | same pattern | DocumentChunker — RAG preprocessing for a RAG backend that does not exist (default retrieval provider returns `[]`). |
| `evals/rubric.py` | same pattern | "Calibrated LLM-as-a-Judge" rubric that was actually regex string-matching ("soundness = 4.8 if the text contains 'therefore'"). Never invoked by the eval harness. |

## Revival checklist (per module)

1. Wire it into the live execution path (grep for importers first — if none
   can be named, stop here).
2. Fix the known defects listed above.
3. Add a behavioral test that fails when the module is disconnected.
4. Run the golden eval (see `evals/EXPERIMENT.md`) and show the module
   improves the measured metric — not just that it runs.
