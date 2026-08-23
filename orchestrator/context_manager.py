"""Per-node context window assembly for the DAG runtime."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import Field

from core.base import CalienneBaseModel
from core.schemas import PipelineBudget, StrategicPlan, TaskNode, TaskProfile
from orchestrator.contracts import InputContract
from orchestrator.memory_hierarchy import MemoryHierarchy
from orchestrator.memory_manager import MemoryManager, SummarizationStrategy
from orchestrator.retrieval import (
    RetrievalRequest,
    RetrievalResult,
    RetrievalService,
)
from orchestrator.retrieval import (
    should_retrieve as retrieval_should_retrieve,
)

RetrievalCallable = Callable[..., list[dict[str, Any]] | list[str]]


class RetrievedSnippet(CalienneBaseModel):
    """A retrieved or injected snippet carried into a node context window."""

    source: str = "memory"
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextWindow(CalienneBaseModel):
    """Bounded context prepared for a single node execution."""

    node_id: str = ""
    objective: str = ""
    messages: list[dict[str, str]] = Field(default_factory=list)
    incoming_outputs: dict[str, Any] = Field(default_factory=dict)
    input_contract: InputContract | None = None
    retrieved_snippets: list[RetrievedSnippet] = Field(default_factory=list)
    compressed_history: str | None = None
    retrieval_result: RetrievalResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextManager:
    """Assemble bounded per-node context windows with deterministic fallback."""

    DEFAULT_MAX_WINDOW_TOKENS = 4_000
    DEFAULT_RECENT_TURNS = 4
    DEFAULT_IMPORTANT_OLDER_TURNS = 2

    def __init__(
        self,
        *,
        memory_manager: MemoryManager | None = None,
        retrieval_provider: RetrievalCallable | None = None,
        retrieval_service: RetrievalService | None = None,
        memory_hierarchy: MemoryHierarchy | None = None,
        max_window_tokens: int = DEFAULT_MAX_WINDOW_TOKENS,
        recent_turns: int = DEFAULT_RECENT_TURNS,
        important_older_turns: int = DEFAULT_IMPORTANT_OLDER_TURNS,
    ) -> None:
        self._memory_manager = memory_manager or MemoryManager()
        self._retrieval_provider = retrieval_provider
        self._retrieval_service = retrieval_service
        self._memory_hierarchy = memory_hierarchy
        self._max_window_tokens = max(256, max_window_tokens)
        self._recent_turns = max(1, recent_turns)
        self._important_older_turns = max(0, important_older_turns)

    async def assemble_window(
        self,
        node: TaskNode,
        *,
        user_query: str,
        task_profile: TaskProfile | None = None,
        strategic_plan: StrategicPlan | None = None,
        history: list[dict[str, str]] | None = None,
        history_summary: str | None = None,
        prior_results: dict[str, Any] | None = None,
        budget: PipelineBudget | None = None,
        code_context_snippets: list[str] | None = None,
        uncertainty_triggered_retrieval: bool = False,
    ) -> ContextWindow:
        """Build the rich context window used when the context flag is enabled."""

        normalized_history = list(history or [])
        constraints, turns = self._split_constraints(normalized_history)
        recent_turns = turns[-self._recent_turns :]
        older_turns = turns[: max(0, len(turns) - len(recent_turns))]
        kept_older_turns, compressed_summary = self._rank_and_compress_history(
            older_turns,
            user_query=user_query,
            objective=node.objective,
        )
        if history_summary:
            compressed_summary = (
                f"{history_summary} {compressed_summary}".strip()
                if compressed_summary
                else history_summary
            )

        incoming_outputs = self._build_incoming_outputs(
            user_query=user_query,
            task_profile=task_profile,
            strategic_plan=strategic_plan,
            prior_results=prior_results,
        )
        retrieval_result, retrieved_snippets = await self._collect_retrieval(
            node=node,
            task_profile=task_profile,
            user_query=user_query,
            incoming_outputs=incoming_outputs,
            code_context_snippets=code_context_snippets,
            uncertainty_triggered=uncertainty_triggered_retrieval,
        )
        memory_snippets = await self._collect_memory(
            user_query=user_query,
            node=node,
            task_profile=task_profile,
        )

        messages = list(constraints)
        messages.append(
            {
                "role": "system",
                "content": f"Node {node.task_id}: {node.objective}",
            }
        )
        messages.extend(kept_older_turns)
        messages.extend(recent_turns)
        if user_query and not any(
            msg.get("role") == "user" and msg.get("content") == user_query
            for msg in messages
        ):
            messages.append({"role": "user", "content": user_query})
        if compressed_summary:
            messages.append(
                {
                    "role": "system",
                    "content": f"[Compressed history] {compressed_summary}",
                }
            )
        for snippet in retrieved_snippets:
            messages.append(
                {
                    "role": "system",
                    "content": f"[{snippet.source}] {snippet.content}",
                }
            )
        for snippet in memory_snippets:
            messages.append(
                {
                    "role": "system",
                    "content": f"[{snippet.source}] {snippet.content}",
                }
            )

        bounded_messages = self._bound_messages(messages, budget=budget)
        return ContextWindow(
            node_id=node.task_id,
            objective=node.objective,
            messages=bounded_messages,
            incoming_outputs=incoming_outputs,
            input_contract=node.input_contract,
            retrieved_snippets=[*retrieved_snippets, *memory_snippets],
            compressed_history=compressed_summary,
            retrieval_result=retrieval_result,
            metadata={
                "route": task_profile.task_type if task_profile is not None else "general",
                "retrieval_enabled": bool(retrieved_snippets),
                "recent_turn_count": len(recent_turns),
                "older_turn_count": len(older_turns),
                "memory_hits": [snippet.model_dump() for snippet in memory_snippets],
            },
        )

    def minimal_window(
        self,
        node: TaskNode,
        *,
        user_query: str,
        task_profile: TaskProfile | None = None,
        strategic_plan: StrategicPlan | None = None,
        history: list[dict[str, str]] | None = None,
        prior_results: dict[str, Any] | None = None,
    ) -> ContextWindow:
        """Return the deterministic minimal window used when context is off."""

        normalized_history = list(history or [])
        constraints, turns = self._split_constraints(normalized_history)
        messages = list(constraints)
        messages.extend(turns[-2:])
        if user_query and not any(
            msg.get("role") == "user" and msg.get("content") == user_query
            for msg in messages
        ):
            messages.append({"role": "user", "content": user_query})
        return ContextWindow(
            node_id=node.task_id,
            objective=node.objective,
            messages=messages,
            incoming_outputs=self._build_incoming_outputs(
                user_query=user_query,
                task_profile=task_profile,
                strategic_plan=strategic_plan,
                prior_results=prior_results,
            ),
            input_contract=node.input_contract,
            retrieved_snippets=[],
            compressed_history=None,
            metadata={"route": task_profile.task_type if task_profile is not None else "general"},
        )

    def _build_incoming_outputs(
        self,
        *,
        user_query: str,
        task_profile: TaskProfile | None,
        strategic_plan: StrategicPlan | None,
        prior_results: dict[str, Any] | None,
    ) -> dict[str, Any]:
        incoming: dict[str, Any] = {"request": user_query}
        if task_profile is not None:
            incoming["task_profile"] = task_profile
        if strategic_plan is not None:
            incoming["strategic_plan"] = strategic_plan
        for result in (prior_results or {}).values():
            if not isinstance(result, dict):
                continue
            produced_outputs = result.get("produced_outputs")
            if isinstance(produced_outputs, dict):
                incoming.update(produced_outputs)
        return incoming

    @staticmethod
    def _split_constraints(
        history: list[dict[str, str]],
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        constraints: list[dict[str, str]] = []
        turns: list[dict[str, str]] = []
        for message in history:
            role = message.get("role", "")
            if role in {"system", "developer"}:
                constraints.append(message)
            else:
                turns.append(message)
        return constraints, turns

    def _rank_and_compress_history(
        self,
        older_turns: list[dict[str, str]],
        *,
        user_query: str,
        objective: str,
    ) -> tuple[list[dict[str, str]], str | None]:
        if not older_turns:
            return [], None

        ranked = sorted(
            older_turns,
            key=lambda message: self._importance_score(
                message,
                user_query=user_query,
                objective=objective,
            ),
            reverse=True,
        )
        kept = ranked[: self._important_older_turns]
        low_priority = ranked[self._important_older_turns :]
        if not low_priority:
            return kept, None

        _, summary = self._memory_manager.compress_history(
            low_priority,
            strategy=SummarizationStrategy.SEMANTIC_COMPRESSION,
            max_limit=self._max_window_tokens,
        )
        return kept, summary

    @staticmethod
    def _importance_score(
        message: dict[str, str],
        *,
        user_query: str,
        objective: str,
    ) -> tuple[int, int, int]:
        content = message.get("content", "").lower()
        role = message.get("role", "")
        query_terms = {term for term in user_query.lower().split() if len(term) > 3}
        objective_terms = {term for term in objective.lower().split() if len(term) > 3}
        overlap = len(query_terms.intersection(content.split())) + len(
            objective_terms.intersection(content.split())
        )
        role_weight = 3 if role == "user" else 1
        length_weight = min(len(content.split()), 20)
        return overlap, role_weight, length_weight

    async def _collect_retrieval(
        self,
        *,
        node: TaskNode,
        task_profile: TaskProfile | None,
        user_query: str,
        incoming_outputs: dict[str, Any],
        code_context_snippets: list[str] | None,
        uncertainty_triggered: bool = False,
    ) -> tuple[RetrievalResult | None, list[RetrievedSnippet]]:
        snippets: list[RetrievedSnippet] = []

        if code_context_snippets and task_profile is not None and task_profile.requires_code_context:
            snippets.extend(
                RetrievedSnippet(source="code_context", content=snippet)
                for snippet in code_context_snippets
                if snippet
            )

        if task_profile is None or not self._should_retrieve(task_profile):
            return None, snippets

        if self._retrieval_service is not None:
            return await self._collect_via_service(
                node=node,
                task_profile=task_profile,
                user_query=user_query,
                incoming_outputs=incoming_outputs,
                snippets=snippets,
                uncertainty_triggered=uncertainty_triggered,
            )

        if uncertainty_triggered and task_profile is not None and not self._should_retrieve(task_profile):
            snippets.append(
                RetrievedSnippet(
                    source="retrieval_forced",
                    content="",
                    metadata={"forced": True, "route": task_profile.task_type},
                )
            )

        return self._collect_via_legacy_provider(
            node=node,
            task_profile=task_profile,
            user_query=user_query,
            incoming_outputs=incoming_outputs,
            snippets=snippets,
        )

    @staticmethod
    def _should_retrieve(task_profile: TaskProfile) -> bool:
        if task_profile.task_type == "research":
            return True
        if task_profile.task_type == "general" and task_profile.requires_rag:
            return True
        return False

    async def _collect_via_service(
        self,
        *,
        node: TaskNode,
        task_profile: TaskProfile,
        user_query: str,
        incoming_outputs: dict[str, Any],
        snippets: list[RetrievedSnippet],
        uncertainty_triggered: bool = False,
    ) -> tuple[RetrievalResult | None, list[RetrievedSnippet]]:
        request = RetrievalRequest(
            query=user_query,
            task_profile=task_profile,
            node_id=node.task_id,
            uncertainty_triggered=uncertainty_triggered,
        )
        result = await self._retrieval_service.retrieve(request)
        for source in result.sources:
            snippets.append(
                RetrievedSnippet(
                    source="retrieval",
                    content=source.excerpt or source.title or source.url or "",
                    metadata={
                        "url": source.url,
                        "title": source.title,
                        "credibility_score": source.credibility_score,
                        "freshness_score": source.freshness_score,
                        "relevance_score": source.relevance_score,
                        "consensus_score": source.consensus_score,
                        "final_score": source.final_score,
                    },
                )
            )
        return result, snippets

    def _collect_via_legacy_provider(
        self,
        *,
        node: TaskNode,
        task_profile: TaskProfile,
        user_query: str,
        incoming_outputs: dict[str, Any],
        snippets: list[RetrievedSnippet],
    ) -> tuple[RetrievalResult | None, list[RetrievedSnippet]]:
        if self._retrieval_provider is None:
            return None, snippets

        retrieved = self._retrieval_provider(
            query=user_query,
            node=node,
            task_profile=task_profile,
            incoming_outputs=incoming_outputs,
        )
        for item in retrieved:
            if isinstance(item, str):
                snippets.append(RetrievedSnippet(source="retrieval", content=item))
            elif isinstance(item, dict):
                snippets.append(
                    RetrievedSnippet(
                        source=str(item.get("source", "retrieval")),
                        content=str(item.get("content", item.get("excerpt", ""))),
                        metadata={
                            key: value
                            for key, value in item.items()
                            if key not in {"source", "content", "excerpt"}
                        },
                    )
                )
        return None, snippets

    async def _collect_memory(
        self,
        *,
        user_query: str,
        node: TaskNode,
        task_profile: TaskProfile | None,
    ) -> list[RetrievedSnippet]:
        """Pull memory-derived snippets when a hierarchy is wired in (Step 16)."""

        if self._memory_hierarchy is None or not user_query:
            return []

        tags = [task_profile.task_type] if task_profile is not None else []
        try:
            entries = await self._memory_hierarchy.gather(
                query=user_query,
                tags=tags,
                agent=node.task_id,
            )
        except Exception:
            return []

        snippets: list[RetrievedSnippet] = []
        for entry in entries:
            if entry.score <= 0.0:
                continue
            snippets.append(
                RetrievedSnippet(
                    source=f"memory:{entry.layer}",
                    content=entry.content,
                    metadata={
                        "key": entry.key,
                        "layer": entry.layer,
                        "score": entry.score,
                        "tags": list(entry.tags),
                    },
                )
            )
        return snippets

    def _bound_messages(
        self,
        messages: list[dict[str, str]],
        *,
        budget: PipelineBudget | None,
    ) -> list[dict[str, str]]:
        token_limit = self._max_window_tokens
        if budget is not None:
            token_limit = min(token_limit, max(256, budget.total_tokens))
        if self._memory_manager.track_tokens(messages) <= token_limit:
            return messages

        constraints, turns = self._split_constraints(messages)
        compressed_turns, summary = self._memory_manager.compress_history(
            turns,
            strategy=SummarizationStrategy.HIERARCHICAL,
            max_limit=token_limit,
        )
        bounded = list(constraints) + compressed_turns
        if summary:
            bounded.append(
                {
                    "role": "system",
                    "content": f"[Window summary] {summary}",
                }
            )
        return bounded
