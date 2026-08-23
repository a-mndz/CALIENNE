"""Memory hierarchy — short / long / user / agent / shared / vector (RFC-004 §2).

The hierarchy is composed of six in-memory layers. ``MemoryManager`` is
retained for compression and token accounting; this module composes the
*remembering* surface area that the new ``ContextManager`` and
``ExecutionManager`` consume. v1 keeps every layer in-process; v2 swaps
the vector layer for ``pgvector`` (DEC-007).

Layers (per RFC-004 §2):

* ``short_term`` — current request and recent turns; ephemeral per request.
* ``long_term`` — durable summaries and prior outcomes keyed by topic.
* ``user_memory`` — stable user preferences and identity hints.
* ``agent_memory`` — per-agent success / failure patterns.
* ``shared_cache`` — RAG and source cache shared across requests.
* ``vector_memory`` — in-memory semantic retrieval (cosine on hashed
  term-frequency vectors in v1; pgvector in v2).

The whole module is gated by :class:`~orchestrator.feature_flags.FeatureFlags.context`
(``CALIENNE_ENABLE_CONTEXT``). When the flag is off, callers must not
instantiate the hierarchy and should fall back to the deterministic
``ContextManager.minimal_window`` path.

Design contract (RFC-004 §2 / ADR-007):

* Every layer's ``read`` / ``write`` is async; sync providers must wrap
  themselves in :func:`asyncio.to_thread`.
* Failures never raise into the request path — the hierarchy logs and
  returns empty results.
* No layer talks raw SQL or raw I/O; the repository interfaces in
  ``orchestrator/experience_db.py`` own persistence (added in Step 20).
* The vector layer exposes ``similarity`` and ``add``; the rest expose
  ``read`` / ``write`` keyed by string.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
import time
from collections import OrderedDict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

LOGGER = logging.getLogger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────


@dataclass
class MemoryEntry:
    """A single memory record with provenance and a deterministic key."""

    key: str
    content: str
    layer: str
    tags: list[str] = field(default_factory=list)
    score: float = 0.0
    source: str = ""
    created_at: float = field(default_factory=lambda: time.time())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "content": self.content,
            "layer": self.layer,
            "tags": list(self.tags),
            "score": self.score,
            "source": self.source,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass
class MemoryQuery:
    """A read against one or more memory layers."""

    query: str
    top_k: int = 5
    tags: list[str] = field(default_factory=list)
    layers: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            self.top_k = 1


# ── Protocol ─────────────────────────────────────────────────────────────


@runtime_checkable
class MemoryLayer(Protocol):
    """Contract every layer in the hierarchy implements."""

    name: str

    async def read(self, query: MemoryQuery) -> list[MemoryEntry]: ...

    async def write(self, entry: MemoryEntry) -> None: ...

    async def evict(self, *, max_age_seconds: float | None = None) -> int: ...

    def snapshot(self) -> dict[str, Any]: ...


# ── Common helpers ───────────────────────────────────────────────────────


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text or "")]


def _stable_key(*parts: str) -> str:
    joined = "::".join(part.strip().lower() for part in parts if part)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def _filter_by_tags(
    entries: Iterable[MemoryEntry],
    tags: list[str],
) -> list[MemoryEntry]:
    if not tags:
        return list(entries)
    wanted = {tag.strip().lower() for tag in tags if tag}
    return [
        entry
        for entry in entries
        if wanted.intersection({t.lower() for t in entry.tags})
    ]


def _score_overlap(query_tokens: list[str], entry_tokens: list[str]) -> float:
    if not query_tokens or not entry_tokens:
        return 0.0
    query_set = set(query_tokens)
    entry_set = set(entry_tokens)
    if not entry_set:
        return 0.0
    overlap = query_set.intersection(entry_set)
    if not overlap:
        return 0.0
    return len(overlap) / math.sqrt(len(query_set) * len(entry_set))


# ── Short-term memory ────────────────────────────────────────────────────


class ShortTermMemory:
    """Ephemeral per-request ring buffer of recent turns (RFC-004 §2)."""

    name = "short_term"

    def __init__(self, max_entries: int = 32) -> None:
        self._max_entries = max(1, max_entries)
        self._entries: "OrderedDict[str, MemoryEntry]" = OrderedDict()

    async def read(self, query: MemoryQuery) -> list[MemoryEntry]:
        tokens = _tokenize(query.query)
        candidates = list(self._entries.values())
        if query.tags:
            candidates = _filter_by_tags(candidates, query.tags)
        scored: list[tuple[float, MemoryEntry]] = []
        for entry in candidates:
            entry_tokens = _tokenize(entry.content)
            entry.score = _score_overlap(tokens, entry_tokens)
            if entry.score <= 0.0 and query.query:
                # Fall back to substring containment for short queries.
                needle = query.query.strip().lower()
                if needle and needle in entry.content.lower():
                    entry.score = 0.25
            if entry.score > 0.0:
                scored.append((entry.score, entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = scored[: query.top_k]
        return [entry for _, entry in top]

    async def write(self, entry: MemoryEntry) -> None:
        if entry.layer != self.name:
            entry.layer = self.name
        self._entries[entry.key] = entry
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    async def evict(self, *, max_age_seconds: float | None = None) -> int:
        if not self._entries:
            return 0
        if max_age_seconds is None:
            count = len(self._entries)
            self._entries.clear()
            return count
        cutoff = time.time() - max(0.0, max_age_seconds)
        expired = [key for key, entry in self._entries.items() if entry.created_at < cutoff]
        for key in expired:
            self._entries.pop(key, None)
        return len(expired)

    def snapshot(self) -> dict[str, Any]:
        return {
            "layer": self.name,
            "entries": len(self._entries),
            "max_entries": self._max_entries,
        }


# ── Long-term memory ────────────────────────────────────────────────────


class LongTermMemory:
    """Durable summaries and prior outcomes keyed by topic (RFC-004 §2)."""

    name = "long_term"

    def __init__(self, max_entries: int = 512) -> None:
        self._max_entries = max(1, max_entries)
        self._entries: dict[str, MemoryEntry] = {}

    async def read(self, query: MemoryQuery) -> list[MemoryEntry]:
        tokens = _tokenize(query.query)
        candidates = list(self._entries.values())
        if query.tags:
            candidates = _filter_by_tags(candidates, query.tags)
        scored: list[tuple[float, MemoryEntry]] = []
        for entry in candidates:
            entry.score = _score_overlap(tokens, _tokenize(entry.content))
            if entry.score > 0.0:
                scored.append((entry.score, entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in scored[: query.top_k]]

    async def write(self, entry: MemoryEntry) -> None:
        if entry.layer != self.name:
            entry.layer = self.name
        existing = self._entries.get(entry.key)
        if existing is not None:
            existing.content = entry.content
            existing.tags = list(entry.tags)
            existing.metadata.update(entry.metadata)
            existing.created_at = entry.created_at
            existing.source = entry.source or existing.source
            return
        self._entries[entry.key] = entry
        if len(self._entries) > self._max_entries:
            # Evict the oldest entry to maintain the cap.
            oldest_key = min(
                self._entries,
                key=lambda key: self._entries[key].created_at,
            )
            self._entries.pop(oldest_key, None)

    async def evict(self, *, max_age_seconds: float | None = None) -> int:
        if max_age_seconds is None:
            count = len(self._entries)
            self._entries.clear()
            return count
        cutoff = time.time() - max(0.0, max_age_seconds)
        expired = [key for key, entry in self._entries.items() if entry.created_at < cutoff]
        for key in expired:
            self._entries.pop(key, None)
        return len(expired)

    def snapshot(self) -> dict[str, Any]:
        return {
            "layer": self.name,
            "entries": len(self._entries),
            "max_entries": self._max_entries,
        }


# ── User memory ──────────────────────────────────────────────────────────


class UserMemory:
    """Stable per-user preferences and identity hints (RFC-004 §2)."""

    name = "user_memory"

    def __init__(self, max_entries: int = 128) -> None:
        self._max_entries = max(1, max_entries)
        self._by_user: dict[str, "OrderedDict[str, MemoryEntry]"] = {}

    def _bucket(self, user_id: str | None) -> "OrderedDict[str, MemoryEntry]":
        key = (user_id or "default").strip().lower() or "default"
        bucket = self._by_user.get(key)
        if bucket is None:
            bucket = OrderedDict()
            self._by_user[key] = bucket
        return bucket

    async def read(self, query: MemoryQuery) -> list[MemoryEntry]:
        user_id = (
            query.metadata.get("user_id")
            if isinstance(query.metadata, Mapping)
            else None
        )
        bucket = self._bucket(str(user_id) if user_id is not None else None)
        tokens = _tokenize(query.query)
        candidates = list(bucket.values())
        if query.tags:
            candidates = _filter_by_tags(candidates, query.tags)
        scored: list[tuple[float, MemoryEntry]] = []
        for entry in candidates:
            entry.score = _score_overlap(tokens, _tokenize(entry.content))
            if entry.score > 0.0:
                scored.append((entry.score, entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in scored[: query.top_k]]

    async def write(self, entry: MemoryEntry) -> None:
        if entry.layer != self.name:
            entry.layer = self.name
        user_id = entry.metadata.get("user_id") if isinstance(entry.metadata, Mapping) else None
        bucket = self._bucket(str(user_id) if user_id is not None else None)
        bucket[entry.key] = entry
        while len(bucket) > self._max_entries:
            bucket.popitem(last=False)

    async def evict(self, *, max_age_seconds: float | None = None) -> int:
        total = 0
        for bucket in self._by_user.values():
            if max_age_seconds is None:
                total += len(bucket)
                bucket.clear()
                continue
            cutoff = time.time() - max(0.0, max_age_seconds)
            expired = [key for key, entry in bucket.items() if entry.created_at < cutoff]
            for key in expired:
                bucket.pop(key, None)
            total += len(expired)
        return total

    def snapshot(self) -> dict[str, Any]:
        return {
            "layer": self.name,
            "users": len(self._by_user),
            "entries": sum(len(bucket) for bucket in self._by_user.values()),
            "max_entries_per_user": self._max_entries,
        }


# ── Agent memory ────────────────────────────────────────────────────────


class AgentMemory:
    """Per-agent success / failure patterns (RFC-004 §2)."""

    name = "agent_memory"

    def __init__(self, max_entries: int = 256) -> None:
        self._max_entries = max(1, max_entries)
        self._by_agent: dict[str, "deque[MemoryEntry]"] = {}

    def _bucket(self, agent: str) -> "deque[MemoryEntry]":
        key = (agent or "default").strip().lower() or "default"
        bucket = self._by_agent.get(key)
        if bucket is None:
            bucket = deque(maxlen=self._max_entries)
            self._by_agent[key] = bucket
        return bucket

    async def read(self, query: MemoryQuery) -> list[MemoryEntry]:
        agent = (
            query.metadata.get("agent")
            if isinstance(query.metadata, Mapping)
            else None
        )
        agent_key = (str(agent) if agent is not None else "default").strip().lower() or "default"
        tokens = _tokenize(query.query)
        candidates: list[MemoryEntry] = []
        if "agent" in (query.metadata or {}) and agent_key != "default":
            candidates.extend(self._by_agent.get(agent_key, []))
        else:
            for bucket in self._by_agent.values():
                candidates.extend(bucket)
        if query.tags:
            candidates = _filter_by_tags(candidates, query.tags)
        scored: list[tuple[float, MemoryEntry]] = []
        for entry in candidates:
            entry.score = _score_overlap(tokens, _tokenize(entry.content))
            if entry.score > 0.0:
                scored.append((entry.score, entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in scored[: query.top_k]]

    async def write(self, entry: MemoryEntry) -> None:
        if entry.layer != self.name:
            entry.layer = self.name
        agent = entry.metadata.get("agent") if isinstance(entry.metadata, Mapping) else None
        bucket = self._bucket(str(agent) if agent is not None else "default")
        bucket.append(entry)

    async def evict(self, *, max_age_seconds: float | None = None) -> int:
        total = 0
        for bucket in self._by_agent.values():
            if max_age_seconds is None:
                total += len(bucket)
                bucket.clear()
                continue
            cutoff = time.time() - max(0.0, max_age_seconds)
            while bucket and bucket[0].created_at < cutoff:
                bucket.popleft()
                total += 1
        return total

    def snapshot(self) -> dict[str, Any]:
        return {
            "layer": self.name,
            "agents": len(self._by_agent),
            "entries": sum(len(bucket) for bucket in self._by_agent.values()),
            "max_entries_per_agent": self._max_entries,
        }


# ── Shared knowledge cache ──────────────────────────────────────────────


class SharedCache:
    """RAG and source cache shared across requests (RFC-004 §2)."""

    name = "shared_cache"

    def __init__(self, max_entries: int = 256) -> None:
        self._max_entries = max(1, max_entries)
        self._entries: "OrderedDict[str, MemoryEntry]" = OrderedDict()
        self._hits = 0
        self._misses = 0

    async def read(self, query: MemoryQuery) -> list[MemoryEntry]:
        tokens = _tokenize(query.query)
        candidates = list(self._entries.values())
        if query.tags:
            candidates = _filter_by_tags(candidates, query.tags)
        scored: list[tuple[float, MemoryEntry]] = []
        for entry in candidates:
            entry.score = _score_overlap(tokens, _tokenize(entry.content))
            if entry.score > 0.0:
                scored.append((entry.score, entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        if scored:
            self._hits += 1
        else:
            self._misses += 1
        return [entry for _, entry in scored[: query.top_k]]

    async def write(self, entry: MemoryEntry) -> None:
        if entry.layer != self.name:
            entry.layer = self.name
        if entry.key in self._entries:
            # Refresh recency on duplicate writes.
            self._entries.move_to_end(entry.key)
        self._entries[entry.key] = entry
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    async def evict(self, *, max_age_seconds: float | None = None) -> int:
        if not self._entries:
            return 0
        if max_age_seconds is None:
            count = len(self._entries)
            self._entries.clear()
            return count
        cutoff = time.time() - max(0.0, max_age_seconds)
        expired = [key for key, entry in self._entries.items() if entry.created_at < cutoff]
        for key in expired:
            self._entries.pop(key, None)
        return len(expired)

    def snapshot(self) -> dict[str, Any]:
        return {
            "layer": self.name,
            "entries": len(self._entries),
            "max_entries": self._max_entries,
            "hits": self._hits,
            "misses": self._misses,
        }


# ── Vector memory (in-memory TF cosine, pgvector in v2) ─────────────────


class VectorMemory:
    """In-memory semantic retrieval layer (RFC-004 §2; DEC-007 deferred pgvector).

    v1 stores TF vectors in process and ranks by cosine similarity. v2
    replaces the storage backend with ``pgvector`` against
    ``experience_learning`` while preserving this contract.
    """

    name = "vector_memory"

    def __init__(self, max_entries: int = 256) -> None:
        self._max_entries = max(1, max_entries)
        self._vectors: "OrderedDict[str, dict[str, float]]" = OrderedDict()
        self._entries: dict[str, MemoryEntry] = {}
        self._norms: dict[str, float] = {}

    async def read(self, query: MemoryQuery) -> list[MemoryEntry]:
        if not self._entries:
            return []
        query_vec = _vectorize(query.query)
        query_norm = _norm(query_vec)
        if query_norm == 0.0:
            return []
        scored: list[tuple[float, MemoryEntry]] = []
        for key, entry_vec in self._vectors.items():
            entry_norm = self._norms.get(key, 0.0)
            if entry_norm == 0.0:
                continue
            score = _dot(query_vec, entry_vec) / (query_norm * entry_norm)
            if score <= 0.0:
                continue
            entry = self._entries.get(key)
            if entry is None:
                continue
            if query.tags and not {
                tag.lower() for tag in query.tags
            }.intersection({t.lower() for t in entry.tags}):
                continue
            entry.score = score
            scored.append((score, entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in scored[: query.top_k]]

    async def write(self, entry: MemoryEntry) -> None:
        if entry.layer != self.name:
            entry.layer = self.name
        vec = _vectorize(entry.content)
        norm = _norm(vec)
        if norm == 0.0:
            return
        self._entries[entry.key] = entry
        if entry.key in self._vectors:
            self._vectors.move_to_end(entry.key)
        self._vectors[entry.key] = vec
        self._norms[entry.key] = norm
        while len(self._entries) > self._max_entries:
            oldest_key = next(iter(self._entries))
            self._entries.pop(oldest_key, None)
            self._vectors.pop(oldest_key, None)
            self._norms.pop(oldest_key, None)

    async def evict(self, *, max_age_seconds: float | None = None) -> int:
        if not self._entries:
            return 0
        if max_age_seconds is None:
            count = len(self._entries)
            self._entries.clear()
            self._vectors.clear()
            self._norms.clear()
            return count
        cutoff = time.time() - max(0.0, max_age_seconds)
        expired = [
            key
            for key, entry in self._entries.items()
            if entry.created_at < cutoff
        ]
        for key in expired:
            self._entries.pop(key, None)
            self._vectors.pop(key, None)
            self._norms.pop(key, None)
        return len(expired)

    def snapshot(self) -> dict[str, Any]:
        return {
            "layer": self.name,
            "entries": len(self._entries),
            "max_entries": self._max_entries,
        }


def _vectorize(text: str) -> dict[str, float]:
    counts: dict[str, float] = {}
    for token in _tokenize(text):
        counts[token] = counts.get(token, 0.0) + 1.0
    if not counts:
        return counts
    # Plain term-frequency vectors; v2 swaps to TF-IDF or embeddings.
    return counts


def _norm(vec: dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in vec.values()))


def _dot(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(value * b.get(key, 0.0) for key, value in a.items())


# ── Hierarchy facade ────────────────────────────────────────────────────


LAYER_NAMES: tuple[str, ...] = (
    "short_term",
    "long_term",
    "user_memory",
    "agent_memory",
    "shared_cache",
    "vector_memory",
)


@dataclass
class MemoryHierarchyConfig:
    """Knobs the v1 hierarchy exposes. Defaults are RFC-004 §2 conservative."""

    short_term_max: int = 32
    long_term_max: int = 512
    user_max: int = 128
    agent_max: int = 256
    shared_cache_max: int = 256
    vector_max: int = 256
    per_layer_top_k: int = 3
    gather_top_k: int = 6


class MemoryHierarchy:
    """The composed six-layer hierarchy (RFC-004 §2)."""

    def __init__(self, config: MemoryHierarchyConfig | None = None) -> None:
        self._config = config or MemoryHierarchyConfig()
        self._layers: dict[str, MemoryLayer] = {
            "short_term": ShortTermMemory(max_entries=self._config.short_term_max),
            "long_term": LongTermMemory(max_entries=self._config.long_term_max),
            "user_memory": UserMemory(max_entries=self._config.user_max),
            "agent_memory": AgentMemory(max_entries=self._config.agent_max),
            "shared_cache": SharedCache(max_entries=self._config.shared_cache_max),
            "vector_memory": VectorMemory(max_entries=self._config.vector_max),
        }
        self._lock = asyncio.Lock()

    @property
    def layers(self) -> Mapping[str, MemoryLayer]:
        return dict(self._layers)

    def snapshot(self) -> dict[str, Any]:
        return {
            layer_name: layer.snapshot()
            for layer_name, layer in self._layers.items()
        }

    async def write(self, entry: MemoryEntry) -> None:
        if entry.layer not in self._layers:
            return
        try:
            async with self._lock:
                await self._layers[entry.layer].write(entry)
        except Exception as exc:  # ponytail: ADR-007 — never raise into request path
            LOGGER.warning(
                "memory hierarchy write failed for layer %s: %s",
                entry.layer,
                exc,
                exc_info=False,
            )

    async def gather(
        self,
        *,
        query: str,
        tags: list[str] | None = None,
        layers: list[str] | None = None,
        user_id: str | None = None,
        agent: str | None = None,
        top_k: int | None = None,
    ) -> list[MemoryEntry]:
        """Read across the hierarchy and merge results by score.

        Failures in any layer degrade to an empty contribution — the
        caller still receives whatever the surviving layers returned.
        """

        resolved_layers = list(layers) if layers else list(self._layers)
        per_layer_top_k = top_k or self._config.per_layer_top_k
        gather_limit = top_k or self._config.gather_top_k
        metadata: dict[str, Any] = {
            "user_id": user_id,
            "agent": agent,
        }
        mem_query = MemoryQuery(
            query=query,
            top_k=per_layer_top_k,
            tags=list(tags or []),
            layers=resolved_layers,
            metadata=metadata,
        )

        results: list[MemoryEntry] = []
        for layer_name in resolved_layers:
            layer = self._layers.get(layer_name)
            if layer is None:
                continue
            try:
                entries = await layer.read(mem_query)
            except Exception as exc:  # ponytail: ADR-007
                LOGGER.warning(
                    "memory hierarchy read failed for layer %s: %s",
                    layer_name,
                    exc,
                    exc_info=False,
                )
                continue
            results.extend(entries)
        results.sort(key=lambda entry: entry.score, reverse=True)
        return results[: max(1, gather_limit)]

    async def gather_snippets(
        self,
        *,
        query: str,
        tags: list[str] | None = None,
        layers: list[str] | None = None,
        user_id: str | None = None,
        agent: str | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return a list of dict-shaped snippets for the context manager."""

        entries = await self.gather(
            query=query,
            tags=tags,
            layers=layers,
            user_id=user_id,
            agent=agent,
            top_k=top_k,
        )
        return [
            {
                "key": entry.key,
                "content": entry.content,
                "layer": entry.layer,
                "score": entry.score,
                "tags": list(entry.tags),
                "source": entry.source,
                "metadata": dict(entry.metadata),
            }
            for entry in entries
        ]

    async def evict_all(
        self,
        *,
        max_age_seconds: float | None = None,
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for layer_name, layer in self._layers.items():
            try:
                counts[layer_name] = await layer.evict(max_age_seconds=max_age_seconds)
            except Exception as exc:  # ponytail: ADR-007
                LOGGER.warning(
                    "memory hierarchy evict failed for layer %s: %s",
                    layer_name,
                    exc,
                    exc_info=False,
                )
                counts[layer_name] = 0
        return counts

    @staticmethod
    def build_key(*parts: str) -> str:
        """Stable, case-insensitive key for memory entries."""

        return _stable_key(*parts)


# ── Helpers exposed for tests / future wiring ────────────────────────────


__all__ = [
    "LAYER_NAMES",
    "AgentMemory",
    "LongTermMemory",
    "MemoryEntry",
    "MemoryHierarchy",
    "MemoryHierarchyConfig",
    "MemoryLayer",
    "MemoryQuery",
    "SharedCache",
    "ShortTermMemory",
    "UserMemory",
    "VectorMemory",
]
