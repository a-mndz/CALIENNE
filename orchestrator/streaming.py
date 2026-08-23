"""
calienne — Adaptive Multi-Model Reasoning Orchestrator
Streaming Manager: Granular SSE event emission with buffering and payload limits.

Specifications from Requirement 10 and Design Document Component 9:
- 100 concurrent stream limit
- 64KB (65536 bytes) payload limit per event
- 1000 event buffer capacity per stream
- 500ms latency threshold for buffering warnings
- 300s client timeout for stale stream cleanup
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, AsyncGenerator, Optional

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Timezone-aware UTC ``datetime`` factory (HIGH-010)."""
    return datetime.now(timezone.utc)


# ── Event Types ──────────────────────────────────────────────────────────


class EventType(str, Enum):
    """SSE event types emitted during pipeline execution."""

    AGENT_STARTED = "agent_started"
    PROGRESS = "progress"
    REASONING_SUMMARY = "reasoning_summary"
    DRAFT_ANSWER = "draft_answer"
    AGENT_COMPLETED = "agent_completed"
    ERROR = "error"
    RESULT = "result"
    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    STAGE_FAILED = "stage_failed"
    INJECTION_DETECTED = "injection_detected"
    VALIDATION_FAILED = "validation_failed"
    BREAKER_PASSED = "breaker_passed"
    BREAKER_FAILED = "breaker_failed"
    GENERATION_COMPLETED = "generation_completed"
    JUDGE_SYNTHESIZED = "judge_synthesized"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    QUEUE_FULL = "queue_full"
    PROVIDER_DEGRADED = "provider_degraded"


# ── Stream Event ─────────────────────────────────────────────────────────


@dataclass
class StreamEvent:
    """A single event in a Server-Sent Events stream."""

    event: EventType
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """Serialize event for JSON encoding."""
        return {
            "event": self.event.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }


# ── Streaming Manager ────────────────────────────────────────────────────


class StreamingManager:
    """Manages concurrent SSE event streams with buffering and payload limits.

    Specifications (Design Document Component 9, Requirement 10):
    - MAX_CONCURRENT_STREAMS = 100 streams
    - BUFFER_SIZE = 1000 events per stream
    - PAYLOAD_LIMIT_BYTES = 65536 (64 KB)
    - LATENCY_THRESHOLD_MS = 500 ms
    - CLIENT_TIMEOUT_SEC = 300 s (5 minutes)
    """

    MAX_CONCURRENT_STREAMS = 100
    BUFFER_SIZE = 1000
    PAYLOAD_LIMIT_BYTES = 65536  # 64 KB
    LATENCY_THRESHOLD_MS = 500
    CLIENT_TIMEOUT_SEC = 300  # 5 minutes

    def __init__(self) -> None:
        self._active_streams: dict[str, asyncio.Queue[StreamEvent | None]] = {}
        self._stream_timestamps: dict[str, float] = {}
        self._stream_tasks: dict[str, asyncio.Task[None]] = {}

    # ── Stream Lifecycle ──────────────────────────────────────────────

    def get_active_stream_count(self) -> int:
        """Return the number of currently active streams."""
        return len(self._active_streams)

    def create_stream(self, request_id: str) -> asyncio.Queue[StreamEvent | None]:
        """Create a new event stream for a request.

        Args:
            request_id: Unique identifier for the request.

        Returns:
            asyncio.Queue for the stream.

        Raises:
            RuntimeError: If the maximum concurrent stream limit is reached.
        """
        if request_id in self._active_streams:
            logger.warning("Stream already exists for request_id=%s, closing old stream.", request_id)
            self.close_stream(request_id)

        if len(self._active_streams) >= self.MAX_CONCURRENT_STREAMS:
            raise RuntimeError(
                f"Maximum concurrent streams ({self.MAX_CONCURRENT_STREAMS}) reached. "
                "Close existing streams before creating new ones."
            )

        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue(maxsize=self.BUFFER_SIZE)
        self._active_streams[request_id] = queue
        self._stream_timestamps[request_id] = time.monotonic()

        logger.info(
            "Created stream for request_id=%s (active: %d/%d)",
            request_id,
            len(self._active_streams),
            self.MAX_CONCURRENT_STREAMS,
        )
        return queue

    def close_stream(self, request_id: str) -> None:
        """Clean up stream resources and cancel associated tasks.

        Args:
            request_id: The request whose stream should be closed.
        """
        queue = self._active_streams.pop(request_id, None)
        self._stream_timestamps.pop(request_id, None)

        task = self._stream_tasks.pop(request_id, None)
        if task and not task.done():
            task.cancel()

        # Unblock any waiting consumers by putting a sentinel
        if queue is not None:
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

        logger.info(
            "Closed stream for request_id=%s (active: %d)",
            request_id,
            len(self._active_streams),
        )

    # ── Event Emission ────────────────────────────────────────────────

    async def emit_event(self, request_id: str, event: StreamEvent) -> None:
        """Emit an event to the stream, buffering if client is slow.

        Enforces:
        - Payload size limit of 64KB (65536 bytes)
        - Buffer overflow drops oldest events with warning
        - Latency threshold warning at 500ms

        Args:
            request_id: The request to emit the event for.
            event: The StreamEvent to emit.
        """
        queue = self._active_streams.get(request_id)
        if queue is None:
            logger.warning("No active stream for request_id=%s, event dropped.", request_id)
            return

        # Track emission latency
        emit_start = time.monotonic()

        # Check payload size
        payload_bytes = len(json.dumps(event.data).encode("utf-8"))
        if payload_bytes > self.PAYLOAD_LIMIT_BYTES:
            logger.warning(
                "Event payload exceeded %d bytes (%d bytes) for request_id=%s, truncating.",
                self.PAYLOAD_LIMIT_BYTES,
                payload_bytes,
                request_id,
            )
            event.data["__truncated__"] = True
            # Truncate data values to fit within limit
            truncated_data: dict[str, Any] = {}
            running_size = len(json.dumps({"event": event.event.value, "timestamp": event.timestamp.isoformat()}).encode("utf-8"))  # noqa: E501
            for key, value in event.data.items():
                if key == "__truncated__":
                    continue
                entry = json.dumps({key: value}).encode("utf-8")
                if running_size + len(entry) + 2 <= self.PAYLOAD_LIMIT_BYTES - 50:  # 50 bytes for truncation marker  # noqa: E501
                    truncated_data[key] = value
                    running_size += len(entry) + 2
                else:
                    break
            truncated_data["__truncated__"] = True
            truncated_data["__truncation_marker__"] = "[TRUNCATED: payload exceeded 64KB limit]"
            event.data = truncated_data

        # Buffer event, dropping oldest if full
        if queue.full():
            logger.warning(
                "Event buffer full (capacity=%d) for request_id=%s, dropping oldest event.",
                self.BUFFER_SIZE,
                request_id,
            )
            try:
                queue.get_nowait()  # Drop oldest
            except asyncio.QueueEmpty:
                pass

        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.error("Failed to enqueue event for request_id=%s after draining.", request_id)

        # Update timestamp for staleness tracking
        self._stream_timestamps[request_id] = time.monotonic()

        # Latency threshold check
        latency_ms = (time.monotonic() - emit_start) * 1000
        if latency_ms > self.LATENCY_THRESHOLD_MS:
            logger.warning(
                "High event emission latency: %.1fms (threshold: %dms) for request_id=%s",
                latency_ms,
                self.LATENCY_THRESHOLD_MS,
                request_id,
            )

    # ── Stream Iteration ──────────────────────────────────────────────

    async def iter_events(self, request_id: str) -> AsyncGenerator[dict[str, Any], None]:
        """Iterate over events in SSE format as an async generator.

        Events are yielded in chronological order with timestamp in ISO 8601 format.
        A ``None`` sentinel signals stream closure.

        Args:
            request_id: The request whose events to iterate.

        Yields:
            SSE-formatted dictionaries with ``event`` and ``data`` keys.
        """
        queue = self._active_streams.get(request_id)
        if queue is None:
            logger.warning("No active stream for request_id=%s, nothing to iterate.", request_id)
            return

        while True:
            try:
                item = await queue.get()
            except asyncio.CancelledError:
                break

            if item is None:
                # Sentinel: stream closed
                break

            yield {
                "event": item.event.value,
                "data": item.data,
                "timestamp": item.timestamp.isoformat(),
            }

    # ── Stale Stream Cleanup ──────────────────────────────────────────

    async def cleanup_stale_streams(self) -> int:
        """Remove streams inactive for CLIENT_TIMEOUT_SEC (300 seconds).

        Returns:
            Count of removed stale streams.
        """
        now = time.monotonic()
        stale_ids = [
            rid
            for rid, ts in self._stream_timestamps.items()
            if now - ts > self.CLIENT_TIMEOUT_SEC
        ]

        for rid in stale_ids:
            logger.info("Cleaning up stale stream for request_id=%s (inactive > %ds).", rid, self.CLIENT_TIMEOUT_SEC)  # noqa: E501
            self.close_stream(rid)

        return len(stale_ids)

    # ── Convenience: Emit Without Creating StreamEvent ────────────────

    async def emit(
        self,
        request_id: str,
        event_type: EventType,
        data: dict[str, Any],
    ) -> None:
        """Convenience wrapper: emit an event by type and data dict.

        Args:
            request_id: The request to emit the event for.
            event_type: The type of event.
            data: Event payload data.
        """
        event = StreamEvent(event=event_type, data=data)
        await self.emit_event(request_id, event)

    async def emit_raw(
        self,
        request_id: str,
        event_dict: dict[str, Any],
    ) -> None:
        """Emit a raw event dict (backward-compatible with stream_micro_mode format).

        The dict is expected to have an ``event`` key (string event type) and
        arbitrary payload keys.  The ``event`` key is mapped to an EventType
        where possible; unknown types are mapped to EventType.PROGRESS.

        Args:
            request_id: The request to emit the event for.
            event_dict: Raw event dictionary.
        """
        event_type_str = event_dict.pop("event", "progress")
        try:
            event_type = EventType(event_type_str)
        except ValueError:
            event_type = EventType.PROGRESS
            event_dict["original_event"] = event_type_str

        # Filter out None values and keep the rest as data
        data = {k: v for k, v in event_dict.items() if v is not None}
        event = StreamEvent(event=event_type, data=data)
        await self.emit_event(request_id, event)
