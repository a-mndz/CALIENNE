"""
calienne — Adaptive Multi-Model Reasoning Orchestrator
Main entry point: async CLI REPL.

Initialises the infrastructure layer (ProviderPool, ProviderStrategy,
AsyncAPIGateway) in HYBRID mode and runs an interactive loop that feeds
user queries through the micro-mode pipeline, pretty-printing the
structured output to the console.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import textwrap
from typing import Any

# CRIT-007: load provider API keys from the OS secret store BEFORE
# anything that transitively imports ``core.config`` (which validates
# the keys at construction time).  This module is a no-op if the
# keyring is empty or unavailable, in which case ``calienneConfig``
# falls through to Simulation Mode.
import secrets_bootstrap  # noqa: F401  (side-effecting import)
from api_gateway import AllModelsExhaustedError, AsyncAPIGateway, ProviderPool, ProviderStrategy
from api_gateway.rate_limiter import extract_provider_key
from core.config import configure_logging, get_settings
from core.passport import ExecutionPassport
from orchestrator.calienne_orchestrator import (
    create_request_passport,
    initialize_calienne_components,
)
from telemetry.observer import observer

# ── Logging ──────────────────────────────────────────────────────────────

logger = logging.getLogger("calienne")

# ── ANSI colours (for pretty-printing) ───────────────────────────────────

_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_MAGENTA = "\033[35m"
_RESET = "\033[0m"

# ── Timeout for a single pipeline run (seconds) ─────────────────────────
_PIPELINE_TIMEOUT_SEC = 120


# ── Provider Registration ───────────────────────────────────────────────


def _bootstrap_provider_pool(strategy: ProviderStrategy) -> ProviderPool:
    """
    Create a :class:`ProviderPool` and register every model referenced
    by *strategy* so that health tracking works from the first call.
    """
    pool = ProviderPool()

    # Collect {model: [roles]} from the strategy's supported roles.
    model_roles: dict[str, set[str]] = {}
    for role in strategy.supported_roles:
        for model in strategy.get_model_chain(role):
            model_roles.setdefault(model, set()).add(role)

    # Register each model's provider
    for model, roles in model_roles.items():
        provider_name = extract_provider_key(model)
        pool.register_provider(provider_name, roles=sorted(roles))

    logger.info(
        "ProviderPool bootstrapped with %d providers.", len(pool.get_all_statuses()),
    )
    return pool


# ── Pretty Printer ──────────────────────────────────────────────────────


def _pretty_print_result(result: dict[str, Any]) -> None:
    """Render a :class:`MicroModeResult` dict to the console."""

    status = result.get("status", "unknown")

    # ── Status banner ────────────────────────────────────────────────
    status_colours = {
        "success": _GREEN,
        "aborted": _YELLOW,
        "error": _RED,
    }
    colour = status_colours.get(status, _DIM)
    print(
        f"\n{_BOLD}{'═' * 72}{_RESET}\n"
        f"  {_BOLD}calienne Micro-Mode Result{_RESET}   "
        f"[{colour}{status.upper()}{_RESET}]\n"
        f"{_BOLD}{'═' * 72}{_RESET}"
    )

    # ── Winning answer ───────────────────────────────────────────────
    answer = result.get("winning_answer", "—")
    print(f"\n  {_CYAN}{_BOLD}▸ Answer{_RESET}")
    for line in textwrap.wrap(answer, width=68):
        print(f"    {line}")

    # ── Scores ───────────────────────────────────────────────────────
    score = result.get("validation_score", 0.0)
    diversity = result.get("confidence_delta", 0.0)
    print(
        f"\n  {_MAGENTA}{_BOLD}▸ Validation Score:{_RESET}  {score:.2f}/10"
        f"     {_MAGENTA}{_BOLD}Diversity:{_RESET}  {diversity:.2f}"
    )

    # ── Judge decision ───────────────────────────────────────────────
    decision = result.get("judge_decision")
    if decision:
        print(f"\n  {_YELLOW}{_BOLD}▸ Judge Decision{_RESET}")
        print(f"    Verdict  : {decision.get('verdict', '—')}")
        print(f"    Score A  : {decision.get('score_a', '—')}")
        print(f"    Score B  : {decision.get('score_b', '—')}")
        rationale = decision.get("justification", "")
        if rationale:
            print("    Rationale:")
            for line in textwrap.wrap(rationale, width=64):
                print(f"      {line}")

    # ── Agent outputs (condensed) ────────────────────────────────────
    for label, key in [("Logician", "logician_output"), ("Creative", "creative_output")]:
        output = result.get(key)
        if output is None:
            continue
        print(f"\n  {_GREEN}{_BOLD}▸ {label} Agent{_RESET}")
        if hasattr(output, "answer"):
            # AgentOutput Pydantic model
            print(f"    Answer     : {_trim(output.answer, 120)}")
            print(f"    Confidence : {output.confidence:.2f}")
            steps = output.reasoning_steps
        elif isinstance(output, dict):
            print(f"    Answer     : {_trim(output.get('answer', '—'), 120)}")
            print(f"    Confidence : {output.get('confidence', '—')}")
            steps = output.get("reasoning_steps", [])
        else:
            continue
        if steps:
            print(f"    Reasoning  : ({len(steps)} step{'s' if len(steps) != 1 else ''})")
            for i, step in enumerate(steps[:3], 1):
                print(f"      {i}. {_trim(step, 80)}")
            if len(steps) > 3:
                print(f"      … and {len(steps) - 3} more steps")

    print(f"\n{_BOLD}{'─' * 72}{_RESET}\n")

    # ── Passport metadata (if available) ──────────────────────────────
    passport_data = result.get("_passport")
    if passport_data:
        sec = passport_data.get("security_metadata", {})
        print(
            f"  {_DIM}request_id: {passport_data.get('request_id', '—')}{_RESET}\n"
            f"  {_DIM}injection_attempts: {sec.get('injection_attempts', 0)}"
            f"  validation_failures: {len(sec.get('validation_failures', []))}{_RESET}\n"
        )


def _trim(text: str, max_len: int) -> str:
    """Truncate *text* with an ellipsis if it exceeds *max_len*."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


# ── Main Loop ───────────────────────────────────────────────────────────


async def main() -> None:
    """Async entry point — configure logging, build infra, run REPL."""

    # ── Settings & logging ───────────────────────────────────────────
    settings = get_settings()
    configure_logging(settings)
    logger.info("calienne starting up …")

    # ── Infrastructure ───────────────────────────────────────────────
    strategy = ProviderStrategy(mode="HYBRID")
    pool = _bootstrap_provider_pool(strategy)
    gateway = AsyncAPIGateway()

    # ── CALIENNE Components ────────────────────────────────────────────
    calienne = initialize_calienne_components()

    logger.info(
        "Infrastructure ready — strategy=%s, providers=%d, gateway=OK, calienne=%s.",
        strategy.mode.value,
        len(pool.get_all_statuses()),
        ", ".join(sorted(calienne.keys())),
    )

    # ── CLI banner ───────────────────────────────────────────────────
    print(
        f"\n{_BOLD}{_CYAN}"
        "    ╔═══════════════════════════════════════════════════╗\n"
        "    ║  calienne — Adaptive Multi-Model Reasoning Orchestrator  ║\n"
        "    ║  Mode: HYBRID  │  Pipeline: Micro-Mode           ║\n"
        "    ╚═══════════════════════════════════════════════════╝"
        f"{_RESET}\n"
    )
    print(f"  {_DIM}Type a question and press Enter.  Ctrl+C to quit.{_RESET}\n")

    # ── REPL ─────────────────────────────────────────────────────────
    try:
        while True:
            try:
                user_input = input(f"  {_BOLD}calienne ▶{_RESET} ").strip()
            except (KeyboardInterrupt, EOFError):
                print(f"\n  {_DIM}Goodbye.{_RESET}\n")
                break

            if not user_input:
                continue

            # Built-in meta-commands
            if user_input.lower() in {"exit", "quit", ":q"}:
                print(f"\n  {_DIM}Goodbye.{_RESET}\n")
                break

            if user_input.lower() in {"status", ":s"}:
                _print_pool_status(pool)
                observer.print_session_report()
                continue

            # ── Pipeline execution ───────────────────────────────────────
            try:
                # Create an ExecutionPassport for this request
                passport = create_request_passport()

                # Generate session_id for conversation tracking
                import uuid
                session_id = str(uuid.uuid4())

                result = await asyncio.wait_for(
                    calienne["execution_manager"].execute(
                        user_query=user_input,
                        gateway=gateway,
                        strategy=strategy,
                        pool=pool,
                        passport=passport,
                        decision_engine=calienne["decision_engine"],
                        reasoning_graph=calienne["reasoning_graph"],
                        claim_manager=calienne["claim_manager"],
                        streaming_manager=calienne["streaming_manager"],
                        conversation_director=calienne["conversation_director"],
                        session_id=session_id,
                    ),
                    timeout=_PIPELINE_TIMEOUT_SEC,
                )

                # Log final passport state (3 retries with 1s delay)
                passport.log_final_state()

                # Attach passport metadata to result for display
                result["_passport"] = passport.to_dict()

                _pretty_print_result(result)

            except asyncio.TimeoutError:
                print(
                    f"\n  {_RED}{_BOLD}⏱  Pipeline timed out{_RESET} "
                    f"(>{_PIPELINE_TIMEOUT_SEC}s).  Try a simpler query or "
                    f"check provider health with {_BOLD}status{_RESET}.\n"
                )
                logger.error(
                    "Pipeline timed out after %ds for query: %.120s",
                    _PIPELINE_TIMEOUT_SEC,
                    user_input,
                )

            except AllModelsExhaustedError as exc:
                print(
                    f"\n  {_RED}{_BOLD}✖  All models exhausted for role "
                    f"'{exc.role}'.{_RESET}\n"
                    f"  {_DIM}{exc}{_RESET}\n"
                )
                logger.error("AllModelsExhaustedError: %s", exc)

            except KeyboardInterrupt:
                print(f"\n  {_YELLOW}Pipeline interrupted.{_RESET}\n")
                continue

            except Exception as exc:  # noqa: BLE001
                print(
                    f"\n  {_RED}{_BOLD}✖  Unexpected error:{_RESET} "
                    f"{type(exc).__name__}: {exc}\n"
                )
                logger.exception("Unhandled exception during pipeline run.")
    finally:
        # Clean up HTTPX client resources
        await gateway.close()
        # Log final stats summary
        observer.print_session_report()


# ── Pool Status Helper ──────────────────────────────────────────────────


def _print_pool_status(pool: ProviderPool) -> None:
    """Dump current provider health to the console."""
    statuses = pool.get_all_statuses()
    if not statuses:
        print(f"  {_DIM}No providers registered.{_RESET}\n")
        return

    print(f"\n  {_BOLD}Provider Health{_RESET}")
    print(f"  {'─' * 60}")
    for s in statuses:
        if s is None:
            continue
        status_colour = {
            "healthy": _GREEN,
            "degraded": _YELLOW,
            "dead": _RED,
        }.get(s["status"], _DIM)
        print(
            f"  {s['provider']:<50} "
            f"[{status_colour}{s['status'].upper()}{_RESET}]  "
            f"errors={s['error_count']}"
        )
    print()


# ── Synchronous entry point ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="calienne — Adaptive Multi-Model Reasoning Orchestrator")
    parser.add_argument("--web", action="store_true", help="Launch web UI instead of terminal REPL")
    parser.add_argument("--port", type=int, default=8000, help="Port for web server (default: 8000)")
    parser.add_argument("--host", default="127.0.0.1", help="Host for web server (default: 127.0.0.1)")
    args = parser.parse_args()

    if args.web:
        import uvicorn

        from server import app
        print(
            f"\n{_BOLD}{_CYAN}"
            "    calienne Web UI starting...\n"
            f"    Open  http://{args.host}:{args.port}  in your browser."
            f"{_RESET}\n"
        )
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print(f"\n{_DIM}Interrupted — shutting down.{_RESET}")
            sys.exit(130)
