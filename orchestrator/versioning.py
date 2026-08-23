"""Version stamps, canonical graph fingerprints, and graph versions."""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from threading import Lock
from typing import Any

from core.schemas import TaskGraph, TaskNode, VersionStamp

architecture_version = "0.1.8"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CI_GIT_COMMIT_FILE = _REPO_ROOT / ".git_commit_sha"


def _read_ci_metadata(*, env: dict[str, str] | None = None, ci_commit_file: Path | None = None) -> str | None:
    environment = os.environ if env is None else env
    for key in ("GITHUB_SHA", "CI_COMMIT_SHA", "BUILD_SOURCEVERSION"):
        value = environment.get(key)
        if value:
            return value

    candidate = ci_commit_file or _CI_GIT_COMMIT_FILE
    try:
        if candidate.is_file():
            value = candidate.read_text(encoding="utf-8").strip()
            if value:
                return value
    except OSError:
        return None
    return None


def resolve_git_commit(*, env: dict[str, str] | None = None, ci_commit_file: Path | None = None) -> str:
    environment = os.environ if env is None else env
    return (
        environment.get("CALIENNE_GIT_COMMIT")
        or environment.get("GIT_COMMIT")
        or _read_ci_metadata(env=environment, ci_commit_file=ci_commit_file)
        or "unknown"
    )


git_commit = resolve_git_commit()


class TopologyNormalizer:
    """Convert a DAG into canonical, planner-independent JSON data."""

    @classmethod
    def normalize(cls, graph: TaskGraph) -> dict[str, Any]:
        node_map = {node.task_id: node for node in graph.nodes}
        unknown_dependencies = sorted(
            dependency
            for node in graph.nodes
            for dependency in node.depends_on
            if dependency not in node_map
        )
        if unknown_dependencies:
            raise ValueError(
                "Cannot fingerprint graph with unknown dependencies: "
                + ", ".join(unknown_dependencies)
            )

        dependents: dict[str, list[str]] = defaultdict(list)
        indegree = {node_id: 0 for node_id in node_map}
        for node in graph.nodes:
            indegree[node.task_id] = len(node.depends_on)
            for dependency in node.depends_on:
                dependents[dependency].append(node.task_id)

        signatures = cls._structural_signatures(node_map, dependents)
        ready = [node_id for node_id, degree in indegree.items() if degree == 0]
        ordered: list[str] = []
        while ready:
            ready.sort(
                key=lambda node_id: (
                    signatures[node_id],
                    json.dumps(
                        cls._node_payload(node_map[node_id]),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ),
                )
            )
            node_id = ready.pop(0)
            ordered.append(node_id)
            for dependent in dependents[node_id]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)

        if len(ordered) != len(node_map):
            raise ValueError("Cannot fingerprint a cyclic graph")

        positions = {node_id: index for index, node_id in enumerate(ordered)}
        nodes = []
        for node_id in ordered:
            node = node_map[node_id]
            payload = cls._node_payload(node)
            payload["id"] = positions[node_id]
            payload["depends_on"] = sorted(positions[dependency] for dependency in node.depends_on)
            nodes.append(payload)

        return {
            "nodes": nodes,
            "edges": sorted(
                [positions[dependency], positions[node.task_id]]
                for node in graph.nodes
                for dependency in node.depends_on
            ),
            "root": positions.get(graph.root_task_id),
            "final": positions.get(graph.final_task_id),
        }

    @classmethod
    def canonical_json(cls, graph: TaskGraph) -> str:
        return json.dumps(
            cls.normalize(graph),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    @classmethod
    def _structural_signatures(
        cls,
        node_map: dict[str, TaskNode],
        dependents: dict[str, list[str]],
    ) -> dict[str, str]:
        signatures = {
            node_id: cls._hash_payload(cls._node_payload(node))
            for node_id, node in node_map.items()
        }
        for _ in range(max(1, len(node_map))):
            updated = {
                node_id: cls._hash_payload(
                    {
                        "node": cls._node_payload(node),
                        "parents": sorted(signatures[parent] for parent in node.depends_on),
                        "children": sorted(signatures[child] for child in dependents[node_id]),
                    }
                )
                for node_id, node in node_map.items()
            }
            if updated == signatures:
                break
            signatures = updated
        return signatures

    @staticmethod
    def _node_payload(node: TaskNode) -> dict[str, Any]:
        return {
            "objective": node.objective,
            "skills_required": sorted(node.skills_required),
            "model_tier": node.model_tier,
            "can_run_parallel": node.can_run_parallel,
            "expected_tokens": node.expected_tokens,
            "expected_latency_ms": node.expected_latency_ms,
            "priority": node.priority,
            "contracts": {
                "input": (
                    TopologyNormalizer._canonicalize(
                        node.input_contract.model_dump(mode="json", exclude_none=False)
                    )
                    if node.input_contract is not None
                    else None
                ),
                "output": (
                    TopologyNormalizer._canonicalize(
                        node.output_contract.model_dump(mode="json", exclude_none=False)
                    )
                    if node.output_contract is not None
                    else None
                ),
                "failure": (
                    TopologyNormalizer._canonicalize(
                        node.failure_contract.model_dump(mode="json", exclude_none=False)
                    )
                    if node.failure_contract is not None
                    else None
                ),
            },
        }

    @staticmethod
    def _canonicalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: TopologyNormalizer._canonicalize(item)
                for key, item in sorted(value.items())
            }
        if isinstance(value, list):
            normalized = [TopologyNormalizer._canonicalize(item) for item in value]
            return sorted(
                normalized,
                key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
            )
        return value

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def graph_fingerprint(graph: TaskGraph) -> str:
    """Return the SHA-256 digest of the graph's canonical topology."""

    return hashlib.sha256(TopologyNormalizer.canonical_json(graph).encode("utf-8")).hexdigest()


class VersionRegistry:
    """Process-local monotonic graph-version registry."""

    def __init__(self, *, start: int = 0) -> None:
        self._counter = max(0, start)
        self._versions: dict[tuple[str | None, str | None, str | None], str] = {}
        self._lock = Lock()

    def get_or_create(
        self,
        *,
        planner_version: str | None,
        strategy_version: str | None,
        contract_version: str | None,
    ) -> str:
        key = (planner_version, strategy_version, contract_version)
        with self._lock:
            existing = self._versions.get(key)
            if existing is not None:
                return existing
            self._counter += 1
            version = f"v{self._counter}"
            self._versions[key] = version
            return version

    @property
    def current(self) -> int:
        with self._lock:
            return self._counter


VERSION_REGISTRY = VersionRegistry()


def stamp_graph(
    graph: TaskGraph,
    *,
    planner_version: str | None = None,
    strategy_version: str | None = None,
    contract_version: str | None = "contracts-v1",
    registry: VersionRegistry | None = None,
) -> TaskGraph:
    """Stamp a graph after its final mutation and return the same graph."""

    resolved_planner_version = planner_version or graph.planner_version
    graph.planner_version = resolved_planner_version
    graph.graph_fingerprint = graph_fingerprint(graph)
    graph.graph_version = (registry or VERSION_REGISTRY).get_or_create(
        planner_version=resolved_planner_version,
        strategy_version=strategy_version,
        contract_version=contract_version,
    )
    return graph


def build_version_stamp(
    graph: TaskGraph,
    *,
    prompt_versions: dict[str, str] | None = None,
    scheduler_version: str | None = "scheduler-v1",
    routing_version: str | None = "routing-v1",
    capabilities_version: str | None = "1",
    contracts_version: str | None = "contracts-v1",
    resource_policy_version: str | None = "1",
    prediction_model_version: str | None = None,
) -> VersionStamp:
    return VersionStamp(
        architecture_version=architecture_version,
        planner_version=graph.planner_version,
        scheduler_version=scheduler_version,
        routing_version=routing_version,
        capabilities_version=capabilities_version,
        prompt_versions=deepcopy(prompt_versions or {}),
        contracts_version=contracts_version,
        resource_policy_version=resource_policy_version,
        prediction_model_version=prediction_model_version,
        graph_version=graph.graph_version,
        graph_fingerprint=graph.graph_fingerprint,
    )


def capture_environment_snapshot() -> dict[str, Any]:
    """Return the process-start host snapshot in metric namespace form."""

    from orchestrator.execution_manifest import host_primitives

    return {
        "environment.os": host_primitives.os,
        "environment.python_version": host_primitives.python_version,
        "environment.cuda_version": host_primitives.cuda_version,
        "environment.container": host_primitives.container,
    }


environment_snapshot: dict[str, Any] = capture_environment_snapshot()


def manifest_metrics(*, graph: Any = None) -> dict[str, Any]:
    """Return ``manifest.*`` metrics for a stamped graph."""

    return {
        "manifest.architecture_version": architecture_version,
        "manifest.graph_version": getattr(graph, "graph_version", None),
        "manifest.graph_fingerprint": getattr(graph, "graph_fingerprint", None),
        "manifest.git_commit": git_commit,
    }
