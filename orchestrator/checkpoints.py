"""
calienne — Checkpoint Manager
Save and restore pipeline state for recovery from failures.

Specifications from Requirement 13:
- Save timeout: 5 seconds
- Restore timeout: 10 seconds
- Total checkpoint size limit: 10 MB per request
- Individual agent output size limit: 5 MB
- Retention period: configurable 1 hour to 30 days (default 7 days)
- Storage backends: memory (Phase 1), filesystem, database
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from core.error_handlers import with_timeout
from core.validators import (
    utc_now,
    validate_dict,
    validate_enum,
    validate_non_empty,
)

logger = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    """A saved pipeline state checkpoint."""
    checkpoint_id: str
    request_id: str
    user_email: Optional[str]
    session_id: Optional[str]
    stage: str
    agent_outputs: dict[str, Any]
    partial_results: dict[str, Any]
    timestamp: datetime = field(default_factory=utc_now)
    expires_at: datetime = field(default_factory=lambda: utc_now() + timedelta(days=7))


class CheckpointManager:
    """
    Save and restore pipeline state for recovery from failures.

    Specifications from Requirement 13:
    - 5-second save timeout
    - 10-second restore timeout
    - 10 MB total size per request, 5 MB per agent output
    - Configurable retention: 1 hour to 30 days (default 7 days)
    - Storage backends: memory, filesystem, database
    """

    # Timeouts (Requirement 13.1, 13.4-13.5)
    SAVE_TIMEOUT_SEC = 5  # 5-second timeout for save operations
    RESTORE_TIMEOUT_SEC = 10  # 10-second timeout for restore operations
    QUERY_TIMEOUT_SEC = 2  # 2-second timeout for query operations
    EXPIRY_CLEANUP_TIMEOUT_SEC = 2  # 2-second timeout for expiry cleanup

    # Size limits (Requirement 13.9)
    MAX_CHECKPOINT_SIZE_MB = 10  # 10 MB total size per request
    MAX_AGENT_OUTPUT_SIZE_MB = 5  # 5 MB per individual agent output

    # Retention (Requirement 13.6-13.7)
    MIN_RETENTION_HOURS = 1  # Minimum 1 hour retention
    MAX_RETENTION_DAYS = 30  # Maximum 30 days retention
    DEFAULT_RETENTION_DAYS = 7  # Default 7 days retention

    MAX_CHECKPOINTS_PER_REQUEST = 10

    def __init__(
        self,
        storage_backend: str = "memory",
        retention_days: int = 7,
        db_session_factory: Any = None,
    ):
        """Initialize with storage backend: 'memory', 'filesystem', or 'database'.

        Args:
            storage_backend: 'memory' (default), 'filesystem' (JSON files), or 'database' (PostgreSQL)
            retention_days: Checkpoint retention period (1-30 days, default 7)
            db_session_factory: Callable returning an ``AsyncSession`` (required when
                ``storage_backend`` is ``database``).  Used by the CRIT-003 backend
                switch to keep checkpoints across server restarts.
        """
        validate_enum(storage_backend, ("memory", "filesystem", "database"), "storage_backend")
        self.storage_backend = storage_backend
        self.db_session_factory = db_session_factory
        # Clamp retention_days to range [1/24, 30] (1 hour minimum, 30 days maximum)
        self.retention_days = max(
            self.MIN_RETENTION_HOURS / 24,
            min(retention_days, self.MAX_RETENTION_DAYS)
        )
        # In-memory storage: request_id -> list of checkpoints
        self.checkpoints: dict[str, list[Checkpoint]] = {}
        if storage_backend == "database" and db_session_factory is None:
            logger.warning(
                "CheckpointManager created with database backend but no session factory; "
                "database operations will raise RuntimeError until a factory is wired in."
            )
        logger.info(
            "Initialized CheckpointManager with backend=%s, retention_days=%.2f",
            storage_backend,
            self.retention_days,
        )

    async def save_checkpoint(
        self,
        request_id: str,
        user_email: str,
        session_id: Optional[str],
        stage: str,
        agent_outputs: dict[str, Any],
        partial_results: dict[str, Any],
    ) -> str:
        """Save a checkpoint within 5 seconds, return checkpoint_id.

        Truncates outputs exceeding 5 MB with truncation marker.
        Fails gracefully if timeout or storage error, logs error and continues.
        """
        validate_non_empty(request_id, "request_id")
        validate_non_empty(user_email, "user_email")
        validate_non_empty(stage, "stage")
        validate_dict(agent_outputs, "agent_outputs")
        validate_dict(partial_results, "partial_results")

        # Generate unique checkpoint_id
        checkpoint_id = str(uuid.uuid4())

        # Check total checkpoint size (rough estimate in bytes) before truncation
        total_size = self._estimate_checkpoint_size(agent_outputs, partial_results)
        max_bytes = self.MAX_CHECKPOINT_SIZE_MB * 1024 * 1024
        if total_size > max_bytes:
            logger.warning(
                "Checkpoint size %.2f MB exceeds limit %d MB for request %s, rejecting",
                total_size / (1024 * 1024),
                self.MAX_CHECKPOINT_SIZE_MB,
                request_id,
                extra={"request_id": request_id, "session_id": session_id, "stage": "checkpoint_save"}
            )
            raise ValueError(
                f"Checkpoint size {total_size / (1024 * 1024):.2f} MB exceeds "
                f"limit {self.MAX_CHECKPOINT_SIZE_MB} MB"
            )

        # Truncate agent outputs exceeding 5 MB limit
        truncated_outputs = self._truncate_agent_outputs(agent_outputs)

        # Create checkpoint with expiry
        expires_at = utc_now() + timedelta(days=self.retention_days)
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            request_id=request_id,
            user_email=user_email,
            session_id=session_id,
            stage=stage,
            agent_outputs=truncated_outputs,
            partial_results=partial_results,
            timestamp=utc_now(),
            expires_at=expires_at,
        )

        await asyncio.wait_for(
            self._store_checkpoint(checkpoint), timeout=self.SAVE_TIMEOUT_SEC
        )
        logger.info(
            "Saved checkpoint %s for request %s at stage %s",
            checkpoint_id,
            request_id,
            stage,
            extra={"request_id": request_id, "session_id": session_id, "stage": "checkpoint_save"}
        )
        return checkpoint_id

    async def restore_checkpoint(
        self, checkpoint_id: str, user_email: Optional[str] = None
    ) -> Optional[Checkpoint]:
        """Restore a checkpoint by ID within 10 seconds."""
        validate_non_empty(checkpoint_id, "checkpoint_id")

        result = await with_timeout(
            self._retrieve_checkpoint(checkpoint_id, user_email),
            timeout_sec=self.RESTORE_TIMEOUT_SEC,
            operation_name="Checkpoint restore",
            default=None,
        )
        if result is None:
            logger.warning("Checkpoint %s not found", checkpoint_id, extra={"checkpoint_id": checkpoint_id, "stage": "checkpoint_restore"})  # noqa: E501
        elif result.expires_at <= utc_now():
            logger.warning("Checkpoint %s expired", checkpoint_id)
            return None
        else:
            logger.info("Restored checkpoint %s", checkpoint_id, extra={"checkpoint_id": checkpoint_id, "stage": "checkpoint_restore"})  # noqa: E501
        return result

    async def get_latest_checkpoint(
        self, request_id: str, user_email: Optional[str] = None
    ) -> Optional[Checkpoint]:
        """Retrieve the most recent checkpoint for a request."""
        validate_non_empty(request_id, "request_id")

        if self.storage_backend == "database":
            return await self._get_latest_checkpoint_db(request_id.strip(), user_email)

        checkpoints = [
            checkpoint
            for checkpoint in self.checkpoints.get(request_id.strip(), [])
            if checkpoint.expires_at > utc_now()
            and (user_email is None or checkpoint.user_email == user_email)
        ]
        if not checkpoints:
            return None
        # Return the most recent checkpoint (sorted by timestamp descending)
        latest = max(checkpoints, key=lambda cp: cp.timestamp)
        return latest

    async def list_checkpoints(
        self,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> list[Checkpoint]:
        """List checkpoints filtered by request_id or session_id within 2 seconds."""
        result = await with_timeout(
            self._list_checkpoints_impl(request_id, session_id, user_email),
            timeout_sec=self.QUERY_TIMEOUT_SEC,
            operation_name="Checkpoint query",
            default=[],
        )
        now = utc_now()
        return [checkpoint for checkpoint in (result or []) if checkpoint.expires_at > now]

    async def expire_checkpoints(self) -> int:
        """Remove expired checkpoints within 2 seconds, return count removed."""
        result = await with_timeout(
            self._expire_checkpoints_impl(),
            timeout_sec=self.EXPIRY_CLEANUP_TIMEOUT_SEC,
            operation_name="Checkpoint expiry cleanup",
            default=0,
        )
        return result or 0

    async def delete_checkpoints(
        self, request_id: str, user_email: Optional[str] = None
    ) -> int:
        """Delete all checkpoints for a request, return count deleted."""
        validate_non_empty(request_id, "request_id")

        if self.storage_backend == "database":
            return await self._delete_checkpoints_db(request_id.strip(), user_email)

        request_id = request_id.strip()
        if request_id in self.checkpoints:
            existing = self.checkpoints[request_id]
            deleted = [cp for cp in existing if user_email is None or cp.user_email == user_email]
            retained = [cp for cp in existing if cp not in deleted]
            count = len(deleted)
            if retained:
                self.checkpoints[request_id] = retained
            else:
                del self.checkpoints[request_id]
            logger.info(
                "Deleted %d checkpoints for request %s",
                count,
                request_id,
                extra={"request_id": request_id, "stage": "checkpoint_delete"}
            )
            return count
        return 0

    # Private helper methods

    async def _store_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Store checkpoint in the configured backend."""
        if self.storage_backend == "memory":
            request_id = checkpoint.request_id
            if request_id not in self.checkpoints:
                self.checkpoints[request_id] = []
            if len(self.checkpoints[request_id]) >= self.MAX_CHECKPOINTS_PER_REQUEST:
                oldest = min(self.checkpoints[request_id], key=lambda cp: cp.timestamp)
                self.checkpoints[request_id].remove(oldest)
                logger.debug(
                    "Removed oldest checkpoint %s for request %s to stay within limit",
                    oldest.checkpoint_id,
                    request_id,
                )
            self.checkpoints[request_id].append(checkpoint)
            return

        if self.storage_backend == "database":
            await self._store_checkpoint_db(checkpoint)
            return

        raise NotImplementedError(f"Storage backend '{self.storage_backend}' not yet implemented")

    async def _retrieve_checkpoint(
        self, checkpoint_id: str, user_email: Optional[str]
    ) -> Optional[Checkpoint]:
        """Retrieve checkpoint by ID from the configured backend."""
        if self.storage_backend == "memory":
            for request_checkpoints in self.checkpoints.values():
                for checkpoint in request_checkpoints:
                    if checkpoint.checkpoint_id == checkpoint_id and (
                        user_email is None or checkpoint.user_email == user_email
                    ):
                        return checkpoint
            return None

        if self.storage_backend == "database":
            return await self._retrieve_checkpoint_db(checkpoint_id, user_email)

        raise NotImplementedError(f"Storage backend '{self.storage_backend}' not yet implemented")

    async def _list_checkpoints_impl(
        self,
        request_id: Optional[str],
        session_id: Optional[str],
        user_email: Optional[str],
    ) -> list[Checkpoint]:
        """List checkpoints with optional filters."""
        if self.storage_backend == "memory":
            results: list[Checkpoint] = []
            for req_id, checkpoints in self.checkpoints.items():
                if request_id is not None and req_id != request_id:
                    continue
                for checkpoint in checkpoints:
                    if session_id is not None and checkpoint.session_id != session_id:
                        continue
                    if user_email is not None and checkpoint.user_email != user_email:
                        continue
                    results.append(checkpoint)
            results.sort(key=lambda cp: cp.timestamp, reverse=True)
            return results

        if self.storage_backend == "database":
            return await self._list_checkpoints_db(request_id, session_id, user_email)

        raise NotImplementedError(f"Storage backend '{self.storage_backend}' not yet implemented")

    async def _expire_checkpoints_impl(self) -> int:
        """Remove expired checkpoints from the configured backend."""
        if self.storage_backend == "memory":
            now = utc_now()
            expired_count = 0
            expired_request_ids = []
            for request_id, checkpoints in self.checkpoints.items():
                expired_checkpoints = [cp for cp in checkpoints if cp.expires_at < now]
                for cp in expired_checkpoints:
                    checkpoints.remove(cp)
                    expired_count += 1
                if not checkpoints:
                    expired_request_ids.append(request_id)
            for request_id in expired_request_ids:
                del self.checkpoints[request_id]
            return expired_count

        if self.storage_backend == "database":
            return await self._expire_checkpoints_db()

        raise NotImplementedError(f"Storage backend '{self.storage_backend}' not yet implemented")

    # ── Database backend helpers (CRIT-003) ────────────────────────────

    def _require_db_factory(self) -> Any:
        if self.db_session_factory is None:
            raise RuntimeError(
                "CheckpointManager(database) requires db_session_factory to be provided."
            )
        return self.db_session_factory

    @staticmethod
    def _record_to_checkpoint(record: Any) -> Checkpoint:
        payload = record.payload or {}
        timestamp = record.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        expires_at = record.expires_at or timestamp
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return Checkpoint(
            checkpoint_id=record.checkpoint_id,
            request_id=record.request_id,
            user_email=record.user_email,
            session_id=payload.get("session_id"),
            stage=record.stage,
            agent_outputs=payload.get("agent_outputs", {}),
            partial_results=payload.get("partial_results", {}),
            timestamp=timestamp,
            expires_at=expires_at,
        )

    async def _store_checkpoint_db(self, checkpoint: Checkpoint) -> None:
        from sqlalchemy import select

        from core.models import CheckpointRecord

        factory = self._require_db_factory()
        async with factory() as session:
            existing_q = await session.execute(
                select(CheckpointRecord).where(
                    CheckpointRecord.checkpoint_id == checkpoint.checkpoint_id
                )
            )
            existing = existing_q.scalar_one_or_none()
            payload = {
                "session_id": checkpoint.session_id,
                "agent_outputs": checkpoint.agent_outputs,
                "partial_results": checkpoint.partial_results,
            }
            if existing is None:
                record = CheckpointRecord(
                    checkpoint_id=checkpoint.checkpoint_id,
                    request_id=checkpoint.request_id,
                    user_email=checkpoint.user_email,
                    stage=checkpoint.stage,
                    payload=payload,
                    timestamp=checkpoint.timestamp,
                    expires_at=checkpoint.expires_at,
                )
                session.add(record)
            else:
                existing.request_id = checkpoint.request_id
                existing.user_email = checkpoint.user_email
                existing.stage = checkpoint.stage
                existing.payload = payload
                existing.timestamp = checkpoint.timestamp
                existing.expires_at = checkpoint.expires_at
            await session.commit()

    async def _retrieve_checkpoint_db(
        self, checkpoint_id: str, user_email: Optional[str]
    ) -> Optional[Checkpoint]:
        from sqlalchemy import select

        from core.models import CheckpointRecord

        factory = self._require_db_factory()
        async with factory() as session:
            stmt = select(CheckpointRecord).where(CheckpointRecord.checkpoint_id == checkpoint_id)
            if user_email is not None:
                stmt = stmt.where(CheckpointRecord.user_email == user_email)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if record is None:
                return None
            return self._record_to_checkpoint(record)

    async def _get_latest_checkpoint_db(
        self, request_id: str, user_email: Optional[str]
    ) -> Optional[Checkpoint]:
        from sqlalchemy import select

        from core.models import CheckpointRecord

        factory = self._require_db_factory()
        async with factory() as session:
            stmt = (
                select(CheckpointRecord)
                .where(
                    CheckpointRecord.request_id == request_id,
                    CheckpointRecord.expires_at > utc_now(),
                )
                .order_by(CheckpointRecord.timestamp.desc())
                .limit(1)
            )
            if user_email is not None:
                stmt = stmt.where(CheckpointRecord.user_email == user_email)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            return self._record_to_checkpoint(record) if record is not None else None

    async def _list_checkpoints_db(
        self,
        request_id: Optional[str],
        session_id: Optional[str],
        user_email: Optional[str],
    ) -> list[Checkpoint]:
        from sqlalchemy import select

        from core.models import CheckpointRecord

        factory = self._require_db_factory()
        async with factory() as session:
            stmt = select(CheckpointRecord)
            if request_id is not None:
                stmt = stmt.where(CheckpointRecord.request_id == request_id)
            if user_email is not None:
                stmt = stmt.where(CheckpointRecord.user_email == user_email)
            stmt = stmt.order_by(CheckpointRecord.timestamp.desc())
            result = await session.execute(stmt)
            records = list(result.scalars())
            checkpoints = [self._record_to_checkpoint(r) for r in records]
            if session_id is not None:
                checkpoints = [cp for cp in checkpoints if cp.session_id == session_id]
            return checkpoints

    async def _expire_checkpoints_db(self) -> int:
        from sqlalchemy import delete

        from core.models import CheckpointRecord

        factory = self._require_db_factory()
        async with factory() as session:
            stmt = delete(CheckpointRecord).where(CheckpointRecord.expires_at < utc_now())
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    async def _delete_checkpoints_db(
        self, request_id: str, user_email: Optional[str]
    ) -> int:
        from sqlalchemy import delete

        from core.models import CheckpointRecord

        factory = self._require_db_factory()
        async with factory() as session:
            stmt = delete(CheckpointRecord).where(CheckpointRecord.request_id == request_id)
            if user_email is not None:
                stmt = stmt.where(CheckpointRecord.user_email == user_email)
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    def _truncate_agent_outputs(self, agent_outputs: dict[str, Any]) -> dict[str, Any]:
        """Truncate agent outputs exceeding 5 MB limit."""
        max_bytes = self.MAX_AGENT_OUTPUT_SIZE_MB * 1024 * 1024
        truncated = {}
        for agent_name, output in agent_outputs.items():
            # Estimate size of output
            try:
                output_bytes = len(json.dumps(output, default=str).encode("utf-8"))
            except Exception:
                # If serialization fails, treat as zero size
                output_bytes = 0
            if output_bytes > max_bytes:
                # Truncate with marker
                if isinstance(output, str):
                    truncated[agent_name] = (
                        output[:1000] + "[TRUNCATED: exceeded 5 MB limit]"
                    )
                else:
                    truncated[agent_name] = (
                        f"[TRUNCATED: exceeded 5 MB limit] Original size: {output_bytes} bytes"
                    )
                logger.warning(
                    "Truncated agent output for %s: %d bytes > %d bytes limit",
                    agent_name,
                    output_bytes,
                    max_bytes,
                    extra={"agent_name": agent_name, "stage": "checkpoint_save"}
                )
            else:
                truncated[agent_name] = output
        return truncated

    def _estimate_checkpoint_size(
        self,
        agent_outputs: dict[str, Any],
        partial_results: dict[str, Any],
    ) -> int:
        """Estimate checkpoint size in bytes (rough estimate)."""
        # Serialize to JSON and count bytes
        data = {
            "agent_outputs": agent_outputs,
            "partial_results": partial_results,
        }
        try:
            return len(json.dumps(data, default=str).encode("utf-8"))
        except Exception:
            # Fallback estimate: 100 bytes per item
            return (len(agent_outputs) + len(partial_results)) * 100
