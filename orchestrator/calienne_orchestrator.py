"""
calienne — CALIENNE Central Orchestration Module

Factory function that instantiates all CALIENNE components, wires their
dependencies, and returns a dictionary mapping component names to instances.

This module is the single entry point for bootstrapping the complete
CALIENNE architecture so that main.py and other consumers do not need to
know the internal wiring of each component.
"""

from __future__ import annotations

import logging
from typing import Any

from core.passport import ExecutionPassport
from core.runtime import RuntimeEngine
from core.security import SecurityValidator
from orchestrator.checkpoints import CheckpointManager
from orchestrator.claims import ClaimManager
from orchestrator.conversation import ConversationDirector
from orchestrator.decisions import DecisionEngine, DecisionStrategy
from orchestrator.execution_manager import ExecutionManager
from orchestrator.execution_replay import ReplayStore
from orchestrator.feature_flags import load_flags
from orchestrator.memory_manager import MemoryManager, SummarizationStrategy
from orchestrator.reasoning_graph import ReasoningGraph
from orchestrator.state_machine import StateMachine
from orchestrator.streaming import StreamingManager

logger = logging.getLogger(__name__)


def initialize_calienne_components() -> dict[str, Any]:
    """Instantiate all Calienne components and wire their dependencies.

    Returns
    -------
    dict[str, Any]
        Mapping of component name to its instance.
    """
    # ── Security ─────────────────────────────────────────────────────
    security_validator = SecurityValidator()
    logger.info("SecurityValidator initialized.")

    # ── Conversation ─────────────────────────────────────────────────
    conversation_director = ConversationDirector()
    logger.info("ConversationDirector initialized.")

    # ── Checkpoints ──────────────────────────────────────────────────
    checkpoint_manager = CheckpointManager(storage_backend="memory", retention_days=7)
    logger.info("CheckpointManager initialized (backend=memory, retention=7d).")

    # ── Execution Replay (Step 20a) ──────────────────────────────────
    # Only stand up the store when the flag is on; otherwise leave it
    # None so the debug endpoint reports the feature as disabled.
    flags = load_flags()
    replay_store = ReplayStore() if flags.replay else None
    logger.info("ReplayStore %s (flag=%s).", "initialized" if replay_store else "disabled", flags.replay)

    # ── Memory ───────────────────────────────────────────────────────
    memory_manager = MemoryManager(
        strategy=SummarizationStrategy.TRUNCATION,
        context_limit=128_000,
    )
    logger.info("MemoryManager initialized (strategy=truncation, limit=128k).")

    # ── Knowledge Graph ──────────────────────────────────────────────
    reasoning_graph = ReasoningGraph()
    logger.info("ReasoningGraph initialized.")

    # ── Claim Manager ────────────────────────────────────────────────
    claim_manager = ClaimManager()
    logger.info("ClaimManager initialized.")

    # ── Streaming ────────────────────────────────────────────────────
    streaming_manager = StreamingManager()
    logger.info("StreamingManager initialized.")

    # ── Decision Engine ──────────────────────────────────────────────
    # HIGH-009: RuntimeEngine is now wired into DecisionEngine so every
    # provider call goes through contract enforcement (security,
    # rate-limiting, streaming, per-agent metrics).  Build the resource
    # manager first so RuntimeEngine can depend on it.
    from api_gateway.rate_limiter import ProviderResourceManager

    resource_manager = ProviderResourceManager()
    logger.info("ProviderResourceManager initialized.")

    runtime_engine = RuntimeEngine(
        security_validator=security_validator,
        streaming_manager=streaming_manager,
        resource_manager=resource_manager,
    )
    logger.info(
        "RuntimeEngine initialized "
        "(security=%s, streaming=%s, resource=%s).",
        bool(security_validator),
        bool(streaming_manager),
        bool(resource_manager),
    )

    decision_engine = DecisionEngine(
        strategy=DecisionStrategy.PARALLEL,
        streaming_manager=streaming_manager,
        runtime_engine=runtime_engine,
    )
    logger.info(
        "DecisionEngine initialized (strategy=PARALLEL, streaming=True, "
        "runtime_engine=wired per HIGH-009)."
    )

    from orchestrator.resource_manager import ResourceManager as DagResourceManager

    execution_manager = ExecutionManager(
        flags=flags,
        resource_manager=DagResourceManager(rate_limiter=resource_manager),
        memory_manager=memory_manager,
        claim_manager=claim_manager,
        replay_store=replay_store,
        runtime_engine=runtime_engine,
    )

    components: dict[str, Any] = {
        "security_validator": security_validator,
        "conversation_director": conversation_director,
        "checkpoint_manager": checkpoint_manager,
        "replay_store": replay_store,
        "memory_manager": memory_manager,
        "reasoning_graph": reasoning_graph,
        "claim_manager": claim_manager,
        "decision_engine": decision_engine,
        "streaming_manager": streaming_manager,
        "resource_manager": resource_manager,
        "runtime_engine": runtime_engine,
        "execution_manager": execution_manager,
    }

    logger.info(
        "CALIENNE components initialized: %s",
        ", ".join(sorted(components.keys())),
    )
    return components


def create_request_passport(
    session_id: str | None = None,
    user_id: str | None = None,
) -> ExecutionPassport:
    """Create a new ExecutionPassport for a single request.

    Parameters
    ----------
    session_id:
        Optional conversation session identifier.
    user_id:
        Optional authenticated user identifier.

    Returns
    -------
    ExecutionPassport
        A fresh passport with a UUID v4 request_id and ISO 8601 timestamp.
    """
    return ExecutionPassport(session_id=session_id, user_id=user_id)


def create_request_state_machine(request_id: str) -> StateMachine:
    """Create a StateMachine bound to a specific request.

    Parameters
    ----------
    request_id:
        The passport request_id this state machine tracks.

    Returns
    -------
    StateMachine
        A new state machine initialised to the IDLE state.
    """
    return StateMachine(request_id=request_id)


# Backwards compatibility alias
initialize_calienne_components = initialize_calienne_components
