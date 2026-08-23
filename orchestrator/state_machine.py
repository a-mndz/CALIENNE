"""
calienne — State Machine for Pipeline Transitions
Manages pipeline state transitions with validation, hooks, and event emission.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class PipelineState(str, Enum):
    """Valid pipeline states."""
    IDLE = "idle"
    NORMALIZING = "normalizing"
    BREACH_CHECKING = "breach_checking"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    SYNTHESIZING = "synthesizing"
    FORMATTING = "formatting"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass
class StateTransition:
    """Record of a state transition."""
    from_state: PipelineState
    to_state: PipelineState
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


# Valid transitions mapping
VALID_TRANSITIONS: dict[PipelineState, list[PipelineState]] = {
    PipelineState.IDLE: [PipelineState.NORMALIZING],
    PipelineState.NORMALIZING: [PipelineState.BREACH_CHECKING, PipelineState.FAILED],
    PipelineState.BREACH_CHECKING: [PipelineState.GENERATING, PipelineState.ABORTED, PipelineState.FAILED],
    PipelineState.GENERATING: [PipelineState.EVALUATING, PipelineState.FAILED],
    PipelineState.EVALUATING: [PipelineState.SYNTHESIZING, PipelineState.FAILED],
    PipelineState.SYNTHESIZING: [PipelineState.FORMATTING, PipelineState.FAILED],
    PipelineState.FORMATTING: [PipelineState.COMPLETED, PipelineState.FAILED],
    PipelineState.COMPLETED: [],  # Terminal state
    PipelineState.FAILED: [],  # Terminal state
    PipelineState.ABORTED: [],  # Terminal state
}


class StateMachine:
    """
    Manages pipeline state transitions with validation, hooks, and event emission.

    Specifications from Requirement 14:
    - 10 states: idle, normalizing, breach_checking, generating, evaluating,
      synthesizing, formatting, completed, failed, aborted
    - Explicit transition map
    - InvalidTransitionError for invalid transitions
    - State history tracking (100 most recent transitions)
    - Hooks: on_enter, on_exit, on_transition
    - Rollback on hook exception
    """

    MAX_HISTORY_SIZE = 100  # Track most recent 100 state transitions

    def __init__(self, request_id: str):
        """
        Initialize the state machine.

        Args:
            request_id: Unique identifier for the request being tracked.
        """
        self.request_id = request_id
        self.current_state = PipelineState.IDLE  # Initial state
        self.history: deque[StateTransition] = deque(maxlen=self.MAX_HISTORY_SIZE)
        self.hooks: dict[str, list[tuple[Optional[PipelineState], Callable]]] = {
            "on_enter": [],
            "on_exit": [],
            "on_transition": [],
        }

    def transition(
        self,
        to_state: PipelineState,
        metadata: Optional[dict[str, Any]] = None
    ) -> StateTransition:
        """
        Transition to a new state with validation.

        Args:
            to_state: Target state to transition to.
            metadata: Optional metadata for the transition.

        Returns:
            StateTransition record of the transition.

        Raises:
            InvalidTransitionError: If transition is not valid from current state.
        """
        if metadata is None:
            metadata = {}

        # Validate transition
        if not self.can_transition(to_state):
            raise InvalidTransitionError(
                f"Invalid transition from {self.current_state.value} to {to_state.value} "
                f"for request {self.request_id}"
            )

        from_state = self.current_state

        # Execute on_exit hooks for current state
        self._execute_hooks("on_exit", from_state)

        # Update state
        self.current_state = to_state

        # Execute on_enter hooks for new state
        try:
            self._execute_hooks("on_enter", to_state)
        except Exception:
            # Rollback on hook exception
            self.current_state = from_state
            raise

        # Create transition record
        transition = StateTransition(
            from_state=from_state,
            to_state=to_state,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata,
        )

        # Track history
        self.history.append(transition)

        # Execute on_transition hooks
        self._execute_hooks("on_transition", None)

        # Log transition
        logger.info(
            "State transition: %s → %s (request=%s)",
            from_state.value,
            to_state.value,
            self.request_id,
            extra={"request_id": self.request_id, "stage": "state_machine", "from_state": from_state.value, "to_state": to_state.value}  # noqa: E501
        )

        return transition

    def can_transition(self, to_state: PipelineState) -> bool:
        """
        Check if transition is valid from current state.

        Args:
            to_state: Target state to check.

        Returns:
            True if transition is valid, False otherwise.
        """
        valid_targets = VALID_TRANSITIONS.get(self.current_state, [])
        return to_state in valid_targets

    def register_hook(
        self,
        hook_type: str,
        callback: Callable,
        state: Optional[PipelineState] = None
    ) -> None:
        """
        Register a callback for state transitions.

        Args:
            hook_type: 'on_enter', 'on_exit', or 'on_transition'.
            callback: Function to execute.
            state: Specific state for on_enter/on_exit hooks (None for on_transition).
        """
        if hook_type not in self.hooks:
            raise ValueError(f"Invalid hook type: {hook_type}. Must be one of: on_enter, on_exit, on_transition")  # noqa: E501

        self.hooks[hook_type].append((state, callback))
        logger.debug(
            "Registered %s hook for state %s (request=%s)",
            hook_type,
            state.value if state else "all",
            self.request_id,
            extra={"request_id": self.request_id, "stage": "state_machine", "hook_type": hook_type}
        )

    def get_state_history(self) -> list[StateTransition]:
        """
        Return complete state transition history.

        Returns:
            List of most recent 100 StateTransition records.
        """
        return list(self.history)

    def _execute_hooks(self, hook_type: str, state: Optional[PipelineState]) -> None:
        """
        Execute hooks of the specified type.

        Args:
            hook_type: Type of hooks to execute.
            state: State to filter hooks by (None for on_transition).
        """
        for hook_state, callback in self.hooks.get(hook_type, []):
            # For on_enter/on_exit, only execute if hook is registered for this specific state
            # For on_transition, execute all hooks regardless of state
            if hook_type == "on_transition" or hook_state == state:
                try:
                    callback()
                except Exception as e:
                    logger.error(
                        "Hook %s failed for state %s: %s",
                        hook_type,
                        state.value if state else "transition",
                        str(e),
                        extra={"request_id": self.request_id, "stage": "state_machine", "hook_type": hook_type, "error": str(e)}  # noqa: E501
                    )
                    raise

    def emit_transition_event(self, transition: StateTransition) -> dict[str, Any]:
        """
        Emit telemetry event for state transition.

        Args:
            transition: The transition that occurred.

        Returns:
            Dictionary containing event data for telemetry.
        """
        event_data = {
            "event": "state_transition",
            "request_id": self.request_id,
            "from_state": transition.from_state.value,
            "to_state": transition.to_state.value,
            "timestamp": transition.timestamp.isoformat(),
            "metadata": transition.metadata,
        }
        logger.info(
            "State transition event: %s → %s (request=%s)",
            transition.from_state.value,
            transition.to_state.value,
            self.request_id,
            extra={"request_id": self.request_id, "stage": "state_machine", "from_state": transition.from_state.value, "to_state": transition.to_state.value}  # noqa: E501
        )
        return event_data
