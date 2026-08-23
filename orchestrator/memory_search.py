"""Durable turn memory — ReFind-pattern search over the transcript store.

Design: `.research_tmp/retry_agent_memory.md` idea 1 (verified sources:
arXiv:2608.12888 — lexical, per-turn indexing with **no LLM extraction**
beat the strongest graph baseline 58.2 vs 53.2; PostgreSQL docs §12.3 —
`websearch_to_tsquery` never raises on raw user input; `ts_rank_cd(..., 32)`
bounds rank into [0,1)).

Two surfaces:

- ``PostgresTurnSearchProvider`` — implements the dormant RetrievalProvider
  protocol so it lights up under ``CALIENNE_ENABLE_DAG`` with no changes to
  RetrievalService/ContextManager.
- ``hydrate_history`` — the v1 live path: when a query endpoint receives no
  client history, pull the owner's recent turns plus topically relevant past
  turns. Tenancy is non-negotiable (MAFIA: 90.7% poisoning on shared memory)
  and GDPR Art. 17 deletion rides the existing session→message CASCADE.

Every SQL statement here joins ``conversation_sessions`` and filters
``owner_email`` — ``conversation_messages`` has no owner column by design.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.retrieval import RetrievalProvider, RetrievalRequest, SourceCandidate

logger = logging.getLogger("calienne.MemorySearch")

# Raw user input goes through websearch_to_tsquery precisely because it
# cannot raise (to_tsquery would throw on '&'/'!' inside a query).
_SEARCH_SQL = text(
    """
    SELECT m.content, m.role, m."timestamp" AS ts, s.session_id,
           ts_rank_cd(m.content_tsv, q, 32) AS rank
      FROM conversation_messages m
      JOIN conversation_sessions s ON s.id = m.session_id,
           websearch_to_tsquery('english', :query) AS q
     WHERE s.owner_email = :owner_email
       AND m.content_tsv @@ q
       AND (CAST(:since AS timestamptz) IS NULL OR m."timestamp" >= CAST(:since AS timestamptz))
     ORDER BY rank DESC, m."timestamp" DESC
     LIMIT :k
    """
)

_RECENT_SQL = text(
    """
    SELECT m.content, m.role, m."timestamp" AS ts, s.session_id
      FROM conversation_messages m
      JOIN conversation_sessions s ON s.id = m.session_id
     WHERE s.owner_email = :owner_email
     ORDER BY m."timestamp" DESC
     LIMIT :k
    """
)


def _freshness(turn_timestamp: datetime, now: datetime | None = None) -> float:
    """Recency decay into [0, 1]: 1 now, halving every 7 days."""
    now = now or datetime.now(timezone.utc)
    if turn_timestamp.tzinfo is None:
        turn_timestamp = turn_timestamp.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - turn_timestamp).total_seconds() / 86400.0)
    return max(0.0, 0.5 ** (age_days / 7.0))


def _row_to_candidate(row: Any, rank: float) -> SourceCandidate:
    # RFC-004 §3.2 blend: relevance*0.40 + credibility*0.25 + freshness*0.15
    # + consensus*0.20. User-authored turns carry more weight than model
    # output (provenance-based salience, research idea 3).
    role = getattr(row, "role", "user")
    return SourceCandidate(
        excerpt=str(getattr(row, "content", "")),
        relevance_score=float(rank),
        freshness_score=_freshness(getattr(row, "ts", datetime.now(timezone.utc))),
        credibility_score=0.5 if role == "user" else 0.2,
        consensus_score=0.0,
    )


class PostgresTurnSearchProvider(RetrievalProvider):
    """Lexical search over the owner's stored turns.

    ``owner_email`` MUST be provided (or present in ``request.metadata``).
    A missing owner returns nothing rather than everything — an unscoped
    memory search is a cross-user disclosure, not a fallback case.
    """

    def __init__(self, session_factory: Any, owner_email: str | None = None) -> None:
        self._session_factory = session_factory
        self._owner_email = owner_email

    async def retrieve(self, request: RetrievalRequest) -> list[SourceCandidate]:
        owner = self._owner_email or request.metadata.get("owner_email")
        if not owner:
            logger.warning("Turn search without owner_email — returning nothing.")
            return []
        if not request.query.strip():
            return []

        async with self._session_factory() as db:
            result = await db.execute(
                _SEARCH_SQL,
                {
                    "query": request.query,
                    "owner_email": owner,
                    "since": request.metadata.get("since"),
                    "k": request.limit,
                },
            )
            rows = result.fetchall()

        candidates = [_row_to_candidate(row, row.rank) for row in rows]
        logger.info("Turn search: %d hit(s) for owner over %d slot(s).", len(candidates), request.limit)
        return [candidate.clamped() for candidate in candidates]


async def search_relevant_turns(
    db: AsyncSession,
    *,
    owner_email: str,
    query: str,
    limit: int = 5,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """Topically relevant past turns for the owner, newest-first."""
    if not query.strip():
        return []
    result = await db.execute(
        _SEARCH_SQL,
        {"query": query, "owner_email": owner_email, "since": since, "k": limit},
    )
    return [
        {
            "role": row.role if row.role in {"user", "assistant"} else "user",
            "content": row.content,
            "session_id": row.session_id,
            "timestamp": row.ts.isoformat() if row.ts else None,
        }
        for row in result.fetchall()
    ]


async def recent_turns(
    db: AsyncSession,
    *,
    owner_email: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """The owner's most recent turns regardless of topic."""
    result = await db.execute(_RECENT_SQL, {"owner_email": owner_email, "k": limit})
    return [
        {
            "role": row.role if row.role in {"user", "assistant"} else "user",
            "content": row.content,
            "session_id": row.session_id,
            "timestamp": row.ts.isoformat() if row.ts else None,
        }
        for row in result.fetchall()
    ]


async def hydrate_history(
    db: AsyncSession,
    *,
    owner_email: str,
    query: str,
    recent_limit: int = 6,
    search_limit: int = 5,
) -> list[dict[str, str]]:
    """Memory v1 fallback for the query endpoints.

    Merges a recency window with topically relevant turns (ReFind's
    "chat-native controls" reduced to two SQL predicates), deduplicates,
    and returns chronologically ordered ``{"role", "content"}`` dicts ready
    for the pipeline's ``history`` argument. Only the OWNER's turns are
    ever visible.
    """
    recent = await recent_turns(db, owner_email=owner_email, limit=recent_limit)
    relevant = await search_relevant_turns(db, owner_email=owner_email, query=query, limit=search_limit)

    merged: dict[tuple[str | None, str], dict[str, Any]] = {}
    for turn in [*recent, *relevant]:
        key = (turn.get("session_id"), turn.get("content", ""))
        if key not in merged and turn.get("content"):
            merged[key] = turn

    ordered = sorted(
        merged.values(),
        key=lambda turn: turn.get("timestamp") or "",
    )
    return [
        {"role": str(turn["role"]), "content": str(turn["content"])}
        for turn in ordered
    ]
