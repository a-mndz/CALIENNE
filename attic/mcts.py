"""Tree-of-Thoughts (ToT) / Monte Carlo Tree Search (MCTS) guided by PRMs (P2-04).

Implements frontier multi-step reasoning tree search:
1. MCTSNode: Tree node maintaining UCT (Upper Confidence bounds for Trees) statistics.
2. ProcessRewardVerifier (PRM): Step-level verifier scoring intermediate reasoning transitions.
3. TreeOfThoughtsMCTS: Search orchestrator performing Selection, Expansion, Simulation,
   and Backpropagation to discover verified reasoning paths.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence


@dataclass
class MCTSNode:
    """A node in the reasoning search tree."""
    state: str
    parent: Optional[MCTSNode] = None
    children: list[MCTSNode] = field(default_factory=list)
    visits: int = 0
    value: float = 0.0
    prm_score: float = 1.0
    is_terminal: bool = False
    step_index: int = 0

    @property
    def q_value(self) -> float:
        """Average reward."""
        return self.value / self.visits if self.visits > 0 else 0.0

    def uct(self, exploration_weight: float = 1.414) -> float:
        """Compute Upper Confidence Bound for Trees (UCT)."""
        if self.visits == 0:
            return float("inf")
        if self.parent is None or self.parent.visits == 0:
            return self.q_value
        exploration = exploration_weight * math.sqrt(math.log(self.parent.visits) / self.visits)
        return self.q_value + exploration

    def select_best_child(self, exploration_weight: float = 1.414) -> MCTSNode:
        """Select child with highest UCT score."""
        if not self.children:
            raise ValueError("Node has no children to select from.")
        return max(self.children, key=lambda c: c.uct(exploration_weight))


class ProcessRewardVerifier:
    """Lightweight Process Reward Model (PRM) scoring intermediate reasoning transitions."""

    FALLACY_MARKERS = [
        "contradiction",
        "invalid step",
        "division by zero",
        "impossible premise",
        "undefined operation",
    ]

    def score_step(self, parent_thought: str, candidate_step: str) -> float:
        """Score reasoning step transition into [0.0, 1.0]."""
        if not candidate_step or not candidate_step.strip():
            return 0.0

        step_lower = candidate_step.lower()
        # Penalize fallacy markers
        for marker in self.FALLACY_MARKERS:
            if marker in step_lower:
                return 0.1

        # Reward constructive mathematical or deductive connective tokens
        score = 0.70
        connectives = ["therefore", "because", "since", "let", "given", "substituting", "equals", "="]
        if any(c in step_lower for c in connectives):
            score += 0.20

        if len(candidate_step.split()) >= 4:
            score += 0.10

        return min(1.0, max(0.0, score))


class TreeOfThoughtsMCTS:
    """Monte Carlo Tree Search over reasoning steps."""

    def __init__(
        self,
        prm: Optional[ProcessRewardVerifier] = None,
        exploration_weight: float = 1.414,
        max_depth: int = 8,
        iterations: int = 20,
    ) -> None:
        self.prm = prm or ProcessRewardVerifier()
        self.exploration_weight = exploration_weight
        self.max_depth = max_depth
        self.iterations = iterations

    def search(
        self,
        initial_problem: str,
        expand_fn: Callable[[str], Sequence[str]],
        iterations: Optional[int] = None,
    ) -> list[str]:
        """Perform MCTS to identify the optimal reasoning trajectory.

        Args:
            initial_problem: Root problem definition.
            expand_fn: Function mapping current path/state to candidate next reasoning steps.
            iterations: Number of MCTS simulation rollouts.

        Returns:
            List of reasoning steps forming the highest-value path to solution.
        """
        root = MCTSNode(state=initial_problem, step_index=0)
        num_iters = iterations if iterations is not None else self.iterations

        for _ in range(num_iters):
            # 1. Selection
            node = root
            while node.children and not node.is_terminal and node.step_index < self.max_depth:
                node = node.select_best_child(self.exploration_weight)

            # 2. Expansion
            if not node.is_terminal and node.step_index < self.max_depth and not node.children:
                candidates = expand_fn(node.state)
                if not candidates:
                    node.is_terminal = True
                else:
                    for cand in candidates:
                        step_score = self.prm.score_step(node.state, cand)
                        is_term = "final answer" in cand.lower() or "qed" in cand.lower()
                        child = MCTSNode(
                            state=f"{node.state} -> {cand}" if node.state else cand,
                            parent=node,
                            prm_score=step_score,
                            is_terminal=is_term,
                            step_index=node.step_index + 1,
                        )
                        node.children.append(child)

                    # Pick first expanded child for simulation if available
                    if node.children:
                        node = node.children[0]

            # 3. Simulation / Evaluation
            # Node reward combines PRM step score with depth progression
            reward = node.prm_score * (1.0 if not node.is_terminal or node.prm_score > 0.5 else 0.2)

            # 4. Backpropagation
            curr: Optional[MCTSNode] = node
            while curr is not None:
                curr.visits += 1
                curr.value += reward
                curr = curr.parent

        # Trace winning path
        path: list[str] = []
        curr_step: Optional[MCTSNode] = root
        while curr_step and curr_step.children:
            best_child = max(curr_step.children, key=lambda c: c.visits)
            path.append(best_child.state)
            if best_child.is_terminal or best_child.visits == 0:
                break
            curr_step = best_child

        return path
