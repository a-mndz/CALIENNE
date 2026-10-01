"""Live capture runner — feeds G6 (paired regression), G7 (noise floor),
β (co-failure), and the reference-check gate introduced with golden v2.

NON-BLOCKING by design: needs provider API keys, so it never runs as a
required check (fork PRs get no secrets). Intended for the scheduled evals
workflow and local runs with keys present.

What it writes — one JSONL row per item, already redacted:

    {"id", "rep", "cluster_id", "pass", "aborted", "logician_pass",
     "creative_pass", "validation_score", "checks_passed", "checks_total",
     "arm", "golden", "git_commit", "model_ids", "role_temperatures",
     "simulated", "captured_at", "label"}

Grading:
  liveness          — pipeline completed, winning answer non-empty, no
                      parse-failure markers.
  reference checks  — golden v2+ items carry expect.checks (deterministic,
                      see evals/checks.py). pass = liveness AND checks.
                      v1 items have no checks, so pass == liveness.
  logician_pass /
  creative_pass     — triad arm only; feed evals.beta (dual-agent decision).

Arms:
  triad   — the full breaker -> logician ∥ creative -> judge pipeline
            (4 provider calls per item).
  single  — one direct call on the generation chain, no pipeline. This is the
            baseline the triad must beat for the architecture to be justified.

Usage:
  python -m evals.capture --label baseline
  python -m evals.capture --label triad-v2 --golden v2
  python -m evals.capture --label single-v2 --golden v2 --arm single
  python -m evals.capture --label noise --reruns 3 --limit 20   # G7
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Side-effecting import, exactly like server.py/main.py: loads provider keys
# from the OS secret store BEFORE api_gateway reads them. Without this the
# capture silently runs in Simulation Mode and measures deterministic stubs
# (found the hard way 2026-08-22: the first "baseline" was byte-identical
# across different prompts).
import secrets_bootstrap  # noqa: F401  (side-effecting import)
from api_gateway.client import ROLE_TEMPERATURES
from api_gateway.rate_limiter import AsyncAPIGateway, ProviderPool
from api_gateway.strategy import ProviderStrategy
from evals.checks import checks_failed, evaluate_checks
from orchestrator.calienne_orchestrator import (
    create_request_passport,
    initialize_calienne_components,
)
from orchestrator.execution_replay import redact_pii

EVALS_DIR = Path(__file__).resolve().parent
RUNS_DIR = EVALS_DIR / "runs"
FAILURE_MARKERS = ("PARSE FAILURE", "ERROR:", "unparsable", "KNOWLEDGE ABSENCE")

# Provider calls per item, per arm (cost-ceiling arithmetic).
CALLS_PER_ITEM = {"triad": 4, "single": 1}

# Hard cost ceiling: raises rather than continuing past this many provider
# calls in one capture (research Q5 cost control #4).
DEFAULT_MAX_CALLS = 600


def _looks_failed(text: str | None) -> bool:
    if not text or not str(text).strip():
        return True
    upper = str(text).upper()
    return any(marker in upper for marker in FAILURE_MARKERS)


def grade_item(
    result: dict,
    expect: dict | None = None,
    answer_override: str | None = None,
) -> dict:
    """Deterministic grading — liveness always; reference checks when the
    golden item carries ``expect.checks`` (golden v2+)."""
    answer = answer_override or result.get("answer") or result.get("winning_answer")

    def _agent_text(agent: object) -> str | None:
        if agent is None:
            return None
        if isinstance(agent, dict):
            return agent.get("answer") or agent.get("final_answer")
        return getattr(agent, "answer", None)

    # The pipeline returns agents as top-level logician_output/creative_output
    # (AgentOutput objects); the server layer additionally nests them under
    # agent_outputs. Accept both shapes.
    logician = result.get("agent_outputs", {}).get("logician") if isinstance(
        result.get("agent_outputs"), dict
    ) else None
    logician = logician if logician is not None else result.get("logician_output")
    creative = result.get("agent_outputs", {}).get("creative") if isinstance(
        result.get("agent_outputs"), dict
    ) else None
    creative = creative if creative is not None else result.get("creative_output")

    aborted = result.get("status") == "aborted"
    liveness = not aborted and result.get("status") != "failed" and not _looks_failed(answer)

    checks = (expect or {}).get("checks") if isinstance(expect, dict) else None
    check_results = evaluate_checks(answer or "", checks) if checks else []
    failed_checks = checks_failed(check_results)
    graded_pass = liveness and not failed_checks

    return {
        "pass": graded_pass,
        # Aborted rows keep their L/C grades (usually both False — the agents
        # never ran). β must exclude them: "agents never ran" is not
        # "both agents failed".
        "aborted": aborted,
        "logician_pass": not aborted and not _looks_failed(_agent_text(logician)),
        "creative_pass": not aborted and not _looks_failed(_agent_text(creative)),
        "liveness_pass": liveness,
        "checks_passed": sum(1 for r in check_results if r["passed"]),
        "checks_total": len(check_results),
        "failed_check_details": [r["detail"] for r in failed_checks][:5],
    }


def _git_commit() -> str:
    """Best-effort HEAD sha for run provenance."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()[:12]
    except Exception:  # noqa: BLE001 — provenance must never break a run
        return "unknown"


async def _run_single_arm(
    item: dict,
    *,
    gateway: AsyncAPIGateway,
    strategy: ProviderStrategy,
    pool: ProviderPool,
    passport: object,
    timeout: float = 300.0,
) -> dict:
    """Single-model baseline: one direct call, no triad, no judge."""
    response = await asyncio.wait_for(
        gateway.execute_with_fallback(
            prompt=redact_pii(item["query"]),
            role="generation",
            strategy=strategy,
            pool=pool,
            system_prompt=None,
            history=None,
            passport=passport,
        ),
        timeout=timeout,
    )
    # Mirror the pipeline result shape so grade_item works unchanged: a
    # single-arm run "completes" iff the call returned non-empty text.
    return {"status": "completed", "answer": response}


async def capture(
    items: list[dict],
    *,
    label: str,
    arm: str = "triad",
    golden_version: str = "v1",
    reruns: int = 1,
    limit: int | None = None,
    max_calls: int = DEFAULT_MAX_CALLS,
    mode: str = "HYBRID",
    pause_sec: float = 2.0,
    simulated: bool = False,
    row_label: str | None = None,
) -> Path:
    """Run the live pipeline over golden items and write a redacted run file.

    ``label`` is the output filename stem; ``row_label`` (defaulting to
    ``label``) is what each row records — simulation runs append ``-sim``
    there, since ``*`` is not a legal filename character on Windows.
    """
    strategy = ProviderStrategy(mode=mode)
    pool = ProviderPool()
    gateway = AsyncAPIGateway()
    components = initialize_calienne_components() if arm == "triad" else {}
    row_label = row_label or label

    selected = items[: limit] if limit else items
    calls_per_item = CALLS_PER_ITEM.get(arm)
    if calls_per_item is None:
        raise ValueError(f"unknown arm {arm!r}")
    budget = len(selected) * reruns * calls_per_item
    if budget > max_calls:
        raise RuntimeError(
            f"capture budget {budget} provider calls exceeds --max-calls "
            f"{max_calls}; refusing to run (cost ceiling, research Q5)"
        )

    provenance = {
        "arm": arm,
        "golden": golden_version,
        "git_commit": _git_commit(),
        "model_ids": {
            role: strategy.get_model_chain(role)
            for role in ("breaker", "logician", "creative", "judge", "generation")
        },
        "role_temperatures": dict(ROLE_TEMPERATURES),
        "simulated": simulated,
        "mode": mode,
    }

    try:
        rows: list[dict] = []
        for rep in range(reruns):
            for item in selected:
                passport = create_request_passport()
                try:
                    if arm == "triad":
                        result = await asyncio.wait_for(
                            components["execution_manager"].execute(
                                user_query=redact_pii(item["query"]),
                                gateway=gateway,
                                strategy=strategy,
                                pool=pool,
                                passport=passport,
                                decision_engine=components.get("decision_engine"),
                                reasoning_graph=components.get("reasoning_graph"),
                                claim_manager=components.get("claim_manager"),
                                streaming_manager=None,
                                conversation_director=components.get("conversation_director"),
                                session_id=f"eval-{item['id']}-r{rep}",
                                user_id="eval-capture",
                            ),
                            timeout=900,
                        )
                        payload = dict(result) if isinstance(result, dict) else {}
                        graded = grade_item(payload, expect=item.get("expect"))
                    else:
                        result = await _run_single_arm(
                            item,
                            gateway=gateway,
                            strategy=strategy,
                            pool=pool,
                            passport=passport,
                        )
                        payload = dict(result) if isinstance(result, dict) else {}
                        graded = grade_item(
                            payload, expect=item.get("expect"), answer_override=result.get("answer")
                        )
                        graded.pop("logician_pass", None)
                        graded.pop("creative_pass", None)
                except Exception as exc:
                    # One exhausted provider chain must not kill the run —
                    # record the item as failed and keep capturing.
                    graded = {
                        "pass": False,
                        "aborted": False,
                        "liveness_pass": False,
                        "checks_passed": 0,
                        "checks_total": len((item.get("expect") or {}).get("checks") or []),
                        "failed_check_details": [],
                    }
                    if arm == "triad":
                        graded["logician_pass"] = False
                        graded["creative_pass"] = False
                    payload = {"error": f"{type(exc).__name__}: {exc}"[:200]}
                    print(f"[{label}] {item['id']} rep{rep}: FAILED — {payload['error']}", file=sys.stderr)
                rows.append(
                    {
                        "id": item["id"],
                        "rep": rep,
                        "cluster_id": item.get("cluster_id"),
                        "label": row_label,
                        **provenance,
                        **graded,
                        "validation_score": payload.get("validation_score"),
                        "captured_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                lc = (
                    f" L={graded.get('logician_pass')} C={graded.get('creative_pass')}"
                    if arm == "triad"
                    else ""
                )
                print(
                    f"[{label}] {item['id']} rep{rep}: "
                    f"pass={graded['pass']}"
                    f" ({graded.get('checks_passed', 0)}/{graded.get('checks_total', 0)} checks)"
                    f"{lc}",
                    file=sys.stderr,
                )
                if pause_sec > 0:
                    await asyncio.sleep(pause_sec)
    finally:
        await gateway.close()

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = (RUNS_DIR / f"{label}.jsonl").resolve()
    runs_root = RUNS_DIR.resolve()
    if not out_path.is_relative_to(runs_root):
        raise ValueError(f"run output path escaped runs directory: {out_path}")
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    out_path.write_text(payload, encoding="utf-8")
    return out_path


def noise_floor(rows: list[dict]) -> float:
    """G7: fraction of items whose verdict is not identical across all reps."""
    by_item: dict[str, set[bool]] = {}
    for row in rows:
        by_item.setdefault(row["id"], set()).add(bool(row["pass"]))
    if not by_item:
        return 0.0
    unstable = sum(1 for verdicts in by_item.values() if len(verdicts) > 1)
    return unstable / len(by_item)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="run label / output filename stem")
    parser.add_argument("--golden", default="v1", help="golden set version (v1, v2, gsm8k_v1)")
    parser.add_argument(
        "--arm",
        default="triad",
        choices=sorted(CALLS_PER_ITEM),
        help="triad = full pipeline (4 calls/item); single = one direct call (baseline)",
    )
    parser.add_argument("--limit", type=int, default=None, help="first N items only")
    parser.add_argument("--reruns", type=int, default=1, help="repetitions per item (G7: >=2)")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    parser.add_argument("--mode", default="HYBRID", choices=["FREE", "HYBRID", "PAID"])
    parser.add_argument(
        "--pause-sec",
        type=float,
        default=2.0,
        help="delay between items (provider RPM headroom; 0 disables)",
    )
    parser.add_argument(
        "--allow-simulation",
        action="store_true",
        help="permit a keyless (simulation-mode) run; row labels get a -sim suffix",
    )
    args = parser.parse_args(argv)

    # The label becomes a filename under evals/runs/ — restrict it to a safe
    # stem so it cannot escape the directory or smuggle separators.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.label) or ".." in args.label:
        print(
            f"error: invalid --label {args.label!r}: use letters, digits, dot, dash, underscore",
            file=sys.stderr,
        )
        return 2

    import os

    live_keys = [
        name
        for name in os.environ
        if name.startswith("CALIENNE_")
        and name.endswith(("_API_KEY", "_TOKEN"))
        and os.environ[name].strip()
    ]
    if not live_keys and not args.allow_simulation:
        print(
            "refusing to run: no provider keys present — this would measure "
            "simulation stubs, not models. Load keys (secrets_bootstrap/keyring) "
            "or pass --allow-simulation for a stub run.",
            file=sys.stderr,
        )
        return 3
    if not live_keys:
        print("WARNING: simulation-mode run (no provider keys).", file=sys.stderr)

    from evals.validate import load_golden

    items, meta = load_golden(args.golden)
    if meta["errors"]:
        print("refusing to capture against an invalid golden set:", file=sys.stderr)
        for error in meta["errors"]:
            print(f"  - {error}", file=sys.stderr)
        return 2

    row_label = args.label if live_keys else f"{args.label}-sim"

    out_path = asyncio.run(
        capture(
            items,
            label=args.label,
            arm=args.arm,
            golden_version=args.golden,
            reruns=args.reruns,
            limit=args.limit,
            max_calls=args.max_calls,
            mode=args.mode,
            pause_sec=args.pause_sec,
            simulated=not live_keys,
            row_label=row_label,
        )
    )
    rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.reruns > 1:
        print(f"G7 noise floor (verdict flip rate across {args.reruns} reps): "
              f"{noise_floor(rows):.4f}")
    print(f"wrote {len(rows)} rows -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
