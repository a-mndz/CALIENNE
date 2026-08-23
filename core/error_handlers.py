"""
Shared error handling utilities for CALIENNE components.

This module provides common error handling patterns extracted from
duplicate code across the codebase, including:
- Base exception classes for CALIENNE errors
- Decorators for API gateway and pipeline error handling
- Timeout handling utilities
- Error recording helpers for ExecutionPassport
- Background task error loop patterns
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from typing import Any, Awaitable, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ── Base Exception Classes ──────────────────────────────────────────────


class CALIENNEException(Exception):
    """Base exception for all CALIENNE component errors."""

    def __init__(self, message: str, component: str = "", details: dict | None = None):
        self.component = component
        self.details = details or {}
        super().__init__(message)


# HIGH-002 audit fix: `SecurityValidationError` is now defined exclusively in
# `core.security` (the canonical owner).  Importing it from this module
# would create two distinct classes which were ``isinstance``-incompatible.
# A backward-compatible alias is preserved so existing callers that import
# from ``core.error_handlers`` continue to work.

from core.security import SecurityValidationError  # noqa: E402,F401


class PipelineError(CALIENNEException):
    """Raised when a pipeline stage encounters an error."""

    def __init__(self, stage: str, message: str, details: dict | None = None):
        super().__init__(message, component=f"pipeline.{stage}", details=details)


class TimeoutError(CALIENNEException):
    """Raised when an operation exceeds its timeout."""

    def __init__(self, operation: str, timeout_sec: float, component: str = ""):
        super().__init__(
            f"{operation} exceeded timeout of {timeout_sec}s",
            component=component,
            details={"operation": operation, "timeout_sec": timeout_sec},
        )


class ProviderError(CALIENNEException):
    """Raised when a provider operation fails."""

    def __init__(self, provider: str, message: str, details: dict | None = None):
        super().__init__(
            f"Provider {provider}: {message}",
            component=f"provider.{provider}",
            details=details,
        )


# ── Error Recording Helpers ─────────────────────────────────────────────


def log_and_record_error(
    passport: Any,
    stage: str,
    error: Exception,
    details: dict | None = None,
    logger_instance: logging.Logger | None = None,
) -> None:
    """Log an error and record it in the ExecutionPassport.

    This is the shared pattern used across decisions.py and other
    components for consistent error recording.

    Parameters
    ----------
    passport:
        ExecutionPassport instance (or None to skip recording).
    stage:
        Pipeline stage or component name where the error occurred.
    error:
        The exception that was raised.
    details:
        Optional additional context about the error.
    logger_instance:
        Logger to use (defaults to module logger).
    """
    log = logger_instance or logger
    error_msg = f"{type(error).__name__}: {error}"
    log.error("Error in %s: %s", stage, error_msg)
    if passport is not None:
        try:
            passport.record_error(stage, error_msg, details)
        except Exception:
            log.warning("Failed to record error in passport for stage %s", stage)


def log_and_record_warning(
    passport: Any,
    message: str,
    logger_instance: logging.Logger | None = None,
) -> None:
    """Log a warning and record it in the ExecutionPassport.

    Parameters
    ----------
    passport:
        ExecutionPassport instance (or None to skip recording).
    message:
        Warning message to log and record.
    logger_instance:
        Logger to use (defaults to module logger).
    """
    log = logger_instance or logger
    log.warning(message)
    if passport is not None:
        try:
            passport.record_warning(message)
        except Exception:
            log.debug("Failed to record warning in passport")


def record_error_if_passport(
    passport: Any,
    stage: str,
    error_msg: str,
    details: dict | None = None,
) -> None:
    """Record an error in passport without logging (for silent error recording).

    Parameters
    ----------
    passport:
        ExecutionPassport instance (or None to skip).
    stage:
        Pipeline stage or component name.
    error_msg:
        Error message to record.
    details:
        Optional additional context.
    """
    if passport is not None:
        try:
            passport.record_error(stage, error_msg, details)
        except Exception:
            pass


# ── Timeout Handling ────────────────────────────────────────────────────


async def with_timeout(
    coro: Awaitable[T],
    timeout_sec: float,
    operation_name: str,
    default: T | None = None,
    passport: Any = None,
    stage: str = "",
    logger_instance: logging.Logger | None = None,
) -> T | None:
    """Execute a coroutine with timeout, logging errors and optionally recording in passport.

    This is the shared pattern used across checkpoints.py for save/restore/query operations.

    Parameters
    ----------
    coro:
        The coroutine to execute.
    timeout_sec:
        Maximum seconds to wait.
    operation_name:
        Human-readable name for logging.
    default:
        Value to return on timeout or error.
    passport:
        Optional ExecutionPassport for error recording.
    stage:
        Stage name for passport error recording.
    logger_instance:
        Logger to use (defaults to module logger).

    Returns
    -------
    The coroutine result, or default on timeout/error.
    """
    log = logger_instance or logger
    try:
        result = await asyncio.wait_for(coro, timeout=timeout_sec)
        return result
    except asyncio.TimeoutError:
        log.error("%s timeout exceeded %d seconds", operation_name, timeout_sec)
        record_error_if_passport(passport, stage or operation_name, f"Timeout: {operation_name}")
        return default
    except Exception as e:
        log.error("%s failed: %s", operation_name, str(e))
        record_error_if_passport(passport, stage or operation_name, f"{operation_name} failed: {e}")
        return default


# ── Conversation State Transition Helper ────────────────────────────────


def transition_conversation_to_failed(
    conversation_director: Any,
    session_id: str | None,
    logger_instance: logging.Logger | None = None,
) -> None:
    """Transition a conversation session to FAILED state, silently ignoring errors.

    This eliminates the 8+ identical try/except blocks in pipelines.py.

    Parameters
    ----------
    conversation_director:
        ConversationDirector instance (or None to skip).
    session_id:
        Session identifier (or None to skip).
    logger_instance:
        Logger to use (defaults to module logger).
    """
    if conversation_director is None or not session_id:
        return
    try:
        from orchestrator.conversation import ConversationState
        conversation_director.transition_state(session_id, ConversationState.FAILED)
    except Exception:
        (logger_instance or logger).debug(
            "Failed to transition session %s to FAILED", session_id
        )


# ── Pipeline Error Result Factories ─────────────────────────────────────


def make_error_result(
    message: str,
    status: str = "error",
    request_id: str = "",
    failed_stage: str = "",
    logician_output: Any = None,
    creative_output: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    """Create a standardized error result dictionary for pipeline failures.

    This eliminates the 7+ identical MicroModeResult dict constructions in pipelines.py.

    Parameters
    ----------
    message:
        Error or abort message.
    status:
        Result status (default "error").
    request_id:
        The request identifier.
    failed_stage:
        The stage that failed.
    logician_output:
        Optional Logician output (may be partial).
    creative_output:
        Optional Creative output (may be partial).
    **extra:
        Additional fields to include.

    Returns
    -------
    Standardized result dictionary.
    """
    result = {
        "status": status,
        "winning_answer": message,
        "validation_score": 0.0,
        "confidence_delta": 0.0,
        "judge_decision": None,
        "logician_output": logician_output,
        "creative_output": creative_output,
        "request_id": request_id,
        "failed_stage": failed_stage,
        **extra,
    }
    return result


def make_abort_result(
    reason: str,
    request_id: str = "",
    logician_output: Any = None,
    creative_output: Any = None,
) -> dict[str, Any]:
    """Create a standardized abort result dictionary.

    Parameters
    ----------
    reason:
        The abort reason.
    request_id:
        The request identifier.
    logician_output:
        Optional Logician output.
    creative_output:
        Optional Creative output.

    Returns
    -------
    Standardized abort result dictionary.
    """
    return make_error_result(
        message=reason,
        status="aborted",
        request_id=request_id,
        logician_output=logician_output,
        creative_output=creative_output,
    )


# ── Background Task Loop Helper ────────────────────────────────────────


async def periodic_cleanup_task(
    component: Any,
    method_name: str,
    task_description: str,
    interval_seconds: int,
    is_async: bool = False,
    log_verb: str = "Cleaned up",
    min_count: int = 1,
) -> None:
    """Generic periodic cleanup task loop.

    This eliminates the 4 identical while/try/except/sleep loops in background_tasks.py.

    Parameters
    ----------
    component:
        Component instance with the cleanup method.
    method_name:
        Name of the method to call on the component.
    task_description:
        Human-readable description for error logging.
    interval_seconds:
        Sleep interval between cleanup runs.
    is_async:
        Whether the method is async (uses await).
    log_verb:
        Verb for logging (e.g., "Cleaned up", "Expired").
    min_count:
        Minimum count to log (skip logging if count < min_count).
    """
    while True:
        try:
            method = getattr(component, method_name)
            if is_async:
                count = await method()
            else:
                count = method()
            if count and count >= min_count:
                logger.info("%s %d %s", log_verb, count, task_description)
        except Exception:
            logger.exception("Error in %s", task_description)
        await asyncio.sleep(interval_seconds)


# ── Agent Execution with Passport Logging ──────────────────────────────


async def execute_with_passport_logging(
    coro: Awaitable[T],
    passport: Any,
    stage: str,
    label: str,
    logger_instance: logging.Logger | None = None,
    on_error_return: Any = None,
) -> T | Any:
    """Execute a coroutine, recording errors in passport on failure.

    This eliminates the repeated try/passport.record_error/logger.error pattern
    shared across decisions.py and other engine modules.

    Parameters
    ----------
    coro:
        The coroutine to execute.
    passport:
        ExecutionPassport instance.
    stage:
        Stage name for error recording.
    label:
        Human-readable label for logging (e.g., "Logician", "Creative").
    logger_instance:
        Logger to use.
    on_error_return:
        Value to return on error (default None).

    Returns
    -------
    The coroutine result, or on_error_return on failure.
    """
    log = logger_instance or logger
    try:
        return await coro
    except Exception as exc:
        passport.record_error(stage, f"{label} failed: {exc}")
        log.error("%s failed: %s", label, exc)
        return on_error_return


# ── Security Validation + Passport Recording ────────────────────────────


def validate_and_record(
    security_validator: Any,
    prompt: str,
    passport: Any,
) -> tuple[bool, list]:
    """Validate input using SecurityValidator and record violations in passport.

    This eliminates the duplicate security validation + passport recording pattern
    in rate_limiter.py and runtime.py.

    Parameters
    ----------
    security_validator:
        SecurityValidator instance.
    prompt:
        User input to validate.
    passport:
        ExecutionPassport for recording violations.

    Returns
    -------
    Tuple of (is_valid, violations).
    """
    is_valid, violations = security_validator.validate_input(prompt)
    if not is_valid:
        for violation in violations:
            passport.record_validation_failure(violation.description)
        if any(v.violation_type == "prompt_injection" for v in violations):
            passport.record_injection_attempt()
    return is_valid, violations
