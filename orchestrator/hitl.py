"""Human-in-the-loop (HITL) interrupt and resume primitives."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any

from orchestrator.state_machine import PipelineState, StateMachine

_HITL_LOCK = Lock()
_PAUSED_RUNS: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class HitlPause:
    """Record of an execution pause awaiting external/human input."""

    payload: Any
    trace_id: str
    paused_at_stage: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload": self.payload,
            "trace_id": self.trace_id,
            "paused_at_stage": self.paused_at_stage,
        }


@dataclass(frozen=True)
class CommandResume:
    """Envelope carrying resumption input for a paused execution."""

    value: Any
    trace_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "trace_id": self.trace_id,
        }


def interrupt(
    payload: Any,
    *,
    trace_id: str,
    paused_at_stage: str = "",
    state_machine: StateMachine | None = None,
    replay_recorder: Any | None = None,
    run_context: dict[str, Any] | None = None,
) -> HitlPause:
    """Pause an execution, record the pause event, and wait for resumption."""
    pause = HitlPause(
        payload=payload,
        trace_id=trace_id,
        paused_at_stage=paused_at_stage,
    )

    with _HITL_LOCK:
        _PAUSED_RUNS[trace_id] = {
            "pause": pause,
            "context": run_context or {},
            "state_machine": state_machine,
        }

    if state_machine is not None and state_machine.current_state != PipelineState.PAUSED:
        state_machine.transition(PipelineState.PAUSED, metadata={"trace_id": trace_id})

    if replay_recorder is not None and hasattr(replay_recorder, "emit"):
        replay_recorder.emit(
            "node_paused",
            payload={
                "trace_id": trace_id,
                "paused_at_stage": paused_at_stage,
                "pause_payload": payload,
            },
        )

    return pause


def resume_with(
    value: Any,
    *,
    trace_id: str,
    target_state: PipelineState = PipelineState.GENERATING,
) -> CommandResume:
    """Resume a paused execution with the provided input value."""
    resume_cmd = CommandResume(value=value, trace_id=trace_id)

    with _HITL_LOCK:
        paused_data = _PAUSED_RUNS.get(trace_id)

    if paused_data is not None:
        sm = paused_data.get("state_machine")
        if sm is not None and sm.current_state == PipelineState.PAUSED:
            sm.transition(target_state, metadata={"resumed_with": value, "trace_id": trace_id})

    return resume_cmd


def get_paused_run(trace_id: str) -> dict[str, Any] | None:
    """Retrieve recorded pause information for a given trace_id."""
    with _HITL_LOCK:
        return _PAUSED_RUNS.get(trace_id)


def clear_paused_runs() -> None:
    """Clear all recorded paused runs (useful for test isolation)."""
    with _HITL_LOCK:
        _PAUSED_RUNS.clear()
