"""Live capture runner for the golden set — feeds gates G6 (paired regression)
and G7 (judge noise floor), and the β (co-failure) measurement.

NON-BLOCKING by design: needs provider API keys, so it never runs as a
required check (fork PRs get no secrets). Intended for the scheduled evals
workflow and local runs with keys present.

What it writes — one JSONL row per item, already redacted:

    {"id", "cluster_id", "pass", "logician_pass", "creative_pass",
     "validation_score", "captured_at", "label"}

Rubric v1 (deterministic, zero judgement — the graded surface is structural
correctness, not answer quality):
  pass           — pipeline completed, winning answer non-empty, no
                   parse-failure markers in it.
  logician_pass /
  creative_pass  — agent output present, non-empty, no parse-failure markers.
                   These two feed evals.beta (the dual-agent decision).

Usage:
  python -m evals.capture --label baseline
  python -m evals.capture --label candidate --limit 20
  python -m evals.capture --label noise --reruns 3 --limit 20   # G7
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Side-effecting import, exactly like server.py/main.py: loads provider keys
# from the OS secret store BEFORE api_gateway reads them. Without this the
# capture silently runs in Simulation Mode and measures deterministic stubs
# (found the hard way 2026-08-22: the first "baseline" was byte-identical
# across different prompts).
import secrets_bootstrap  # noqa: F401  (side-effecting import)
from api_gateway.rate_limiter import AsyncAPIGateway, ProviderPool
from api_gateway.strategy import ProviderStrategy
from orchestrator.calienne_orchestrator import (
    create_request_passport,
    initialize_calienne_components,
)
from orchestrator.execution_replay import redact_pii

EVALS_DIR = Path(__file__).resolve().parent
RUNS_DIR = EVALS_DIR / "runs"
FAILURE_MARKERS = ("PARSE FAILURE", "ERROR:", "unparsable", "KNOWLEDGE ABSENCE")

# Hard cost ceiling: raises rather than continuing past this many provider
# calls in one capture (research Q5 cost control #4).
DEFAULT_MAX_CALLS = 600


def _looks_failed(text: str | None) -> bool:
    if not text or not str(text).strip():
        return True
    upper = str(text).upper()
    return any(marker in upper for marker in FAILURE_MARKERS)


def grade_item(result: dict) -> dict:
    """Deterministic rubric v1 — see module docstring."""
    answer = result.get("answer") or result.get("winning_answer")

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
    return {
        "pass": not aborted and result.get("status") != "failed" and not _looks_failed(answer),
        # Aborted rows keep their L/C grades (usually both False — the agents
        # never ran). β must exclude them: "agents never ran" is not
        # "both agents failed".
        "aborted": aborted,
        "logician_pass": not aborted and not _looks_failed(_agent_text(logician)),
        "creative_pass": not aborted and not _looks_failed(_agent_text(creative)),
    }


async def capture(
    items: list[dict],
    *,
    label: str,
    reruns: int = 1,
    limit: int | None = None,
    max_calls: int = DEFAULT_MAX_CALLS,
    mode: str = "HYBRID",
    pause_sec: float = 2.0,
) -> Path:
    """Run the live pipeline over golden items and write a redacted run file."""
    strategy = ProviderStrategy(mode=mode)
    pool = ProviderPool()
    gateway = AsyncAPIGateway()
    components = initialize_calienne_components()

    selected = items[: limit] if limit else items
    budget = len(selected) * reruns * 4  # breaker + 2 agents + judge per item
    if budget > max_calls:
        raise RuntimeError(
            f"capture budget {budget} provider calls exceeds --max-calls "
            f"{max_calls}; refusing to run (cost ceiling, research Q5)"
        )

    try:
        rows: list[dict] = []
        for rep in range(reruns):
            for item in selected:
                passport = create_request_passport()
                try:
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
                    graded = grade_item(payload)
                except Exception as exc:
                    # One exhausted provider chain must not kill the run —
                    # record the item as failed and keep capturing.
                    graded = {
                        "pass": False,
                        "aborted": False,
                        "logician_pass": False,
                        "creative_pass": False,
                    }
                    payload = {"error": f"{type(exc).__name__}: {exc}"[:200]}
                    print(f"[{label}] {item['id']} rep{rep}: FAILED — {payload['error']}", file=sys.stderr)
                rows.append(
                    {
                        "id": item["id"],
                        "rep": rep,
                        "cluster_id": item.get("cluster_id"),
                        "label": label,
                        **graded,
                        "validation_score": payload.get("validation_score"),
                        "captured_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                print(
                    f"[{label}] {item['id']} rep{rep}: "
                    f"pass={graded['pass']} "
                    f"L={graded['logician_pass']} C={graded['creative_pass']}",
                    file=sys.stderr,
                )
                if pause_sec > 0:
                    await asyncio.sleep(pause_sec)
    finally:
        await gateway.close()

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RUNS_DIR / f"{label}.jsonl"
    with open(out_path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
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
    parser.add_argument("--golden", default="v1", help="golden set version")
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
        help="permit a keyless (simulation-mode) run; rows are tagged label*=sim",
    )
    args = parser.parse_args(argv)

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

    out_path = asyncio.run(
        capture(
            items,
            label=args.label,
            reruns=args.reruns,
            limit=args.limit,
            max_calls=args.max_calls,
            mode=args.mode,
            pause_sec=args.pause_sec,
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
