"""Weighted consensus engine + dynamic judge allocation (RFC-003 §8/§10).

Gate: CALIENNE_ENABLE_CONSENSUS.

Inputs: outputs from multiple models or judges.
Outputs: raw + weighted agreement, agreement matrix, disagreement clusters,
MinorityView with reasons, derived minority_should_influence_final.

Weights come from config/capabilities/model_capabilities.json.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import Field as PydanticField

from core.base import CalienneBaseModel

LOGGER = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CAPABILITIES_PATH = _REPO_ROOT / "config" / "capabilities" / "model_capabilities.json"

# ponytail: neutral fallback weight per RFC-002 §5.
_FALLBACK_WEIGHT = 0.5

# ── Schemas ───────────────────────────────────────────────────────────


class MinorityView(CalienneBaseModel):
    """A dissenting position from a minority judge (RFC-003 §10)."""

    claim: str = ""
    model_id: str = ""
    confidence: float = 0.0
    reason: str = ""


class JudgePlan(CalienneBaseModel):
    """Dynamic judge allocation plan (RFC-003 §8)."""

    judge_count: int = 1
    judge_roles: list[str] = PydanticField(default_factory=list)
    requires_consensus: bool = False
    model_weighting_strategy: str = "equal"


class ConsensusResult(CalienneBaseModel):
    """Full consensus output from the engine."""

    raw_agreement: float = 0.0
    weighted_agreement: float = 0.0
    agreement_matrix: dict[str, dict[str, float]] = PydanticField(default_factory=dict)
    disagreement_clusters: list[list[str]] = PydanticField(default_factory=list)
    confidence_spread: float = 0.0
    contradiction_score: float = 0.0
    majority_claims: list[str] = PydanticField(default_factory=list)
    minority_views: list[MinorityView] = PydanticField(default_factory=list)
    minority_should_influence_final: bool = False
    judge_plan: JudgePlan = PydanticField(default_factory=JudgePlan)


# ── Judge output container ────────────────────────────────────────────


@dataclass(frozen=True)
class JudgeOutput:
    """One judge's output — lightweight container for consensus input."""

    model_id: str
    claims: list[str] = field(default_factory=list)
    confidence: float = 0.5
    answer: str = ""


# ── Capability weight loader ─────────────────────────────────────────


def _load_model_weights(
    task_type: str,
    *,
    config_path: Path | None = None,
) -> dict[str, float]:
    """Load per-model capability weights for a task type.

    On any failure, returns empty dict — callers fall back to _FALLBACK_WEIGHT.
    """
    path = config_path or _DEFAULT_CAPABILITIES_PATH
    if not path.is_file():
        LOGGER.warning("model_capabilities.json not found at %s; using fallback weights", path)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Failed to load model_capabilities.json: %s", exc)
        return {}

    models = data.get("models", {})
    weights: dict[str, float] = {}
    for model_id, info in models.items():
        w = info.get("weights", {}).get(task_type)
        if isinstance(w, (int, float)) and 0.0 <= w <= 1.0:
            weights[model_id] = float(w)
    return weights


# ── Judge allocation ──────────────────────────────────────────────────

# RFC-003 §8: complexity → judge count.
_JUDGE_COUNT_BY_COMPLEXITY: dict[str, int] = {
    "low": 1,
    "medium": 2,
    "high": 4,
    "critical": 6,  # "full pipeline"
}


def allocate_judges(
    complexity: str,
    *,
    early_exit_failed: bool = True,
    task_type: str = "general",
) -> JudgePlan:
    """Map complexity to a JudgePlan (RFC-003 §8).

    For low complexity, returns 1 judge only if early-exit failed;
    otherwise 0 (the caller skips judging entirely).
    """
    count = _JUDGE_COUNT_BY_COMPLEXITY.get(complexity, 2)
    if complexity == "low" and not early_exit_failed:
        count = 0

    requires_consensus = count >= 2
    strategy = "capability_weighted" if requires_consensus else "equal"

    # Route-specific roles: coding/math get verifiers, not creative agents.
    if task_type in ("coding", "math"):
        roles = ["verifier"] * count
    elif task_type == "creative":
        roles = ["critic"] * count
    else:
        roles = ["judge"] * count

    return JudgePlan(
        judge_count=count,
        judge_roles=roles,
        requires_consensus=requires_consensus,
        model_weighting_strategy=strategy,
    )


# ── Consensus computation ─────────────────────────────────────────────


def _pairwise_agreement(a: JudgeOutput, b: JudgeOutput) -> float:
    """Jaccard similarity of claim sets."""
    if not a.claims and not b.claims:
        return 1.0
    set_a, set_b = set(a.claims), set(b.claims)
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 1.0


def compute_consensus(
    outputs: list[JudgeOutput],
    *,
    task_type: str = "general",
    judge_plan: JudgePlan | None = None,
    config_path: Path | None = None,
) -> ConsensusResult:
    """Compute consensus across judge outputs (RFC-003 §10)."""
    if not outputs:
        return ConsensusResult(judge_plan=judge_plan or JudgePlan())

    plan = judge_plan or JudgePlan(judge_count=len(outputs))
    model_weights = _load_model_weights(task_type, config_path=config_path)

    # Agreement matrix (pairwise).
    matrix: dict[str, dict[str, float]] = {}
    pair_scores: list[float] = []
    for i, a in enumerate(outputs):
        row: dict[str, float] = {}
        for j, b in enumerate(outputs):
            score = 1.0 if i == j else _pairwise_agreement(a, b)
            row[b.model_id] = score
            if j > i:
                pair_scores.append(score)
        matrix[a.model_id] = row

    # Raw agreement: mean of all pairwise scores.
    raw_agreement = sum(pair_scores) / len(pair_scores) if pair_scores else 1.0

    # Weighted agreement: weight each output's mean agreement by its capability weight.
    weighted_scores: list[float] = []
    total_weight = 0.0
    for o in outputs:
        w = model_weights.get(o.model_id, _FALLBACK_WEIGHT)
        mean_agree = sum(
            matrix[o.model_id][other.model_id]
            for other in outputs if other.model_id != o.model_id
        ) / max(1, len(outputs) - 1)
        weighted_scores.append(mean_agree * w)
        total_weight += w
    weighted_agreement = sum(weighted_scores) / total_weight if total_weight else raw_agreement

    # Confidence spread.
    confidences = [o.confidence for o in outputs]
    confidence_spread = max(confidences) - min(confidences) if len(confidences) > 1 else 0.0

    # Contradiction score: 1 - raw_agreement.
    contradiction_score = round(1.0 - raw_agreement, 4)

    # Majority claims: claims appearing in >50% of outputs.
    claim_counts: dict[str, int] = {}
    for o in outputs:
        for c in o.claims:
            claim_counts[c] = claim_counts.get(c, 0) + 1
    threshold = len(outputs) / 2.0
    majority_claims = sorted(c for c, n in claim_counts.items() if n > threshold)

    # Disagreement clusters: groups of models that agree with each other
    # but disagree with the majority.
    majority_set = set(majority_claims)
    clusters: list[list[str]] = []
    for o in outputs:
        own_claims = set(o.claims)
        if own_claims and not own_claims.issubset(majority_set):
            dissent = own_claims - majority_set
            placed = False
            for cluster in clusters:
                # If any existing member shares dissenting claims, merge.
                for member_id in cluster:
                    member = next((x for x in outputs if x.model_id == member_id), None)
                    if member and dissent & (set(member.claims) - majority_set):
                        cluster.append(o.model_id)
                        placed = True
                        break
                if placed:
                    break
            if not placed:
                clusters.append([o.model_id])

    # Minority views.
    minority_views: list[MinorityView] = []
    for o in outputs:
        dissenting = [c for c in o.claims if c not in majority_set]
        for claim in dissenting:
            minority_views.append(MinorityView(
                claim=claim,
                model_id=o.model_id,
                confidence=o.confidence,
                reason=f"{o.model_id} asserts '{claim}' against majority consensus",
            ))

    # Derived flag: minority should influence final when weighted_agreement
    # is low AND at least one minority view comes from a high-weight model.
    _HIGH_WEIGHT_THRESHOLD = 0.75
    minority_should_influence = False
    if weighted_agreement < 0.6 and minority_views:
        for mv in minority_views:
            if model_weights.get(mv.model_id, _FALLBACK_WEIGHT) >= _HIGH_WEIGHT_THRESHOLD:
                minority_should_influence = True
                break

    return ConsensusResult(
        raw_agreement=round(raw_agreement, 4),
        weighted_agreement=round(weighted_agreement, 4),
        agreement_matrix=matrix,
        disagreement_clusters=clusters,
        confidence_spread=round(confidence_spread, 4),
        contradiction_score=contradiction_score,
        majority_claims=majority_claims,
        minority_views=minority_views,
        minority_should_influence_final=minority_should_influence,
        judge_plan=plan,
    )
