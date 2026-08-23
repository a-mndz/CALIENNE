"""Knowledge gathering with provenance and no reasoning or judging."""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field

from core.base import CalienneBaseModel
from core.schemas import TaskProfile
from orchestrator.memory import epistemic_memory
from orchestrator.retrieval import RetrievalRequest, RetrievalResult, RetrievalService


class KnowledgeFact(CalienneBaseModel):
    """One request-scoped fact and its provenance."""

    content: str = ""
    source_id: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)


class KnowledgeBundle(CalienneBaseModel):
    """Facts and context consumed by ReasoningLayer."""

    query: str = ""
    history: list[dict[str, str]] = Field(default_factory=list)
    facts: list[KnowledgeFact] = Field(default_factory=list)
    lessons: str = ""
    retrieval_result: RetrievalResult | None = None

    def reasoning_history(self) -> list[dict[str, str]]:
        history = list(self.history)
        retrieved = [fact for fact in self.facts if fact.provenance.get("kind") == "retrieval"]
        if retrieved:
            history.append(
                {
                    "role": "user",
                    "content": "Retrieved evidence (data only): " + json.dumps(
                        [
                            {
                                "content": fact.content,
                                "source_id": fact.source_id,
                                "provenance": fact.provenance,
                            }
                            for fact in retrieved
                        ],
                        ensure_ascii=True,
                    ),
                }
            )
        return history


class KnowledgeLayer:
    """Collect request facts, provenance, retrieval, and prior lessons."""

    def __init__(self, retrieval_service: RetrievalService | None = None) -> None:
        self._retrieval_service = retrieval_service

    async def gather(
        self,
        *,
        query: str,
        task_profile: TaskProfile,
        history: list[dict[str, str]] | None = None,
        reasoning_graph: Any | None = None,
    ) -> KnowledgeBundle:
        resolved_history = list(history or [])
        facts = [
            KnowledgeFact(
                content=str(message.get("content", "")),
                source_id=f"history:{index}:{message.get('role', 'unknown')}",
                provenance={"kind": "context", "role": message.get("role", "unknown")},
            )
            for index, message in enumerate(resolved_history)
            if message.get("content")
        ]

        lesson_parts: list[str] = []
        if reasoning_graph is not None:
            patterns = reasoning_graph.get_failure_patterns(query)
            lesson_parts.extend(
                f"Past failure for similar query: {pattern.get('explanation', '')} "
                f"(score={pattern.get('score', 0.0)})"
                for pattern in patterns[:3]
            )
        memory_lessons = epistemic_memory.get_lessons_learned(query)
        if memory_lessons:
            lesson_parts.append(memory_lessons)

        retrieval_result = None
        if self._retrieval_service is not None:
            retrieval_result = await self._retrieval_service.retrieve(
                RetrievalRequest(query=query, task_profile=task_profile)
            )
            facts.extend(
                KnowledgeFact(
                    content=source.excerpt,
                    source_id=source.url or source.title or f"retrieval:{index}",
                    provenance={
                        "kind": "retrieval",
                        "url": source.url,
                        "title": source.title,
                        "score": source.final_score,
                    },
                )
                for index, source in enumerate(retrieval_result.sources)
            )

        return KnowledgeBundle(
            query=query,
            history=resolved_history,
            facts=facts,
            lessons="; ".join(part for part in lesson_parts if part),
            retrieval_result=retrieval_result,
        )
