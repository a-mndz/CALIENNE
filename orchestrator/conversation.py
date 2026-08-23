"""
calienne — Conversation Director
Manages multi-turn dialogue state, history, and context window management.

Specifications from Requirement 3:
- MAX_HISTORY_SIZE = 100 turns per session
- CONTEXT_WINDOW_LIMIT = 128000 tokens
- TRUNCATION_THRESHOLD = 0.8 (80% of context window)
- PRESERVED_TURNS = 5 most recent turns
- EXPIRATION_HOURS = 24 for completed/failed sessions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from core.validators import (
    utc_now,
    validate_non_empty,
    validate_non_negative_int,
)

logger = logging.getLogger(__name__)


class ConversationState(str, Enum):
    """Valid conversation session states."""
    ACTIVE = "active"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


# Valid state transitions for conversation sessions
VALID_CONVERSATION_TRANSITIONS: dict[ConversationState, list[ConversationState]] = {
    ConversationState.ACTIVE: [ConversationState.WAITING, ConversationState.COMPLETED, ConversationState.FAILED],  # noqa: E501
    ConversationState.WAITING: [ConversationState.ACTIVE, ConversationState.COMPLETED, ConversationState.FAILED],  # noqa: E501
    ConversationState.COMPLETED: [],  # Terminal state
    ConversationState.FAILED: [],  # Terminal state
}


@dataclass
class ConversationTurn:
    """A single turn in a conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=utc_now)
    token_count: int = 0


@dataclass
class ConversationSession:
    """A conversation session containing history and metadata."""
    session_id: str
    state: ConversationState = ConversationState.ACTIVE
    history: list[ConversationTurn] = field(default_factory=list)
    total_tokens: int = 0
    created_at: datetime = field(default_factory=utc_now)
    expires_at: Optional[datetime] = None
    # HIGH-015 audit fix: owner_email prevents cross-user session access.
    # ``None`` means the session predates user scoping and is therefore
    # accessible to any authenticated caller (legacy / repair window).
    owner_email: Optional[str] = None


class InvalidConversationTransitionError(Exception):
    """Raised when an invalid conversation state transition is attempted."""
    pass


class ConversationDirector:
    """
    Manages multi-turn dialogue state, history, and context window management.

    Specifications from Requirement 3:
    - Maximum 100 turns per session
    - 128,000 token context window limit
    - Truncation triggered at 80% of context window
    - Preserve 5 most recent turns during truncation
    - 24-hour expiration for completed/failed sessions

    HIGH-015: each session carries an optional ``owner_email``.  Access is
    approved via :meth:`verify_access` which is called from the API layer
    on every session-scoped endpoint.  Ownerless legacy sessions permit
    any authenticated user so existing data is not orphaned during rollout.
    """

    MAX_HISTORY_SIZE: int = 100
    CONTEXT_WINDOW_LIMIT: int = 128_000
    TRUNCATION_THRESHOLD: float = 0.8  # 80% of context window
    PRESERVED_TURNS: int = 5
    EXPIRATION_HOURS: int = 24

    def __init__(self) -> None:
        """Initialize the ConversationDirector with in-memory session storage."""
        self._sessions: dict[str, ConversationSession] = {}

    def create_session(
        self,
        session_id: str,
        owner_email: Optional[str] = None,
    ) -> ConversationSession:
        """
        Initialize a new conversation session.

        Args:
            session_id: Unique identifier for the session.
            owner_email: Optional authenticated user identifier.  When set,
                only that user may access the session (HIGH-015).

        Returns:
            The newly created ConversationSession.

        Raises:
            ValueError: If session_id is empty or already exists.
        """
        session_id = validate_non_empty(session_id, "session_id")

        if session_id in self._sessions:
            raise ValueError(f"Session {session_id} already exists")

        session = ConversationSession(
            session_id=session_id,
            state=ConversationState.ACTIVE,
            history=[],
            total_tokens=0,
            created_at=utc_now(),
            expires_at=None,
            owner_email=owner_email,
        )

        self._sessions[session_id] = session
        logger.info(
            "Created conversation session: %s owner=%s",
            session_id,
            owner_email or "<legacy>",
            extra={"session_id": session_id, "stage": "conversation"},
        )
        return session

    def verify_access(self, session_id: str, user_email: Optional[str]) -> bool:
        """HIGH-015: return True iff the requesting user owns this session.

        Ownerless sessions (``owner_email is None``) accept any authenticated
        caller to honour legacy data.  Owning callers receive True; all other
        identities receive False.
        """
        if user_email is None:
            return False
        session = self._sessions.get(session_id)
        if session is None:
            return False
        if session.owner_email is None:
            return True
        return session.owner_email == user_email

    def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        token_count: int = 0,
    ) -> None:
        """
        Add a conversation turn to the session history.

        Args:
            session_id: The session to add the turn to.
            role: The role of the speaker ("user" or "assistant").
            content: The content of the turn.
            token_count: Number of tokens in the turn.

        Raises:
            ValueError: If session_id is missing, session not found, or role invalid.
        """
        session_id = validate_non_empty(session_id, "session_id")

        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")

        if role not in ("user", "assistant"):
            raise ValueError(f"Invalid role: {role}. Must be 'user' or 'assistant'")

        if not isinstance(content, str):
            raise TypeError("content must be a string")

        validate_non_negative_int(token_count, "token_count")

        session = self._sessions[session_id]

        turn = ConversationTurn(
            role=role,
            content=content,
            timestamp=utc_now(),
            token_count=token_count,
        )

        session.history.append(turn)
        session.total_tokens += token_count

        # Enforce MAX_HISTORY_SIZE by dropping oldest turns
        if len(session.history) > self.MAX_HISTORY_SIZE:
            excess = len(session.history) - self.MAX_HISTORY_SIZE
            session.history = session.history[excess:]

        logger.debug(
            "Added turn to session %s: role=%s, tokens=%d, total=%d",
            session_id,
            role,
            token_count,
            session.total_tokens,
            extra={"session_id": session_id, "stage": "conversation", "role": role}
        )

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        """
        Retrieve conversation history in message format.

        Args:
            session_id: The session to retrieve history for.

        Returns:
            List of dicts with 'role' and 'content' keys.

        Raises:
            ValueError: If session_id is missing or session not found.
        """
        session_id = validate_non_empty(session_id, "session_id")

        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")

        session = self._sessions[session_id]
        return [{"role": turn.role, "content": turn.content} for turn in session.history]

    def get_metadata(self, session_id: str) -> dict[str, Any]:
        """
        Return session metadata including turn count, total tokens, state, and remaining capacity.

        Args:
            session_id: The session to get metadata for.

        Returns:
            Dictionary with turn_count, total_tokens, state, and remaining_capacity.

        Raises:
            ValueError: If session_id is missing or session not found.
        """
        session_id = validate_non_empty(session_id, "session_id")

        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")

        session = self._sessions[session_id]
        remaining_capacity = max(0, self.CONTEXT_WINDOW_LIMIT - session.total_tokens)

        return {
            "turn_count": len(session.history),
            "total_tokens": session.total_tokens,
            "state": session.state.value,
            "remaining_capacity": remaining_capacity,
        }

    def transition_state(
        self,
        session_id: str,
        new_state: ConversationState,
    ) -> None:
        """
        Transition session to a new state with validation.

        Args:
            session_id: The session to transition.
            new_state: The target state.

        Raises:
            ValueError: If session_id is missing or session not found.
            InvalidConversationTransitionError: If transition is not valid.
        """
        session_id = validate_non_empty(session_id, "session_id")

        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")

        session = self._sessions[session_id]
        current_state = session.state

        # Validate transition
        valid_targets = VALID_CONVERSATION_TRANSITIONS.get(current_state, [])
        if new_state not in valid_targets:
            raise InvalidConversationTransitionError(
                f"Invalid transition from {current_state.value} to {new_state.value} "
                f"for session {session_id}"
            )

        session.state = new_state

        # Set expiration for terminal states
        if new_state in (ConversationState.COMPLETED, ConversationState.FAILED):
            session.expires_at = utc_now() + timedelta(hours=self.EXPIRATION_HOURS)
            logger.info(
                "Session %s transitioned to %s, expires at %s",
                session_id,
                new_state.value,
                session.expires_at.isoformat(),
                extra={"session_id": session_id, "stage": "conversation", "state": new_state.value}
            )
        else:
            logger.info(
                "Session %s transitioned from %s to %s",
                session_id,
                current_state.value,
                new_state.value,
                extra={"session_id": session_id, "stage": "conversation", "state": new_state.value}
            )

    def should_truncate(self, session_id: str) -> bool:
        """
        Check if truncation is needed based on token threshold.

        Truncation is triggered when total_tokens exceeds 80% of CONTEXT_WINDOW_LIMIT.

        Args:
            session_id: The session to check.

        Returns:
            True if truncation is needed, False otherwise.

        Raises:
            ValueError: If session_id is missing or session not found.
        """
        session_id = validate_non_empty(session_id, "session_id")

        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")

        session = self._sessions[session_id]
        threshold_tokens = self.TRUNCATION_THRESHOLD * self.CONTEXT_WINDOW_LIMIT

        return session.total_tokens > threshold_tokens

    def truncate_history(self, session_id: str) -> Optional[str]:
        """
        Truncate old turns, preserving the most recent 5 turns and system prompts.

        Generates a summary of removed turns with maximum 500 tokens.

        Args:
            session_id: The session to truncate.

        Returns:
            Summary string of removed turns, or None if no truncation needed.

        Raises:
            ValueError: If session_id is missing or session not found.
        """
        session_id = validate_non_empty(session_id, "session_id")

        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")

        session = self._sessions[session_id]

        if not self.should_truncate(session_id):
            return None

        # Preserve system prompts and most recent PRESERVED_TURNS turns
        preserved_turns: list[ConversationTurn] = []
        removed_turns: list[ConversationTurn] = []

        # Separate system prompts from other turns
        system_prompts = [t for t in session.history if t.role == "system"]
        non_system_turns = [t for t in session.history if t.role != "system"]

        # Preserve system prompts + most recent PRESERVED_TURNS non-system turns
        if len(non_system_turns) > self.PRESERVED_TURNS:
            preserved_turns = non_system_turns[-self.PRESERVED_TURNS:]
            removed_turns = non_system_turns[:-self.PRESERVED_TURNS]
        else:
            preserved_turns = non_system_turns

        # Rebuild history: system prompts + preserved turns
        session.history = system_prompts + preserved_turns

        # Recalculate total tokens
        session.total_tokens = sum(t.token_count for t in session.history)

        # Generate summary of removed turns (max 500 tokens)
        summary = None
        if removed_turns:
            summary_parts = []
            total_summary_tokens = 0
            max_summary_tokens = 500

            for turn in removed_turns:
                part = f"[{turn.role}]: {turn.content[:200]}"
                # Rough token estimate: ~4 chars per token
                part_tokens = len(part) // 4

                if total_summary_tokens + part_tokens > max_summary_tokens:
                    break

                summary_parts.append(part)
                total_summary_tokens += part_tokens

            summary = " ".join(summary_parts) if summary_parts else None

        logger.info(
            "Truncated session %s: removed %d turns, preserved %d, summary_tokens ~%d",
            session_id,
            len(removed_turns),
            len(session.history),
            sum(len(s) // 4 for s in (summary_parts if summary else [])),
            extra={"session_id": session_id, "stage": "conversation"}
        )

        return summary

    def cleanup_expired_sessions(self) -> int:
        """
        Remove sessions past expiration.

        Returns:
            Count of removed sessions.
        """
        now = utc_now()
        expired_ids = []

        for session_id, session in self._sessions.items():
            if session.expires_at is not None and now > session.expires_at:
                expired_ids.append(session_id)

        for session_id in expired_ids:
            del self._sessions[session_id]
            logger.info("Removed expired session: %s", session_id, extra={"session_id": session_id, "stage": "conversation"})  # noqa: E501

        return len(expired_ids)

    def get_session(self, session_id: str) -> Optional[ConversationSession]:
        """
        Retrieve a session by ID.

        Args:
            session_id: The session ID to retrieve.

        Returns:
            The ConversationSession if found, None otherwise.
        """
        if not isinstance(session_id, str) or not session_id.strip():
            return None

        return self._sessions.get(session_id.strip())

    def list_sessions(self) -> list[str]:
        """
        List all active session IDs.

        Returns:
            List of session ID strings.
        """
        return list(self._sessions.keys())

    def delete_session(self, session_id: str) -> bool:
        """
        Explicitly delete a session.

        Args:
            session_id: The session to delete.

        Returns:
            True if session was deleted, False if not found.
        """
        if not isinstance(session_id, str) or not session_id.strip():
            return False

        session_id = session_id.strip()

        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info("Deleted session: %s", session_id, extra={"session_id": session_id, "stage": "conversation"})  # noqa: E501
            return True

        return False
