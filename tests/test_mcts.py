"""Tests for Tree-of-Thoughts / MCTS Search guided by PRMs (P2-04)."""

from __future__ import annotations

from orchestrator.mcts import MCTSNode, ProcessRewardVerifier, TreeOfThoughtsMCTS


def test_mcts_node_uct_and_child_selection() -> None:
    root = MCTSNode(state="root", visits=10, value=5.0)
    c1 = MCTSNode(state="child1", parent=root, visits=4, value=3.0)
    c2 = MCTSNode(state="child2", parent=root, visits=6, value=2.0)
    root.children = [c1, c2]

    uct1 = c1.uct()
    uct2 = c2.uct()
    assert uct1 > uct2
    assert root.select_best_child() == c1


def test_prm_verifier_fallacy_detection() -> None:
    prm = ProcessRewardVerifier()
    score_valid = prm.score_step("Let x = 2", "Therefore substituting x gives 2 * 2 = 4")
    score_fallacy = prm.score_step("Let x = 0", "Divide by x which is a division by zero error")
    assert score_valid > score_fallacy
    assert score_fallacy <= 0.2


def test_tree_of_thoughts_mcts_search() -> None:
    mcts = TreeOfThoughtsMCTS(iterations=25)

    def mock_expand(state: str) -> list[str]:
        if "root" in state and "step 1" not in state:
            return ["Step 1: factorize equation into (x-1)(x-2)", "Invalid step: contradiction"]
        elif "Step 1" in state and "step 2" not in state:
            return ["Step 2: solve roots therefore x=1 or x=2. Final answer."]
        return []

    path = mcts.search("Solve root equation", expand_fn=mock_expand, iterations=30)
    assert len(path) >= 1
    # PRM should steer the winning path away from contradiction
    assert any("factorize" in step for step in path)
    assert not any("contradiction" in step for step in path)
