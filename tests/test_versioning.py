from __future__ import annotations

import uuid
from pathlib import Path

from core.schemas import TaskGraph, TaskNode
from orchestrator.contracts import InputContract, OutputContract
from orchestrator.versioning import (
    TopologyNormalizer,
    VersionRegistry,
    architecture_version,
    capture_environment_snapshot,
    git_commit,
    graph_fingerprint,
    manifest_metrics,
    resolve_git_commit,
    stamp_graph,
)


def _scratch_file(name: str) -> Path:
    root = Path("C:/Users/amand/AppData/Local/Temp/opencode")
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{uuid.uuid4()}-{name}"


def test_architecture_version_constant() -> None:
    assert architecture_version == "0.1.8"


def test_capture_environment_snapshot_returns_all_four_keys() -> None:
    snapshot = capture_environment_snapshot()

    assert set(snapshot) == {
        "environment.os",
        "environment.python_version",
        "environment.cuda_version",
        "environment.container",
    }
    assert snapshot["environment.os"]  # non-empty best-effort platform string
    assert snapshot["environment.python_version"]
    assert snapshot["environment.cuda_version"] is None or isinstance(
        snapshot["environment.cuda_version"], str
    )
    assert isinstance(snapshot["environment.container"], bool)


def test_manifest_metrics_matches_module_constants_and_stubs_graph_fields() -> None:
    metrics = manifest_metrics(graph=None)

    assert metrics["manifest.architecture_version"] == architecture_version
    assert metrics["manifest.git_commit"] == git_commit
    assert metrics["manifest.graph_version"] is None  # ponytail: Step 19 stub
    assert metrics["manifest.graph_fingerprint"] is None  # ponytail: Step 19 stub


def _versioning_graph(*, renamed: bool = False, reverse_nodes: bool = False) -> TaskGraph:
    first_id = "source-renamed" if renamed else "source"
    final_id = "sink-renamed" if renamed else "sink"
    source = TaskNode(
        task_id=first_id,
        objective="Collect inputs",
        skills_required=["researcher", "academic"],
        input_contract=InputContract(required_fields=["request", "context"]),
        output_contract=OutputContract(
            produced_fields=["evidence", "summary"],
            types={"summary": "string", "evidence": "list"},
        ),
    )
    sink = TaskNode(
        task_id=final_id,
        objective="Produce answer",
        depends_on=[first_id],
        can_run_parallel=False,
        input_contract=InputContract(required_fields=["summary", "evidence"]),
        output_contract=OutputContract(
            produced_fields=["final_response"],
            types={"final_response": "string"},
        ),
    )
    nodes = [sink, source] if reverse_nodes else [source, sink]
    return TaskGraph(nodes=nodes, root_task_id=first_id, final_task_id=final_id)


def test_graph_fingerprint_is_deterministic_for_structurally_identical_dags() -> None:
    original = _versioning_graph()
    equivalent = _versioning_graph(renamed=True, reverse_nodes=True)
    equivalent.nodes[1].skills_required.reverse()
    equivalent.nodes[1].input_contract.required_fields.reverse()

    assert TopologyNormalizer.normalize(original) == TopologyNormalizer.normalize(equivalent)
    assert graph_fingerprint(original) == graph_fingerprint(equivalent)
    assert len(graph_fingerprint(original)) == 64


def test_graph_fingerprint_changes_when_contract_changes() -> None:
    original = _versioning_graph()
    changed = _versioning_graph(renamed=True)
    changed.nodes[-1].output_contract.types["final_response"] = "object"

    assert graph_fingerprint(original) != graph_fingerprint(changed)


def test_version_registry_is_stable_per_key_and_monotonic_for_new_keys() -> None:
    registry = VersionRegistry()

    first = registry.get_or_create(
        planner_version="planner-v1",
        strategy_version="strategy-v1",
        contract_version="contracts-v1",
    )
    repeated = registry.get_or_create(
        planner_version="planner-v1",
        strategy_version="strategy-v1",
        contract_version="contracts-v1",
    )
    second = registry.get_or_create(
        planner_version="planner-v2",
        strategy_version="strategy-v1",
        contract_version="contracts-v1",
    )

    assert first == repeated == "v1"
    assert second == "v2"
    assert registry.current == 2


def test_stamp_graph_sets_version_and_fingerprint() -> None:
    graph = _versioning_graph()
    registry = VersionRegistry(start=4)

    stamped = stamp_graph(
        graph,
        planner_version="planner-v1",
        strategy_version="strategy-v1",
        registry=registry,
    )

    assert stamped is graph
    assert graph.graph_version == "v5"
    assert graph.graph_fingerprint == graph_fingerprint(graph)


def test_git_commit_fallback_chain_uses_calienne_env_first() -> None:
    ci_file = _scratch_file(".git_commit_sha")
    ci_file.write_text("ci-file-sha", encoding="utf-8")

    commit = resolve_git_commit(
        env={
            "CALIENNE_GIT_COMMIT": "explicit-sha",
            "GIT_COMMIT": "generic-sha",
            "GITHUB_SHA": "github-sha",
        },
        ci_commit_file=ci_file,
    )

    assert commit == "explicit-sha"


def test_git_commit_fallback_chain_uses_generic_env_before_ci_metadata() -> None:
    ci_file = _scratch_file(".git_commit_sha")
    ci_file.write_text("ci-file-sha", encoding="utf-8")

    commit = resolve_git_commit(
        env={
            "GIT_COMMIT": "generic-sha",
            "GITHUB_SHA": "github-sha",
        },
        ci_commit_file=ci_file,
    )

    assert commit == "generic-sha"


def test_git_commit_fallback_chain_uses_ci_metadata_before_unknown() -> None:
    ci_file = _scratch_file(".git_commit_sha")
    ci_file.write_text("ci-file-sha", encoding="utf-8")

    commit = resolve_git_commit(env={}, ci_commit_file=ci_file)

    assert commit == "ci-file-sha"


def test_git_commit_fallback_chain_returns_unknown_when_nothing_available() -> None:
    commit = resolve_git_commit(env={}, ci_commit_file=_scratch_file("missing.git_commit_sha"))

    assert commit == "unknown"
