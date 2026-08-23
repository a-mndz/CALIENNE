"""
Thread-safe request tracking for the CALIENNE execution pipeline.

The execution passport is intentionally implemented with dataclasses so it can
be passed between synchronous and asynchronous components without coupling the
runtime state to a validation framework.

ponytail: Not converted to CalienneBaseModel — dataclasses + threading.Lock
are the correct tool for mutable runtime state. Pydantic adds overhead and
breaks the threading contract. (See ADR-001 carve-out: this is not a "schema"
in the RFC sense.)
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, ClassVar

from core.validators import (
    as_utc,
    iso_utc,
    utc_now,
    validate_dict,
    validate_list,
    validate_non_empty,
    validate_non_negative_int,
    validate_string_list,
)

logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC."""
    return as_utc(value)


def _iso_utc(value: datetime) -> str:
    """Serialize a datetime in ISO 8601 UTC form."""
    return iso_utc(value)


@dataclass(slots=True)
class SecurityMetadata:
    """Security events recorded while processing a request."""

    injection_attempts: int = 0
    validation_failures: list[str] = field(default_factory=list)
    scrubbed_secrets: int = 0

    MAX_VALIDATION_FAILURES: ClassVar[int] = 50

    def __post_init__(self) -> None:
        validate_non_negative_int(self.injection_attempts, "injection_attempts")
        validate_non_negative_int(self.scrubbed_secrets, "scrubbed_secrets")
        validate_list(
            self.validation_failures,
            "validation_failures",
            max_length=self.MAX_VALIDATION_FAILURES,
            element_type=str,
            element_type_name="entries",
        )


@dataclass(slots=True)
class ExecutionState:
    """Mutable pipeline state stored by an :class:`ExecutionPassport`."""

    current_stage: str = "idle"
    agent_outputs: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checkpoints: list[str] = field(default_factory=list)

    MAX_AGENTS: ClassVar[int] = 10
    MAX_ERRORS: ClassVar[int] = 100
    MAX_WARNINGS: ClassVar[int] = 100

    def __post_init__(self) -> None:
        validate_non_empty(self.current_stage, "current_stage")
        validate_dict(self.agent_outputs, "agent_outputs")
        if len(self.agent_outputs) > self.MAX_AGENTS:
            raise ValueError(
                f"agent_outputs cannot contain more than {self.MAX_AGENTS} agents"
            )
        validate_list(self.errors, "errors", max_length=self.MAX_ERRORS)
        validate_list(self.warnings, "warnings", max_length=self.MAX_WARNINGS)
        validate_string_list(self.warnings, "warnings")
        validate_list(self.checkpoints, "checkpoints")
        validate_string_list(self.checkpoints, "checkpoints")


@dataclass
class ExecutionPassport:
    """
    Request identity and audit state shared across CALIENNE components.

    All mutation helpers use a ``threading.Lock``. Limits are enforced by
    retaining the first configured number of entries; existing agent outputs
    may still be updated after the ten-agent limit has been reached.
    """

    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str | None = None
    user_id: str | None = None
    timestamp: datetime = field(default_factory=utc_now)
    security_metadata: SecurityMetadata = field(default_factory=SecurityMetadata)
    execution_state: ExecutionState = field(default_factory=ExecutionState)
    execution_manifest: Any | None = None

    _lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
        compare=False,
    )

    EXECUTION_TIMEOUT_SEC: ClassVar[int] = 300
    LOGGING_RETRY_ATTEMPTS: ClassVar[int] = 3
    LOGGING_RETRY_DELAY_SEC: ClassVar[int] = 1
    TERMINAL_STAGES: ClassVar[frozenset[str]] = frozenset(
        {"completed", "failed", "aborted"}
    )

    def __post_init__(self) -> None:
        try:
            parsed_request_id = uuid.UUID(str(self.request_id))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("request_id must be a valid UUID v4") from exc
        if parsed_request_id.version != 4:
            raise ValueError("request_id must be a UUID v4")

        object.__setattr__(self, "request_id", str(parsed_request_id))
        object.__setattr__(self, "timestamp", _as_utc(self.timestamp))

        if self.session_id is not None and not isinstance(self.session_id, str):
            raise TypeError("session_id must be a string or None")
        if self.user_id is not None and not isinstance(self.user_id, str):
            raise TypeError("user_id must be a string or None")
        if not isinstance(self.security_metadata, SecurityMetadata):
            raise TypeError("security_metadata must be SecurityMetadata")
        if not isinstance(self.execution_state, ExecutionState):
            raise TypeError("execution_state must be ExecutionState")

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "request_id" and "request_id" in self.__dict__:
            raise AttributeError("request_id is immutable")
        super().__setattr__(name, value)

    def record_error(
        self,
        stage: str,
        error: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a stage error, retaining at most 100 entries."""
        validate_non_empty(stage, "stage")
        validate_non_empty(error, "error")
        if details is not None and not isinstance(details, dict):
            raise TypeError("details must be a dictionary or None")

        with self._lock:
            self._record_error_unlocked(stage, error, details)

    def _record_error_unlocked(
        self,
        stage: str,
        error: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if len(self.execution_state.errors) >= ExecutionState.MAX_ERRORS:
            return
        self.execution_state.errors.append(
            {
                "stage": stage,
                "error": error,
                "details": deepcopy(details) if details else {},
                "timestamp": _iso_utc(utc_now()),
            }
        )

    def record_warning(self, message: str) -> None:
        """Record a warning, retaining at most 100 entries."""
        validate_non_empty(message, "message")
        with self._lock:
            if len(self.execution_state.warnings) < ExecutionState.MAX_WARNINGS:
                self.execution_state.warnings.append(message)

    def update_stage(self, stage: str) -> None:
        """Update the current pipeline stage."""
        validate_non_empty(stage, "stage")
        with self._lock:
            self.execution_state.current_stage = stage

    def add_agent_output(self, agent: str, output: Any) -> None:
        """Add or replace an agent output while enforcing the ten-agent cap."""
        validate_non_empty(agent, "agent")
        with self._lock:
            outputs = self.execution_state.agent_outputs
            if agent in outputs or len(outputs) < ExecutionState.MAX_AGENTS:
                outputs[agent] = output

    def add_checkpoint(self, checkpoint_id: str) -> None:
        """Record a checkpoint identifier."""
        validate_non_empty(checkpoint_id, "checkpoint_id")
        with self._lock:
            self.execution_state.checkpoints.append(checkpoint_id)

    def set_execution_manifest(self, manifest: Any) -> None:
        """Attach the request's frozen execution manifest."""

        with self._lock:
            self.execution_manifest = manifest

    def record_injection_attempt(self) -> None:
        """Increment the prompt-injection attempt counter."""
        with self._lock:
            self.security_metadata.injection_attempts += 1

    def record_validation_failure(self, reason: str) -> None:
        """Record a security validation failure, retaining at most 50."""
        validate_non_empty(reason, "reason")
        with self._lock:
            failures = self.security_metadata.validation_failures
            if len(failures) < SecurityMetadata.MAX_VALIDATION_FAILURES:
                failures.append(reason)

    def record_scrubbed_secret(self, count: int = 1) -> None:
        """Increment the number of secrets scrubbed from request data."""
        validate_non_negative_int(count, "count")
        with self._lock:
            self.security_metadata.scrubbed_secrets += count

    def elapsed_seconds(self, now: datetime | None = None) -> float:
        """Return elapsed execution time in seconds."""
        current_time = _as_utc(now) if now is not None else utc_now()
        return max(0.0, (current_time - self.timestamp).total_seconds())

    def is_timed_out(self, now: datetime | None = None) -> bool:
        """Return whether a non-terminal execution exceeded 300 seconds."""
        with self._lock:
            is_terminal = (
                self.execution_state.current_stage.casefold() in self.TERMINAL_STAGES
            )
        return not is_terminal and self.elapsed_seconds(now) > self.EXECUTION_TIMEOUT_SEC

    def enforce_timeout(self, now: datetime | None = None) -> bool:
        """
        Force an overdue non-terminal execution into the failed stage.

        Returns ``True`` only when this call performs the transition.
        """
        current_time = _as_utc(now) if now is not None else utc_now()
        elapsed = max(0.0, (current_time - self.timestamp).total_seconds())

        with self._lock:
            current_stage = self.execution_state.current_stage
            if (
                current_stage.casefold() in self.TERMINAL_STAGES
                or elapsed <= self.EXECUTION_TIMEOUT_SEC
            ):
                return False

            self.execution_state.current_stage = "failed"
            self._record_error_unlocked(
                current_stage,
                f"Execution timed out after {elapsed:.3f} seconds",
                {"timeout_seconds": self.EXECUTION_TIMEOUT_SEC},
            )

        self.log_final_state()
        return True

    def check_timeout(self, now: datetime | None = None) -> bool:
        """Compatibility alias for timeout enforcement."""
        return self.enforce_timeout(now)

    def to_dict(self) -> dict[str, Any]:
        """
        Return a detached state snapshot for logging and telemetry.

        The lock is held only while copying state. Mutating the returned
        dictionary cannot mutate the passport.
        """
        with self._lock:
            return {
                "request_id": self.request_id,
                "session_id": self.session_id,
                "user_id": self.user_id,
                "timestamp": _iso_utc(self.timestamp),
                "execution_manifest": (
                    self.execution_manifest.model_dump(mode="json")
                    if hasattr(self.execution_manifest, "model_dump")
                    else deepcopy(self.execution_manifest)
                ),
                "security_metadata": {
                    "injection_attempts": self.security_metadata.injection_attempts,
                    "validation_failures": list(
                        self.security_metadata.validation_failures
                    ),
                    "scrubbed_secrets": self.security_metadata.scrubbed_secrets,
                },
                "execution_state": {
                    "current_stage": self.execution_state.current_stage,
                    "agent_outputs": deepcopy(self.execution_state.agent_outputs),
                    "errors": deepcopy(self.execution_state.errors),
                    "warnings": list(self.execution_state.warnings),
                    "checkpoints": list(self.execution_state.checkpoints),
                },
            }

    def snapshot(self) -> dict[str, Any]:
        """Return the detached monitoring snapshot."""
        return self.to_dict()

    def log_final_state(
        self,
        log_method: Callable[[str], Any] | None = None,
        sleep_method: Callable[[float], None] | None = None,
    ) -> bool:
        """
        Log the JSON passport state with three attempts and one-second delays.

        A failed audit log never blocks request completion. The injectable
        callables keep retry behavior deterministic in tests.
        """
        target = log_method or logger.info
        sleeper = sleep_method or time.sleep
        payload = json.dumps(self.to_dict(), default=str, sort_keys=True)

        for attempt in range(1, self.LOGGING_RETRY_ATTEMPTS + 1):
            try:
                target(payload)
                return True
            except Exception as exc:  # pragma: no cover - depends on log backend
                if attempt < self.LOGGING_RETRY_ATTEMPTS:
                    sleeper(self.LOGGING_RETRY_DELAY_SEC)
                    continue
                try:
                    logger.warning(
                        "Unable to log final ExecutionPassport state after %s "
                        "attempts: %s",
                        self.LOGGING_RETRY_ATTEMPTS,
                        exc,
                    )
                except Exception:
                    pass
        return False
