"""
Shared prompt assembly utilities for AETHERIS agents.

Centralizes common prompt assembly patterns to eliminate duplicate code
across orchestrator/pipelines.py, orchestrator/decisions.py, and
orchestrator/evaluation.py.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from agents.prompt_manager import assemble_agent_prompt

logger = logging.getLogger(__name__)


# ── Agent prompt configurations ──────────────────────────────────────

_BREAKER_CONFIG = {
    "role": "Breaker",
    "pipeline_stage": "Pre-Filter",
    "objective": "Knowledge Absence Detection",
    "system_prompt_filename": "04_breaker.xml",
}

_LOGICIAN_CONFIG = {
    "role": "Logician",
    "pipeline_stage": "Generation",
    "objective": "Logical Validation",
    "system_prompt_filename": "05_logician.xml",
}

_CREATIVE_CONFIG = {
    "role": "Creative",
    "pipeline_stage": "Generation",
    "objective": "Creative Expansion",
    "system_prompt_filename": "06_creative.xml",
}

_SYNTHESIZER_CONFIG = {
    "role": "Reasoning Fusion Engine",
    "pipeline_stage": "Synthesis",
    "objective": "Consensus and Synthesis Arbitration",
    "system_prompt_filename": "09_synthesizer.xml",
}


# ── Single-agent prompt assembly ─────────────────────────────────────

def assemble_breaker_prompt(
    execution_mode: str,
    iteration: int = 1,
    prompts_dir: Optional[str] = None,
) -> str:
    """Assemble the Breaker agent system prompt.

    Args:
        execution_mode: Current pipeline execution mode.
        iteration: Current iteration number (default 1).
        prompts_dir: Optional overrides for prompt file location.

    Returns:
        Assembled XML prompt string.
    """
    return assemble_agent_prompt(
        **_BREAKER_CONFIG,
        iteration=iteration,
        execution_mode=execution_mode,
        prompts_dir=prompts_dir,
    )


def assemble_logician_prompt(
    execution_mode: str,
    iteration: int = 1,
    prompts_dir: Optional[str] = None,
) -> str:
    """Assemble the Logician agent system prompt.

    Args:
        execution_mode: Current pipeline execution mode.
        iteration: Current iteration number (default 1).
        prompts_dir: Optional overrides for prompt file location.

    Returns:
        Assembled XML prompt string.
    """
    return assemble_agent_prompt(
        **_LOGICIAN_CONFIG,
        iteration=iteration,
        execution_mode=execution_mode,
        prompts_dir=prompts_dir,
    )


def assemble_creative_prompt(
    execution_mode: str,
    iteration: int = 1,
    prompts_dir: Optional[str] = None,
) -> str:
    """Assemble the Creative agent system prompt.

    Args:
        execution_mode: Current pipeline execution mode.
        iteration: Current iteration number (default 1).
        prompts_dir: Optional overrides for prompt file location.

    Returns:
        Assembled XML prompt string.
    """
    return assemble_agent_prompt(
        **_CREATIVE_CONFIG,
        iteration=iteration,
        execution_mode=execution_mode,
        prompts_dir=prompts_dir,
    )


def assemble_synthesizer_prompt(
    execution_mode: str,
    iteration: int = 1,
    prompts_dir: Optional[str] = None,
) -> str:
    """Assemble the Synthesizer (Judge) agent system prompt.

    Args:
        execution_mode: Current pipeline execution mode.
        iteration: Current iteration number (default 1).
        prompts_dir: Optional overrides for prompt file location.

    Returns:
        Assembled XML prompt string.
    """
    return assemble_agent_prompt(
        **_SYNTHESIZER_CONFIG,
        iteration=iteration,
        execution_mode=execution_mode,
        prompts_dir=prompts_dir,
    )


# ── Multi-agent prompt assembly (eliminates repeated triples) ────────

def assemble_generation_prompts(
    execution_mode: str,
    iteration: int = 1,
    prompts_dir: Optional[str] = None,
) -> dict[str, str]:
    """Assemble system prompts for Breaker, Logician, and Creative agents.

    This replaces the repeated triple-assemble pattern that appeared
    in pipelines.py (lines 139-162 and 537-560).

    Args:
        execution_mode: Current pipeline execution mode.
        iteration: Current iteration number (default 1).
        prompts_dir: Optional overrides for prompt file location.

    Returns:
        Dict with keys 'breaker', 'logician', 'creative' mapping to
        assembled prompt strings.
    """
    return {
        "breaker": assemble_breaker_prompt(execution_mode, iteration, prompts_dir),
        "logician": assemble_logician_prompt(execution_mode, iteration, prompts_dir),
        "creative": assemble_creative_prompt(execution_mode, iteration, prompts_dir),
    }


# ── History formatting ───────────────────────────────────────────────

def format_message_history(
    history: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    """Format conversation history for LLM gateway calls.

    Ensures consistent message structure across all callers. Each entry
    must contain 'role' and 'content' keys.

    Args:
        history: Raw conversation history from ConversationDirector or
                 other sources. May be None.

    Returns:
        List of message dicts with 'role' and 'content' keys.
        Returns empty list if history is None or empty.
    """
    if not history:
        return []

    formatted: list[dict[str, str]] = []
    for turn in history:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role and content:
            formatted.append({"role": str(role), "content": str(content)})
    return formatted


# ── Conversation context initialization ──────────────────────────────

def init_conversation_context(
    conversation_director: Any,
    session_id: str | None,
    logger_instance: Any = None,
    owner_email: str | None = None,
) -> tuple[list[dict[str, str]] | None, dict[str, Any] | None]:
    """Initialize conversation context for a pipeline run.

    Replaces the duplicate conversation initialization block found in
    pipelines.py (lines 91-114 and 896-919).

    Args:
        conversation_director: ConversationDirector instance (or None).
        session_id: Session identifier or None.
        logger_instance: Optional logger to use (defaults to module logger).
        owner_email: Authenticated user's email. Passed to session
            auto-creation so pipeline-created sessions are owned (HIGH-015);
            unowned sessions defeat per-principal memory scoping.

    Returns:
        Tuple of (history, conversation_metadata).
        - history: Conversation history list or None if no session.
        - conversation_metadata: Session metadata dict or None.
    """
    log = logger_instance or logger

    if conversation_director is None or not session_id:
        return None, None

    try:
        from orchestrator.conversation import ConversationState

        session = conversation_director.get_session(session_id)
        if session is None:
            if owner_email:
                conversation_director.create_session(session_id, owner_email=owner_email)
            else:
                # Duck-typed directors may not accept the owner kwarg; the
                # unowned legacy path stays available (logged below).
                conversation_director.create_session(session_id)
            log.info(
                "Created new conversation session: %s (owner=%s)",
                session_id,
                owner_email or "<legacy>",
            )

        history = conversation_director.get_history(session_id)

        if conversation_director.should_truncate(session_id):
            summary = conversation_director.truncate_history(session_id)
            if summary:
                log.info("Truncated conversation history: %s", summary[:100])

        metadata = conversation_director.get_metadata(session_id)
        return history, metadata

    except Exception as exc:
        log.warning("Conversation context error: %s", exc)
        return None, None


def record_user_query(
    conversation_director: Any,
    session_id: str | None,
    user_query: str | None,
    logger_instance: Any = None,
) -> None:
    """Append the user query to conversation history (MED-015 fix).

    Idempotent — calling with the same query twice still records both turns
    because the caller's intent is unambiguous.  Failures are logged at
    ``debug`` level so a transient director glitch never aborts the pipeline.
    """
    log = logger_instance or logger
    if conversation_director is None or not session_id or not user_query:
        return
    try:
        token_count = len(user_query) // 4
        conversation_director.add_turn(session_id, "user", user_query, token_count)
    except Exception as exc:
        log.debug("Failed to record user query in session %s: %s", session_id, exc)


def complete_conversation_session(
    conversation_director: Any,
    session_id: str | None,
    final_answer: str,
    pipeline_status: str,
    logger_instance: Any = None,
) -> dict[str, Any] | None:
    """Complete a conversation session after pipeline finishes.

    Replaces the duplicate conversation completion block found in
    pipelines.py (lines 468-484 and 1231-1249).

    Args:
        conversation_director: ConversationDirector instance (or None).
        session_id: Session identifier (or None).
        final_answer: The final answer text to record.
        pipeline_status: Pipeline outcome ('completed' or 'failed').
        logger_instance: Optional logger to use (defaults to module logger).

    Returns:
        Updated conversation metadata dict, or None on error.
    """
    log = logger_instance or logger

    if conversation_director is None or not session_id:
        return None

    try:
        from orchestrator.conversation import ConversationState

        token_count = len(final_answer) // 4
        conversation_director.add_turn(
            session_id, "assistant", final_answer, token_count
        )

        if pipeline_status == "completed":
            conversation_director.transition_state(
                session_id, ConversationState.COMPLETED
            )
        else:
            conversation_director.transition_state(
                session_id, ConversationState.FAILED
            )

        return conversation_director.get_metadata(session_id)

    except Exception as exc:
        log.warning("Conversation completion error: %s", exc)
        return None


# ── Decision dict assembly ───────────────────────────────────────────

def build_decision_dict(
    logician_confidence: float,
    creative_confidence: float,
    overall_confidence: str,
    overall_bias_risk: str,
    disagreement_notes: list[str],
) -> dict[str, Any]:
    """Build the judge decision dictionary.

    Replaces the duplicate decision_dict assembly found in
    pipelines.py (lines 402-411, 775-784, 1165-1174).

    Args:
        logician_confidence: Logician agent confidence (0.0-1.0).
        creative_confidence: Creative agent confidence (0.0-1.0).
        overall_confidence: Human-readable confidence label.
        overall_bias_risk: Human-readable bias risk label.
        disagreement_notes: List of disagreement notes.

    Returns:
        Decision dictionary with verdict, scores, and justification.
    """
    return {
        "verdict": "synthesized",
        "score_a": round(logician_confidence * 10.0, 1),
        "score_b": round(creative_confidence * 10.0, 1),
        "justification": (
            f"Confidence: {overall_confidence} | "
            f"Bias Risk: {overall_bias_risk} | "
            f"Disagreements: {', '.join(disagreement_notes) if disagreement_notes else 'None'}"
        ),
    }


# ── Parse-and-repair fallback ───────────────────────────────────────

def safe_parse_agent_output(
    raw: Any,
    role_name: str,
    parse_fn: Any,
    output_cls: Any,
) -> Any:
    """Parse raw LLM output into AgentOutput with fallback for dict results.

    Replaces the duplicate parse_and_repair + isinstance(parsed, dict)
    pattern found in decisions.py (lines 303-310, 338-345, 373-380).

    Args:
        raw: Raw output from LLM gateway.
        role_name: Agent role name for error messages (e.g., 'Breaker').
        parse_fn: The parse_and_repair function to use.
        output_cls: The AgentOutput class to construct on dict fallback.

    Returns:
        Parsed AgentOutput instance.
    """
    parsed = parse_fn(raw, output_cls)
    if isinstance(parsed, dict):
        return output_cls(
            reasoning_steps=parsed.get("reasoning_steps", ["Parse failure"]),
            answer=parsed.get("answer", f"ERROR: {role_name} output unparsable."),
            confidence=parsed.get("confidence", 0.0),
        )
    return parsed
