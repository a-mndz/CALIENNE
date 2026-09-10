"""PlannerCommand union and node transformation primitives.

Supports LangGraph-style Command/Send and dynamic worker fan-out (RFC-003).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Union

from pydantic import Field

from core.base import CalienneBaseModel

if TYPE_CHECKING:
    from core.schemas import TaskNode


class DispatchNode(CalienneBaseModel):
    """Command to dispatch work to a single worker node."""

    worker: str
    payload: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)

    def __init__(
        self,
        worker: str,
        payload: dict[str, Any] | None = None,
        task_id: str | None = None,
        depends_on: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            worker=worker,
            payload=payload if payload is not None else kwargs.get("payload", {}),
            task_id=task_id if task_id is not None else kwargs.get("task_id"),
            depends_on=depends_on if depends_on is not None else kwargs.get("depends_on", []),
            **kwargs,
        )


class SkipNode(CalienneBaseModel):
    """Command to omit a stage/task and rewire dependents to upstream dependencies."""

    stage: str

    def __init__(self, stage: str, **kwargs: Any) -> None:
        super().__init__(stage=stage, **kwargs)


class FanOut(CalienneBaseModel):
    """Command to fan out parallel sub-tasks across multiple payloads."""

    worker: str
    payloads: list[dict[str, Any]] = Field(default_factory=list)
    task_prefix: str | None = None
    depends_on: list[str] = Field(default_factory=list)

    def __init__(
        self,
        worker: str,
        payloads: list[dict[str, Any]] | None = None,
        task_prefix: str | None = None,
        depends_on: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            worker=worker,
            payloads=payloads if payloads is not None else kwargs.get("payloads", []),
            task_prefix=task_prefix if task_prefix is not None else kwargs.get("task_prefix"),
            depends_on=depends_on if depends_on is not None else kwargs.get("depends_on", []),
            **kwargs,
        )


PlannerCommand = Union[DispatchNode, SkipNode, FanOut]


def apply_skip_node(nodes: list[TaskNode], stage: str) -> list[TaskNode]:
    """Omit node with task_id == stage and rewire dependents to omitted node's depends_on."""
    target_node = next((n for n in nodes if n.task_id == stage), None)
    if target_node is None:
        return nodes

    skipped_deps = list(target_node.depends_on)
    new_nodes: list[TaskNode] = []
    for node in nodes:
        if node.task_id == stage:
            continue
        if stage in node.depends_on:
            new_deps: list[str] = []
            for dep in node.depends_on:
                if dep == stage:
                    for d in skipped_deps:
                        if d not in new_deps and d != node.task_id:
                            new_deps.append(d)
                elif dep not in new_deps:
                    new_deps.append(dep)
            node = node.model_copy(update={"depends_on": new_deps})
        new_nodes.append(node)
    return new_nodes
