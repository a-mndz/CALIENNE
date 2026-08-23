"""Agent contracts — per-node I/O contracts and failure policies (RFC-003 §3.4).

Every contract inherits from ``CalienneBaseModel`` per ADR-001.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from core.base import CalienneBaseModel


class InputContract(CalienneBaseModel):
    """Required inputs and validation rules for a node."""

    required_fields: list[str] = Field(default_factory=list)
    allowed_types: list[str] = Field(default_factory=list)
    validation_rules: dict[str, Any] = Field(default_factory=dict)


class OutputContract(CalienneBaseModel):
    """Produced outputs and their types for a node."""

    produced_fields: list[str] = Field(default_factory=list)
    types: dict[str, str] = Field(default_factory=dict)
    schema_ref: str | None = None


class FailureContract(CalienneBaseModel):
    """Failure modes and the response shape for each."""

    failure_modes: list[str] = Field(default_factory=list)
    response_shape: str = "repair_request"


class FailurePolicy(CalienneBaseModel):
    """Maps FailureClass -> Action (RFC-003 §3.5)."""

    failure_class: str = "recoverable"  # recoverable | non_recoverable
    action: str = "retry_with_backoff"
    max_retries: int = 2


class ContractViolation(CalienneBaseModel):
    """A single input/output contract breach for one node (RFC-003 §3.4)."""

    task_id: str
    kind: str  # "missing_input" | "missing_output" | "type_mismatch"
    field: str


# RFC-003 §3.5 failure classification. Anything unlisted classifies as
# non_recoverable (fail safe, not fail open).
_RECOVERABLE: frozenset[str] = frozenset(
    {"timeout", "rate_limited", "provider_down", "oom", "validation_error"}
)

# Failure mode -> action (RFC-003 §3.5 action set).
_ACTIONS: dict[str, str] = {
    "timeout": "retry_with_backoff",
    "rate_limited": "retry_with_backoff",
    "provider_down": "switch_provider",
    "oom": "downgrade_model",
    "validation_error": "request_repair",
    "unsupported_claim": "request_repair",
    "contradiction": "request_repair",
    "auth_error": "abort_branch",
    "contract_violation": "abort_branch",
}

# Ambient pipeline inputs the executor always supplies (not node-produced).
_AMBIENT_INPUTS: frozenset[str] = frozenset(
    {"request", "task_profile", "strategic_plan", "history"}
)


def validate_inputs(
    node: Any, incoming_outputs: dict[str, Any]
) -> list[ContractViolation]:
    """Every required input present before a node starts (RFC-003 §3.4).

    ``incoming_outputs`` maps produced-field name -> value (aggregated from
    upstream nodes). Ambient pipeline inputs are always considered satisfied.
    """
    contract = getattr(node, "input_contract", None)
    if contract is None:
        return []
    return [
        ContractViolation(task_id=node.task_id, kind="missing_input", field=field)
        for field in contract.required_fields
        if field not in incoming_outputs and field not in _AMBIENT_INPUTS
    ]


def validate_outputs(node: Any, produced: dict[str, Any]) -> list[ContractViolation]:
    """Every declared output is present with its declared type."""
    contract = getattr(node, "output_contract", None)
    if contract is None:
        return []
    violations = [
        ContractViolation(task_id=node.task_id, kind="missing_output", field=field)
        for field in contract.produced_fields
        if field not in produced
    ]
    type_map = {
        "string": str,
        "dict": dict,
        "list": list,
        "integer": int,
        "float": (int, float),
        "boolean": bool,
    }
    violations.extend(
        ContractViolation(task_id=node.task_id, kind="type_mismatch", field=field)
        for field, declared_type in contract.types.items()
        if field in produced
        and declared_type in type_map
        and not isinstance(produced[field], type_map[declared_type])
    )
    return violations


def classify_failure(failure_mode: str) -> FailurePolicy:
    """Map a failure mode to its recovery policy (RFC-003 §3.5)."""
    return FailurePolicy(
        failure_class="recoverable" if failure_mode in _RECOVERABLE else "non_recoverable",
        action=_ACTIONS.get(failure_mode, "abort_branch"),
    )


def to_failure_response(node: Any, failure: str) -> dict[str, Any]:
    """Emit a structured failure event for a node (RFC-003 §3.4).

    ``failure`` is a failure mode from the node's ``FailureContract``. The
    response shape and recovery policy come from the contract + classification.
    """
    contract = getattr(node, "failure_contract", None)
    policy = classify_failure(failure)
    return {
        "task_id": node.task_id,
        "status": "failed",
        "failure_mode": failure,
        "failure_class": policy.failure_class,
        "action": policy.action,
        "response_shape": contract.response_shape if contract is not None else "repair_request",
    }
