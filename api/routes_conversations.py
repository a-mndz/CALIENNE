"""Conversation CRUD: list/save/delete/purge (owner-scoped; GDPR Art. 17 purge)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import Field as PField
from sqlalchemy import delete, func, select
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
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return all conversation sessions owned by the current user from PostgreSQL."""
    stmt = (
        select(ConversationSessionRecord)
        .where(ConversationSessionRecord.owner_email == current_user.email)
        .options(selectinload(ConversationSessionRecord.messages))
        .order_by(ConversationSessionRecord.updated_at.desc())
        .limit(limit)
        .offset(offset)
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
        new_turns = req.transcript
    else:
        session_rec.title = req.title[:255]
        session_rec.state = req.mode[:32]
        session_rec.updated_at = datetime.now(timezone.utc)
        existing_msgs = sorted(session_rec.messages or [], key=lambda m: m.timestamp)
        existing_count = len(existing_msgs)

        # Detect if any existing turns were modified, replaced, or truncated
        modified = False
        if len(req.transcript) < existing_count:
            modified = True
        else:
            for idx in range(existing_count):
                turn = req.transcript[idx]
                msg = existing_msgs[idx]
                if (turn.get("text") or "") != msg.content or (turn.get("role") or "user")[:16] != msg.role:
                    modified = True
                    break

        if modified:
            # Replace all messages if prior history was edited or truncated
            await db.execute(
                delete(ConversationMessageRecord).where(
                    ConversationMessageRecord.session_id == session_rec.id
                )
            )
            new_turns = req.transcript
        else:
            # Append-only: preserve existing message IDs and prevent O(N^2) churn
            new_turns = req.transcript[existing_count:]

    for turn in new_turns:
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
    stmt_count = select(func.count(ConversationSessionRecord.id)).where(
        ConversationSessionRecord.owner_email == current_user.email
    )
    count = (await db.scalar(stmt_count)) or 0
    await db.execute(
        delete(ConversationSessionRecord).where(
            ConversationSessionRecord.owner_email == current_user.email
        )
    )
    await db.commit()
    return {"status": "purged", "deleted_sessions": count}
