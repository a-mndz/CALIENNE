"""Session lifecycle and checkpoint endpoints (HIGH-015 ownership enforced)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.schemas import _StrictRequestModel
from core.models import User
from core.security import get_current_user
from orchestrator.conversation import ConversationState

router = APIRouter()


def _components() -> dict[str, Any]:
    """Late-bound access to the shared component dict.

    server.py owns ``_aetheris``; tests monkeypatch it there, so handlers must
    read it at call time rather than importing a snapshot.
    """
    import server as _server

    return _server._aetheris



class SessionCreateRequest(_StrictRequestModel):
    session_id: str | None = None


class SessionCreateResponse(BaseModel):
    session_id: str
    state: str
    created_at: str


class SessionMetadataResponse(BaseModel):
    session_id: str
    turn_count: int
    total_tokens: int
    state: str
    remaining_capacity: int


class SessionHistoryResponse(BaseModel):
    history: list[dict[str, str]]


class SessionCloseResponse(BaseModel):
    session_id: str
    state: str
    closed_at: str


class CheckpointListResponse(BaseModel):
    checkpoints: list[dict[str, str]]


class CheckpointRestoreRequest(_StrictRequestModel):
    pass


class CheckpointRestoreResponse(BaseModel):
    request_id: str
    resumed_from_stage: str
    status: str


class CheckpointDeleteResponse(BaseModel):
    request_id: str
    deleted_count: int


@router.post("/api/sessions", response_model=SessionCreateResponse, status_code=201)
async def create_session(
    req: SessionCreateRequest,
    current_user: User = Depends(get_current_user),
) -> SessionCreateResponse:
    """Create a new conversation session owned by the caller (HIGH-015)."""
    import uuid

    conversation_director = _components().get("conversation_director")
    if not conversation_director:
        raise HTTPException(status_code=503, detail="Conversation director not available")

    session_id = req.session_id or str(uuid.uuid4())
    owner = current_user.email

    try:
        session = conversation_director.create_session(session_id, owner_email=owner)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SessionCreateResponse(
        session_id=session.session_id,
        state=session.state.value,
        created_at=session.created_at.isoformat(),
    )


def _require_session_ownership(
    conversation_director: Any,
    session_id: str,
    current_user: User,
) -> None:
    """HIGH-015: reject cross-user session access with 403."""
    if not conversation_director.verify_access(session_id, current_user.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session does not belong to the authenticated user.",
        )


@router.get("/api/sessions/{session_id}", response_model=SessionMetadataResponse)
async def get_session_metadata(
    session_id: str,
    current_user: User = Depends(get_current_user),
) -> SessionMetadataResponse:
    """Retrieve session metadata (HIGH-015 ownership enforced)."""
    conversation_director = _components().get("conversation_director")
    if not conversation_director:
        raise HTTPException(status_code=503, detail="Conversation director not available")

    _require_session_ownership(conversation_director, session_id, current_user)

    try:
        metadata = conversation_director.get_metadata(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return SessionMetadataResponse(**metadata)


@router.get("/api/sessions/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(
    session_id: str,
    current_user: User = Depends(get_current_user),
) -> SessionHistoryResponse:
    """Retrieve conversation history (HIGH-015 ownership enforced)."""
    conversation_director = _components().get("conversation_director")
    if not conversation_director:
        raise HTTPException(status_code=503, detail="Conversation director not available")

    _require_session_ownership(conversation_director, session_id, current_user)

    try:
        history = conversation_director.get_history(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return SessionHistoryResponse(history=history)


@router.delete("/api/sessions/{session_id}", response_model=SessionCloseResponse)
async def close_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
) -> SessionCloseResponse:
    """Explicitly close a conversation session (HIGH-015 ownership enforced)."""
    conversation_director = _components().get("conversation_director")
    if not conversation_director:
        raise HTTPException(status_code=503, detail="Conversation director not available")

    _require_session_ownership(conversation_director, session_id, current_user)

    try:
        conversation_director.transition_state(session_id, ConversationState.COMPLETED)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SessionCloseResponse(
        session_id=session_id,
        state="completed",
        closed_at=datetime.now(timezone.utc).isoformat(),
    )


# ── Checkpoint Management Endpoints ───────────────────────────────────────


@router.get("/api/checkpoints/{request_id}", response_model=CheckpointListResponse)
async def list_checkpoints(
    request_id: str,
    current_user: User = Depends(get_current_user),
) -> CheckpointListResponse:
    """List checkpoints for a request."""
    checkpoint_manager = _components().get("checkpoint_manager")
    if not checkpoint_manager:
        raise HTTPException(status_code=503, detail="Checkpoint manager not available")

    try:
        checkpoints = await checkpoint_manager.list_checkpoints(
            request_id=request_id, user_email=current_user.email
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    checkpoint_list = [
        {
            "checkpoint_id": cp.checkpoint_id,
            "stage": cp.stage,
            "timestamp": cp.timestamp.isoformat(),
            "expires_at": cp.expires_at.isoformat(),
        }
        for cp in checkpoints
    ]

    return CheckpointListResponse(checkpoints=checkpoint_list)


@router.post("/api/checkpoints/{checkpoint_id}/restore", response_model=CheckpointRestoreResponse)
async def restore_checkpoint(
    checkpoint_id: str,
    req: CheckpointRestoreRequest,
    current_user: User = Depends(get_current_user),
) -> CheckpointRestoreResponse:
    """Resume pipeline from a checkpoint."""
    checkpoint_manager = _components().get("checkpoint_manager")
    if not checkpoint_manager:
        raise HTTPException(status_code=503, detail="Checkpoint manager not available")

    try:
        checkpoint = await checkpoint_manager.restore_checkpoint(
            checkpoint_id, user_email=current_user.email
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if checkpoint is None:
        raise HTTPException(status_code=404, detail=f"Checkpoint {checkpoint_id} not found or expired")

    return CheckpointRestoreResponse(
        request_id=checkpoint.request_id,
        resumed_from_stage=checkpoint.stage,
        status="restored",
    )


@router.delete("/api/checkpoints/{request_id}", response_model=CheckpointDeleteResponse)
async def delete_checkpoints(
    request_id: str,
    current_user: User = Depends(get_current_user),
) -> CheckpointDeleteResponse:
    """Delete all checkpoints for a request."""
    checkpoint_manager = _components().get("checkpoint_manager")
    if not checkpoint_manager:
        raise HTTPException(status_code=503, detail="Checkpoint manager not available")

    try:
        deleted_count = await checkpoint_manager.delete_checkpoints(
            request_id, user_email=current_user.email
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CheckpointDeleteResponse(
        request_id=request_id,
        deleted_count=deleted_count,
    )
