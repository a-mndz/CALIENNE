"""One-command experiment runner: triad vs single-model vs noise floor.

This is the experiment the repo's own decision rule (evals/README) requires
and which had never been executed twice as of 2026-10-01.

Runs, in order, with a pre-flight validate:
  1. triad pipeline   on golden v2        (4 calls/item)
  2. single baseline  on golden v2        (1 call/item)
  3. triad pipeline   on gsm8k_v1         (external validity)
  4. single baseline  on gsm8k_v1
  5. noise floor:     triad v2 --reruns 3 (variance; G7)

Then prints the comparison commands (mcnemar / beta / report). Steps run
in-process (no subprocess), so there is no shell surface at all.

Usage:
  python -m evals.run_experiment --label-prefix exp1 [--limit 10] [--max-calls 600]
  python -m evals.run_experiment --dry-run     # print the plan, run nothing

Cost note: --limit 10 with the default 600-call ceiling is a sane smoke.
Full runs are 50 items x (4+1) calls x 2 sets + noise floor ~= 550 calls.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

STEPS = [
    # (label, golden, arm, reruns)
    ("{prefix}-triad-v2", "v2", "triad", 1),
    ("{prefix}-single-v2", "v2", "single", 1),
    ("{prefix}-triad-gsm", "gsm8k_v1", "triad", 1),
    ("{prefix}-single-gsm", "gsm8k_v1", "single", 1),
    ("{prefix}-noise-v2", "v2", "triad", 3),
]

VALID_LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _live_keys() -> list[str]:
    return [
        name
        for name in os.environ
        if name.startswith("CALIENNE_")
        and name.endswith(("_API_KEY", "_TOKEN"))
        and os.environ[name].strip()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label-prefix", default="exp1")
    parser.add_argument("--limit", type=int, default=None, help="first N items (smoke runs)")
    parser.add_argument("--max-calls", type=int, default=600)
    parser.add_argument("--pause-sec", type=float, default=2.0)
    parser.add_argument(
        "--allow-simulation", action="store_true", help="permit a keyless stub run"
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    args = parser.parse_args(argv)

    prefix = args.label_prefix
    if not VALID_LABEL_RE.fullmatch(prefix):
        print(
            f"error: invalid --label-prefix {prefix!r}: use letters, digits, dot, dash",
            file=sys.stderr,
        )
        return 2
    if not _live_keys() and not args.allow_simulation:
        print(
            "refusing to run: no provider keys present (this would measure stubs). "
            "Load keys via secrets_bootstrap/keyring or pass --allow-simulation.",
            file=sys.stderr,
        )
        return 3

    print("pre-flight: validating golden sets...")
    from evals.validate import main as validate_main

    validate_rc = validate_main([])
    if validate_rc != 0:
        return validate_rc

    from evals.capture import main as capture_main

    for label_tpl, golden, arm, reruns in STEPS:
        label = label_tpl.format(prefix=prefix)
        step_argv = [
            "--label", label,
            "--golden", golden,
            "--arm", arm,
            "--reruns", str(reruns),
            "--max-calls", str(args.max_calls),
            "--pause-sec", str(args.pause_sec),
        ]
        if args.limit:
            step_argv += ["--limit", str(args.limit)]
        print(f"\n=== step: {label} (golden={golden}, arm={arm}, reruns={reruns}) ===")
        if args.dry_run:
            continue
        rc = capture_main(step_argv)
        if rc != 0:
            print(
                f"error: step {label} exited {rc} — stopping. "
                "Fix the failing arm before comparing.",
                file=sys.stderr,
            )
            return rc

    p = prefix
    print(
        f"""
 done. Compare with:

  python -m evals.report evals/runs/{p}-triad-v2.jsonl evals/runs/{p}-single-v2.jsonl \\
                      evals/runs/{p}-triad-gsm.jsonl evals/runs/{p}-single-gsm.jsonl
  python -m evals.mcnemar evals/runs/{p}-single-v2.jsonl evals/runs/{p}-triad-v2.jsonl
  python -m evals.mcnemar evals/runs/{p}-single-gsm.jsonl evals/runs/{p}-triad-gsm.jsonl
  python -m evals.beta evals/runs/{p}-triad-v2.jsonl

 Decision rule (evals/README): if the triad does not significantly beat the
 single-model baseline, the dual-agent architecture is not earning its cost.
 Report the result either way — that IS the research.
"""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
