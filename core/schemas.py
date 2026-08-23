"""
calienne — Adaptive Multi-Model Reasoning Orchestrator
Core data contracts (Pydantic V2 strict models).

These schemas define the structured I/O boundaries between agents,
the signal-evaluation layer, and the final synthesis output.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from core.base import CalienneBaseModel

# ── Agent Output ─────────────────────────────────────────────────────────


class AgentOutput(CalienneBaseModel):
    """
    Structured output contract that every generation agent must conform to.

    Design note: ``strict=True`` is used with a ``mode='before'``
    validator on ``confidence``.  The before-mode validator runs
    *prior* to strict type checking, allowing string-to-float
    coercion (e.g. ``'high'`` → ``0.9``) while still enforcing
    strict types on all other fields.
    """

    model_config = ConfigDict(strict=True)

    @model_validator(mode="before")
    @classmethod
    def map_contract_fields(cls, data: Any) -> Any:
        """Map alternative XML response contract fields and dynamic role XML schemas to standard schema fields."""  # noqa: E501
        if isinstance(data, dict):
            # 1. Resolve 'confidence'
            if "confidence" in data:
                conf = data["confidence"]
                if isinstance(conf, dict):
                    level = conf.get("level", "medium")
                    if isinstance(level, str):
                        mapping = {"high": 0.9, "medium": 0.5, "low": 0.2}
                        data["confidence"] = mapping.get(level.lower().strip(), 0.5)
                    else:
                        data["confidence"] = 0.5
                elif isinstance(conf, str):
                    # Live models emit plain-string levels ("Low") as often as
                    # the dict form; coerce both (audit 2026-08-22 capture).
                    mapping = {"high": 0.9, "medium": 0.5, "low": 0.2}
                    data["confidence"] = mapping.get(conf.lower().strip(), 0.5)

            # 2. Resolve 'answer'
            # A present-but-null answer (a live model's honest "I have no
            # answer") must fall through to the substitution below instead of
            # failing strict string validation.
            if data.get("answer") is None:
                data.pop("answer", None)
            if "answer" not in data:
                potential_answers = [
                    "summary",
                    "draft_answer",
                    "primary_solution",
                    "recommendation",
                    "problem",
                    "status"
                ]
                for field in potential_answers:
                    if field in data and data[field]:
                        val = data[field]
                        if isinstance(val, str) and val.strip():
                            data["answer"] = val
                            break
                        elif isinstance(val, list) and val:
                            data["answer"] = str(val[0])
                            break
                if "answer" not in data:
                    data["answer"] = "No explicit answer field found in model output."

            # 3. Resolve 'reasoning_steps'
            if "reasoning_steps" not in data:
                potential_steps = [
                    "claims",
                    "logical_analysis",
                    "progress",
                    "tradeoffs",
                    "alternative_solutions",
                    "edge_cases",
                    "requirements"
                ]
                steps = []
                for field in potential_steps:
                    if field in data and data[field]:
                        val = data[field]
                        if isinstance(val, list):
                            for item in val:
                                if isinstance(item, dict):
                                    steps.append(json.dumps(item))
                                else:
                                    steps.append(str(item))
                        elif isinstance(val, str) and val.strip():
                            steps.append(val)
                data["reasoning_steps"] = steps if steps else ["No explicit reasoning steps found."]
        return data

    reasoning_steps: list[str] = Field(
        ...,
        min_length=0,
        description="Reasoning steps/trace of the agent.",
    )
    answer: str = Field(
        ...,
        min_length=0,
        description="Final answer string.",
    )
    confidence: float = Field(
        ...,
        description="Agent self-assessed confidence.",
    )

    @field_validator("confidence", mode="before")
    @classmethod
    def convert_confidence(cls, v: Any) -> float:
        """Coerce string confidence metrics from older schemas/simulators into standard floats."""
        if isinstance(v, str):
            mapping = {"high": 0.9, "medium": 0.5, "low": 0.2}
            return mapping.get(v.lower().strip(), 0.5)
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.5


# ── calienne Final Output ──────────────────────────────────────────────────


class calienneOutput(CalienneBaseModel):
    """
    The final synthesized validation output returned by validation arbitrage.
    """

    model_config = ConfigDict(strict=True)

    @model_validator(mode="before")
    @classmethod
    def map_contract_fields(cls, data: Any) -> Any:
        """Map alternative XML response contract fields to synthesizer schema fields."""
        if isinstance(data, dict):
            if "final_answer" not in data and "summary" in data:
                data["final_answer"] = data["summary"]
            if "overall_confidence" not in data and "confidence" in data:
                conf = data["confidence"]
                if isinstance(conf, (int, float)):
                    if conf >= 0.75:
                        data["overall_confidence"] = "High"
                    elif conf >= 0.4:
                        data["overall_confidence"] = "Medium"
                    else:
                        data["overall_confidence"] = "Low"
                elif isinstance(conf, dict):
                    data["overall_confidence"] = conf.get("level", "Medium")
                else:
                    data["overall_confidence"] = str(conf)
            if "overall_bias_risk" not in data:
                if "warnings" in data:
                    warnings = data["warnings"]
                    data["overall_bias_risk"] = "High" if warnings else "Low"
                else:
                    data["overall_bias_risk"] = "Low"
            if "disagreement_notes" not in data and "warnings" in data:
                warnings = data["warnings"]
                if isinstance(warnings, list):
                    data["disagreement_notes"] = [str(w) for w in warnings]
                elif isinstance(warnings, str):
                    data["disagreement_notes"] = [warnings]
            if "validation_score" not in data:
                if "confidence" in data and isinstance(data["confidence"], (int, float)):
                    data["validation_score"] = float(data["confidence"]) * 10.0
                else:
                    data["validation_score"] = 9.0  # default score
        return data

    final_answer: str = Field(
        ...,
        description="Synthesized response.",
    )
    overall_confidence: str = Field(
        ...,
        description="Overall confidence category (High/Medium/Low).",
    )
    overall_bias_risk: str = Field(
        ...,
        description="Overall bias risk category (Low/Medium/High).",
    )
    disagreement_notes: list[str] = Field(
        default_factory=list,
        description="Disagreements surfaced during arbitration.",
    )
    validation_score: float = Field(
        ...,
        description="Scoring indicating overall logical consistency.",
    )


# ── CALIENNE Shared Schemas ─────────────────────────────────────────────────────


class SessionMetadata(CalienneBaseModel):
    """Conversation session metadata shared with API and telemetry layers."""

    model_config = ConfigDict(strict=True)

    session_id: str = Field(..., min_length=1)
    user_id: str | None = None
    created_at: datetime
    last_activity: datetime
    turn_count: int = Field(..., ge=0)
    total_tokens: int = Field(..., ge=0)
    state: Literal["active", "waiting", "completed", "failed"]


class PipelineResult(CalienneBaseModel):
    """Structured result produced by a complete CALIENNE pipeline execution."""

    model_config = ConfigDict(strict=True)

    request_id: str = Field(..., min_length=1)
    session_id: str | None = None
    status: Literal["success", "error", "aborted"]
    final_answer: str
    validation_score: float = Field(..., ge=0.0, le=10.0)
    confidence_delta: float = Field(..., ge=0.0, le=1.0)
    agent_outputs: dict[str, Any] = Field(default_factory=dict)
    execution_time_ms: float = Field(..., ge=0.0)
    security_metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderHealthStatus(CalienneBaseModel):
    """Current provider health snapshot used for routing and monitoring."""

    model_config = ConfigDict(strict=True)

    provider_name: str = Field(..., min_length=1)
    status: Literal["healthy", "degraded", "dead"]
    success_rate: float = Field(..., ge=0.0, le=1.0)
    avg_latency_ms: float = Field(..., ge=0.0)
    error_count_24h: int = Field(..., ge=0)
    last_check: datetime


class CheckpointData(CalienneBaseModel):
    """Minimal state required to resume a pipeline from a checkpoint."""

    model_config = ConfigDict(strict=True)

    checkpoint_id: str = Field(..., min_length=1)
    request_id: str = Field(..., min_length=1)
    stage: str = Field(..., min_length=1)
    timestamp: datetime
    agent_outputs: dict[str, Any] = Field(default_factory=dict)
    partial_results: dict[str, Any] = Field(default_factory=dict)


# ── Stage Assessment (RFC-001 §5.1) ─────────────────────────────────────


class StageAssessment(CalienneBaseModel):
    """Assessment of a single pipeline stage — extended fields default to None."""

    confidence: float
    calibration: float | None = None
    evidence_strength: float | None = None
    novelty: float | None = None
    agreement: float | None = None
    stability: float | None = None
    reasoning_quality: str | None = None
    evidence_count: int = 0
    contradiction_score: float = 0.0
    unsupported_claim_count: int = 0

    @classmethod
    def from_minimal(cls, confidence: float) -> "StageAssessment":
        """Accept the legacy 3-field shape — fully-defaulted assessment for regression tests."""
        return cls(confidence=confidence)


# ── Planner Schemas (RFC-003 §3) ─────────────────────────────────────────


class TaskProfile(CalienneBaseModel):
    """Classification result from IntentAnalyzer — deterministic, token-free."""

    task_type: str = "general"
    complexity: str = "medium"
    criticality: str = "low"
    needs_decomposition: bool = False
    requires_rag: bool = False
    requires_code_context: bool = False
    requires_math_check: bool = False
    requires_creativity: bool = False


class StrategicPlan(CalienneBaseModel):
    """LLM-assisted decomposition of a complex task into sub-problems."""

    goal: str = ""
    sub_problems: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class PipelineBudget(CalienneBaseModel):
    """Token budget with pressure states — acts as the repair circuit breaker."""

    total_tokens: int = 15000
    planning_pct: float = 5.0
    generation_pct: float = 45.0
    critique_repair_pct: float = 20.0
    judge_pct: float = 15.0
    memory_pct: float = 10.0
    final_pct: float = 5.0
    pressure: str = "normal"  # normal | tight | critical | exhausted


class PipelinePlan(CalienneBaseModel):
    """Complete plan produced by ExecutionPlanner — graph + budget + predictions."""

    graph: "TaskGraph | None" = None
    budget: PipelineBudget = Field(default_factory=PipelineBudget)
    strategy: str = "deterministic"


class TaskNode(CalienneBaseModel):
    """A single node in a TaskGraph — maps to one unit of work."""

    task_id: str = ""
    objective: str = ""
    skills_required: list[str] = Field(default_factory=list)
    model_tier: str = "default"
    depends_on: list[str] = Field(default_factory=list)
    can_run_parallel: bool = True
    expected_tokens: int | None = None
    expected_latency_ms: int | None = None
    priority: str = "normal"  # critical | high | normal | background
    input_contract: "InputContract | None" = None
    output_contract: "OutputContract | None" = None
    failure_contract: "FailureContract | None" = None


class TaskGraph(CalienneBaseModel):
    """Validated DAG of TaskNodes — the executable plan shape."""

    nodes: list[TaskNode] = Field(default_factory=list)
    root_task_id: str = ""
    final_task_id: str = ""
    graph_version: str | None = None
    graph_fingerprint: str | None = None
    planner_version: str | None = None
    version_stamp: "VersionStamp | None" = None
    execution_manifest: "ExecutionManifest | None" = None


# ── Prediction (RFC-003 §3.6) ────────────────────────────────────────────


class PredictionInterval(CalienneBaseModel):
    """A predicted value with variance bounds."""

    value: float = 0.0
    variance: float = 0.0
    std_dev: float = 0.0
    sample_size: int = 0

    @property
    def upper_bound(self) -> float:
        return self.value + self.std_dev

    @property
    def lower_bound(self) -> float:
        return self.value - self.std_dev


class Prediction(CalienneBaseModel):
    """Execution cost / latency / confidence estimates with probability fields."""

    expected_cost: PredictionInterval = Field(default_factory=PredictionInterval)
    expected_latency_ms: PredictionInterval = Field(default_factory=PredictionInterval)
    expected_tokens: PredictionInterval = Field(default_factory=PredictionInterval)
    expected_confidence: PredictionInterval = Field(default_factory=PredictionInterval)
    probability_of_failure: float = 0.0
    probability_of_repair: float = 0.0
    probability_of_retrieval_needed: float = 0.0
    probability_of_clarification_needed: float = 0.0
    probability_of_consensus_disagreement: float = 0.0
    expected_repair_count: int = 0
    calibration_confidence: float = 0.0


# ── Clarification (RFC-003 §3.7) ─────────────────────────────────────────


class ClarificationRequest(CalienneBaseModel):
    """Structured request for user input when the system is uncertain."""

    status: Literal["needs_clarification"] = "needs_clarification"
    question: str = ""
    reason: str = ""
    missing_context: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)


# ── Version Stamp (RFC-005 §2) ───────────────────────────────────────────


class VersionStamp(CalienneBaseModel):
    """Immutable version snapshot — set by producer, consumed everywhere."""

    architecture_version: str = "0.1.0"
    planner_version: str | None = None
    scheduler_version: str | None = None
    budget_version: str | None = None
    routing_version: str | None = None
    capabilities_version: str | None = None
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    consensus_version: str | None = None
    contracts_version: str | None = None
    resource_policy_version: str | None = None
    prediction_model_version: str | None = None
    graph_version: str | None = None
    graph_fingerprint: str | None = None


# Resolve forward references introduced by Step 2 contracts.
from orchestrator.contracts import FailureContract, InputContract, OutputContract
from orchestrator.execution_manifest import ExecutionManifest

PipelinePlan.model_rebuild()
TaskNode.model_rebuild()
TaskGraph.model_rebuild()
