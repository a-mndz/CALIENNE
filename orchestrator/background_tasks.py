"""
Background cleanup tasks for CALIENNE components.

This module defines periodic background tasks that maintain system health
by cleaning up expired sessions, checkpoints, reasoning graph patterns,
and stale streams.
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine

from core.error_handlers import periodic_cleanup_task

logger = logging.getLogger(__name__)


async def cleanup_expired_sessions_task(
    conversation_director: Any,
    interval_seconds: int = 3600,
) -> None:
    """Periodically clean up expired conversation sessions.

    Parameters
    ----------
    conversation_director:
        ConversationDirector instance.
    interval_seconds:
        Sleep interval between cleanup runs (default: 3600 seconds = 1 hour).
    """
    await periodic_cleanup_task(
        component=conversation_director,
        method_name="cleanup_expired_sessions",
        task_description="expired conversation sessions",
        interval_seconds=interval_seconds,
        is_async=False,
        log_verb="Cleaned up",
    )


async def expire_checkpoints_task(
    checkpoint_manager: Any,
    interval_seconds: int = 3600,
) -> None:
    """Periodically expire old checkpoints.

    Parameters
    ----------
    checkpoint_manager:
        CheckpointManager instance.
    interval_seconds:
        Sleep interval between cleanup runs (default: 3600 seconds = 1 hour).
    """
    await periodic_cleanup_task(
        component=checkpoint_manager,
        method_name="expire_checkpoints",
        task_description="checkpoints",
        interval_seconds=interval_seconds,
        is_async=True,
        log_verb="Expired",
    )


async def expire_graph_patterns_task(
    reasoning_graph: Any,
    interval_seconds: int = 86400,
) -> None:
    """Periodically expire old reasoning graph patterns.

    Parameters
    ----------
    reasoning_graph:
        ReasoningGraph instance.
    interval_seconds:
        Sleep interval between cleanup runs (default: 86400 seconds = 1 day).
    """
    await periodic_cleanup_task(
        component=reasoning_graph,
        method_name="expire_old_patterns",
        task_description="reasoning graph patterns",
        interval_seconds=interval_seconds,
        is_async=False,
        log_verb="Expired",
    )


async def cleanup_stale_streams_task(
    streaming_manager: Any,
    interval_seconds: int = 300,
) -> None:
    """Periodically clean up stale streams.

    Parameters
    ----------
    streaming_manager:
        StreamingManager instance.
    interval_seconds:
        Sleep interval between cleanup runs (default: 300 seconds = 5 minutes).
    """
    await periodic_cleanup_task(
        component=streaming_manager,
        method_name="cleanup_stale_streams",
        task_description="stale streams",
        interval_seconds=interval_seconds,
        is_async=True,
        log_verb="Cleaned up",
    )


def create_background_tasks(
    components: dict[str, Any],
) -> list[asyncio.Task]:
    """Create background tasks for all cleanup operations.

    Parameters
    ----------
    components:
        Dictionary mapping component names to instances (from initialize_calienne_components).

    Returns
    -------
    list[asyncio.Task]
        List of created background tasks.
    """
    tasks: list[asyncio.Task] = []

    # Extract components with defaults to handle missing components gracefully
    conversation_director = components.get("conversation_director")
    checkpoint_manager = components.get("checkpoint_manager")
    reasoning_graph = components.get("reasoning_graph")
    streaming_manager = components.get("streaming_manager")

    if conversation_director is not None:
        tasks.append(
            asyncio.create_task(
                cleanup_expired_sessions_task(conversation_director),
                name="cleanup_expired_sessions",
            )
        )
    else:
        logger.warning("ConversationDirector not available, skipping expired sessions cleanup")

    if checkpoint_manager is not None:
        tasks.append(
            asyncio.create_task(
                expire_checkpoints_task(checkpoint_manager),
                name="expire_checkpoints",
            )
        )
    else:
        logger.warning("CheckpointManager not available, skipping checkpoint expiration")

    if reasoning_graph is not None:
        tasks.append(
            asyncio.create_task(
                expire_graph_patterns_task(reasoning_graph),
                name="expire_graph_patterns",
            )
        )
    else:
        logger.warning("ReasoningGraph not available, skipping pattern expiration")

    if streaming_manager is not None:
        tasks.append(
            asyncio.create_task(
                cleanup_stale_streams_task(streaming_manager),
                name="cleanup_stale_streams",
            )
        )
    else:
        logger.warning("StreamingManager not available, skipping stale streams cleanup")

    logger.info("Created %d background cleanup tasks", len(tasks))
    return tasks


async def cancel_background_tasks(tasks: list[asyncio.Task]) -> None:
    """Cancel all background tasks gracefully.

    Parameters
    ----------
    tasks:
        List of background tasks to cancel.
    """
    for task in tasks:
        task.cancel()
    # Wait for all tasks to be cancelled (or raise CancelledError)
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("All background tasks cancelled")


# Example usage in main.py (for reference):
#
# from orchestrator.background_tasks import create_background_tasks, cancel_background_tasks
#
# # During startup:
# components = initialize_calienne_components()
# background_tasks = create_background_tasks(components)
#
# # During shutdown:
# await cancel_background_tasks(background_tasks)
