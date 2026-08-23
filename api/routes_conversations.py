"""Conversation CRUD: list/save/delete/purge (owner-scoped; GDPR Art. 17 purge)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import Field as PField
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.schemas import _StrictRequestModel
from core.database import get_db
from core.models import ConversationMessageRecord, ConversationSessionRecord, User
from core.security import get_current_user

router = APIRouter()


class ConversationSaveRequest(_StrictRequestModel):
    id: str
    title: str = "New Conversation"
    mode: str = "HYBRID"
    transcript: list[dict[str, Any]] = PField(default_factory=list)


@router.get("/api/conversations")
async def get_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return all conversation sessions owned by the current user from PostgreSQL."""
    stmt = (
        select(ConversationSessionRecord)
        .where(ConversationSessionRecord.owner_email == current_user.email)
        .options(selectinload(ConversationSessionRecord.messages))
        .order_by(ConversationSessionRecord.updated_at.desc())
    )
    res = await db.execute(stmt)
    sessions = res.scalars().all()

    convs = []
    for s in sessions:
        sorted_msgs = sorted(s.messages, key=lambda m: m.timestamp)
        last_activity = s.updated_at or s.created_at
        convs.append({
            "id": s.session_id,
            "title": s.title or "Conversation",
            "time": last_activity.strftime("%b %d, %H:%M") if last_activity else "Just now",
            "mode": s.state,
            "agentsCount": 1,
            "score": None,
            "transcript": [
                {
                    "id": str(m.id),
                    "role": m.role,
                    "text": m.content,
                }
                for m in sorted_msgs
            ],
        })
    return {"conversations": convs}


@router.post("/api/conversations")
async def save_conversation(
    req: ConversationSaveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Persist or update a conversation session and its transcript in PostgreSQL."""
    stmt = (
        select(ConversationSessionRecord)
        .where(
            ConversationSessionRecord.session_id == req.id,
            ConversationSessionRecord.owner_email == current_user.email,
        )
        .options(selectinload(ConversationSessionRecord.messages))
    )
    res = await db.execute(stmt)
    session_rec = res.scalars().first()

    if session_rec is None:
        session_rec = ConversationSessionRecord(
            session_id=req.id,
            owner_email=current_user.email,
            title=req.title[:255],
            state=req.mode[:32],
        )
        db.add(session_rec)
        await db.flush()
    else:
        session_rec.title = req.title[:255]
        session_rec.state = req.mode[:32]
        session_rec.turn_count = len(req.transcript)
        # Force the bump even when title/state/turn_count are unchanged, so a
        # re-save always refreshes list ordering (onupdate fires only on UPDATE).
        session_rec.updated_at = datetime.now(timezone.utc)
        await db.execute(
            delete(ConversationMessageRecord).where(
                ConversationMessageRecord.session_id == session_rec.id
            )
        )

    for turn in req.transcript:
        msg_text = turn.get("text") or ""
        msg_role = turn.get("role") or "user"
        msg_rec = ConversationMessageRecord(
            session_id=session_rec.id,
            role=msg_role[:16],
            content=msg_text,
        )
        db.add(msg_rec)

    session_rec.turn_count = len(req.transcript)
    await db.commit()
    return {"status": "ok", "id": req.id}


@router.delete("/api/conversations/{session_id}")
async def delete_conversation(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a conversation owned by current user from PostgreSQL."""
    stmt = select(ConversationSessionRecord).where(
        ConversationSessionRecord.session_id == session_id,
        ConversationSessionRecord.owner_email == current_user.email,
    )
    res = await db.execute(stmt)
    session_rec = res.scalars().first()
    if session_rec:
        await db.delete(session_rec)
        await db.commit()
    return {"status": "deleted"}


@router.delete("/api/conversations")
async def purge_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete every conversation owned by the current user.

    GDPR Art. 17 erasure path for durable memory: sessions cascade to their
    messages (ON DELETE CASCADE), and the memory-search index is a GENERATED
    column over those messages, so nothing user-authored survives this call.
    """
    stmt = select(ConversationSessionRecord).where(
        ConversationSessionRecord.owner_email == current_user.email
    )
    res = await db.execute(stmt)
    sessions = res.scalars().all()
    for session_rec in sessions:
        await db.delete(session_rec)
    await db.commit()
    return {"status": "purged", "deleted_sessions": len(sessions)}
