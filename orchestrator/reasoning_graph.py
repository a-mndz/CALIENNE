"""
calienne — Adaptive Multi-Model Reasoning Orchestrator
Reasoning Knowledge Graph: tracks epistemic failures, claim relationships,
and reasoning patterns using a graph structure.

Tracks failed pipeline executions and claim relationships so subsequent
runs for similar queries can avoid repeating the same mistakes and
validate assertions against known patterns.
"""

from __future__ import annotations

import logging
import math
import uuid

logger = logging.getLogger(__name__)
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_id() -> str:
    return str(uuid.uuid4())


# ── Enums ──────────────────────────────────────────────────────────────────


class NodeType(str, Enum):
    CLAIM = "claim"
    QUERY = "query"
    REASONING_STEP = "reasoning_step"


class EdgeType(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    REFINES = "refines"
    FAILS = "fails"


# ── Data Classes ───────────────────────────────────────────────────────────


@dataclass
class GraphNode:
    node_id: str
    node_type: NodeType
    content: str
    embedding: Optional[list[float]] = None
    created_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    source_id: str
    target_id: str
    edge_type: EdgeType
    weight: float = 1.0
    created_at: datetime = field(default_factory=_utc_now)


# ── Reasoning Graph ────────────────────────────────────────────────────────


class ReasoningGraph:
    """
    In-memory knowledge graph for tracking reasoning patterns, claims,
    and epistemic failures.

    Uses adjacency lists for storage and cosine similarity on embeddings
    for semantic search (Phase 1 uses placeholder embeddings).
    """

    EXPIRY_DAYS = 30

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, list[GraphEdge]] = defaultdict(list)
        self._reverse_edges: dict[str, list[GraphEdge]] = defaultdict(list)

    # ── Core operations ────────────────────────────────────────────────

    def add_node(self, node: GraphNode) -> str:
        """Add a node to the graph, return its node_id."""
        self._nodes[node.node_id] = node
        logger.debug("Added node to reasoning graph: %s", node.node_id, extra={"stage": "reasoning_graph", "node_id": node.node_id, "node_type": node.node_type.value})  # noqa: E501
        return node.node_id

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Retrieve a node by id."""
        return self._nodes.get(node_id)

    def add_edge(self, edge: GraphEdge) -> None:
        """Add an edge between two nodes."""
        self._edges[edge.source_id].append(edge)
        self._reverse_edges[edge.target_id].append(edge)
        logger.debug(
            "Added edge: %s -> %s (%s)",
            edge.source_id,
            edge.target_id,
            edge.edge_type.value,
            extra={"stage": "reasoning_graph", "source_id": edge.source_id, "target_id": edge.target_id, "edge_type": edge.edge_type.value}  # noqa: E501
        )

    def get_edges_from(self, node_id: str) -> list[GraphEdge]:
        """Get all outgoing edges from a node."""
        return list(self._edges.get(node_id, []))

    def get_edges_to(self, node_id: str) -> list[GraphEdge]:
        """Get all incoming edges to a node."""
        return list(self._reverse_edges.get(node_id, []))

    # ── Failure pattern tracking ───────────────────────────────────────

    def record_failure_pattern(
        self,
        query: str,
        explanation: str,
        score: float,
        agent_outputs: dict[str, Any],
        *,
        owner: str = "",
    ) -> str:
        """
        Record a pipeline failure as a query node with failure edges.

        *owner* scopes the pattern to one identity (e.g. the authenticated
        user's email) so query content and agent outputs recorded for one
        account are never replayed into another account's prompts.

        Returns the query node_id.
        """
        query_node = GraphNode(
            node_id=_generate_id(),
            node_type=NodeType.QUERY,
            content=query,
            metadata={
                "explanation": explanation,
                "score": score,
                "agent_outputs": agent_outputs,
                "owner": owner,
            },
        )
        self.add_node(query_node)

        # Create edges to any existing reasoning steps that relate to this query
        for node in self._nodes.values():
            if node.node_type == NodeType.REASONING_STEP:
                edge = GraphEdge(
                    source_id=query_node.node_id,
                    target_id=node.node_id,
                    edge_type=EdgeType.FAILS,
                    weight=max(0.0, 1.0 - score / 10.0),
                )
                self.add_edge(edge)

        logger.info(
            "Recorded failure pattern for query: %s (score=%.2f)",
            query,
            score,
            extra={"stage": "reasoning_graph", "query": query, "score": score, "node_id": query_node.node_id}
        )
        return query_node.node_id

    def get_failure_patterns(self, query: str, *, owner: str = "") -> list[dict[str, Any]]:
        """
        Retrieve relevant failure patterns for similar queries.

        Uses case-insensitive substring containment matching, same as
        EpistemicMemory for backward compatibility. Only nodes whose
        recorded *owner* matches are visible, so one account's failure
        patterns never surface for another account's query.
        """
        query_normalised = query.strip().lower()
        patterns: list[dict[str, Any]] = []

        for node in self._nodes.values():
            if node.node_type != NodeType.QUERY:
                continue
            if node.metadata.get("owner", "") != owner:
                continue
            content_lower = node.content.strip().lower()
            if (
                content_lower == query_normalised
                or query_normalised in content_lower
                or content_lower in query_normalised
            ):
                patterns.append({
                    "query": node.content,
                    "explanation": node.metadata.get("explanation", ""),
                    "score": node.metadata.get("score", 0.0),
                    "agent_outputs": node.metadata.get("agent_outputs", {}),
                    "created_at": node.created_at.isoformat(),
                    "node_id": node.node_id,
                })

        return patterns

    # ── Similarity search ──────────────────────────────────────────────

    @staticmethod
    def _placeholder_embedding(text: str) -> list[float]:
        """
        Generate a deterministic placeholder embedding from text.

        Phase 1: uses character frequency distribution as a simple
        embedding.  Future: replace with sentence-transformers or
        OpenAI embeddings API.
        """
        freq: dict[str, int] = {}
        for ch in text.lower():
            if ch.isalnum():
                freq[ch] = freq.get(ch, 0) + 1

        total = max(1, sum(freq.values()))
        # Fixed 26-dimension vector (a-z)
        embedding = [0.0] * 26
        for ch, count in freq.items():
            idx = ord(ch) - ord("a")
            if 0 <= idx < 26:
                embedding[idx] = count / total
        return embedding

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b) or len(a) == 0:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    def find_similar_nodes(
        self, content: str, top_k: int = 5
    ) -> list[GraphNode]:
        """
        Find semantically similar nodes using cosine similarity on
        embeddings.  Falls back to placeholder embeddings if a node has
        no stored embedding.
        """
        query_emb = self._placeholder_embedding(content)
        scored: list[tuple[float, GraphNode]] = []

        for node in self._nodes.values():
            if node.embedding is not None:
                emb = node.embedding
            else:
                emb = self._placeholder_embedding(node.content)
            sim = self._cosine_similarity(query_emb, emb)
            scored.append((sim, node))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [node for _, node in scored[:top_k]]

    # ── Expiry ─────────────────────────────────────────────────────────

    def expire_old_patterns(self) -> int:
        """Remove nodes and edges older than EXPIRY_DAYS, return count removed."""
        cutoff = _utc_now() - timedelta(days=self.EXPIRY_DAYS)
        expired_ids = [
            nid for nid, node in self._nodes.items()
            if node.created_at < cutoff
        ]

        for nid in expired_ids:
            del self._nodes[nid]
            # Remove associated edges
            for edge in self._edges.pop(nid, []):
                self._reverse_edges[edge.target_id] = [
                    e for e in self._reverse_edges[edge.target_id]
                    if e.source_id != nid
                ]
            for edge in self._reverse_edges.pop(nid, []):
                self._edges[edge.source_id] = [
                    e for e in self._edges[edge.source_id]
                    if e.target_id != nid
                ]

        # Clean up empty entries from defaultdicts
        empty_keys = [k for k, v in self._reverse_edges.items() if not v]
        for k in empty_keys:
            del self._reverse_edges[k]
        empty_keys = [k for k, v in self._edges.items() if not v]
        for k in empty_keys:
            del self._edges[k]

        return len(expired_ids)

    # ── Statistics ─────────────────────────────────────────────────────

    def get_graph_stats(self) -> dict[str, int]:
        """Return statistics: node_count, edge_count by type."""
        edge_counts: dict[str, int] = defaultdict(int)
        for edges in self._edges.values():
            for edge in edges:
                edge_counts[edge.edge_type.value] += 1

        node_counts: dict[str, int] = defaultdict(int)
        for node in self._nodes.values():
            node_counts[node.node_type.value] += 1

        return {
            "node_count": len(self._nodes),
            "edge_count": sum(edge_counts.values()),
            "nodes_by_type": dict(node_counts),
            "edges_by_type": dict(edge_counts),
        }
