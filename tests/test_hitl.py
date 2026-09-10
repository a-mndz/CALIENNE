"""Tests for Human-in-the-Loop (HITL) interrupt and resume functionality."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.models import User
from orchestrator.contracts import InputContract, validate_inputs
from orchestrator.hitl import (
    CommandResume,
    HitlPause,
    clear_paused_runs,
    get_paused_run,
    interrupt,
    resume_with,
)
from orchestrator.state_machine import PipelineState, StateMachine

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_hitl():
    clear_paused_runs()
    yield
    clear_paused_runs()


def test_interrupt_emits_node_paused_event() -> None:
    sm = StateMachine(request_id="trace-101")
    sm.transition(PipelineState.NORMALIZING)
    sm.transition(PipelineState.BREACH_CHECKING)
    sm.transition(PipelineState.GENERATING)

    recorder = MagicMock()

    pause = interrupt(
        payload={"question": "Which database table?"},
        trace_id="trace-101",
        paused_at_stage="generating",
        state_machine=sm,
        replay_recorder=recorder,
    )

    assert isinstance(pause, HitlPause)
    assert pause.trace_id == "trace-101"
    assert pause.paused_at_stage == "generating"
    assert sm.current_state == PipelineState.PAUSED

    recorder.emit.assert_called_once()
    event_type, kwargs = recorder.emit.call_args[0][0], recorder.emit.call_args[1]
    assert event_type == "node_paused"
    assert kwargs["payload"]["trace_id"] == "trace-101"


def test_resume_with_returns_envelope() -> None:
    sm = StateMachine(request_id="trace-102")
    sm.transition(PipelineState.NORMALIZING)
    sm.transition(PipelineState.BREACH_CHECKING)
    sm.transition(PipelineState.GENERATING)
    sm.transition(PipelineState.PAUSED)

    interrupt(
        payload={"missing": "param"},
        trace_id="trace-102",
        state_machine=sm,
    )

    cmd = resume_with(value="users_v2", trace_id="trace-102", target_state=PipelineState.GENERATING)
    assert isinstance(cmd, CommandResume)
    assert cmd.value == "users_v2"
    assert cmd.trace_id == "trace-102"
    assert sm.current_state == PipelineState.GENERATING


@pytest.mark.asyncio
async def test_resume_endpoint_reenters_paused_node() -> None:
    from server import ResumeRequest, resume_run

    interrupt(
        payload={"question": "Specify date range"},
        trace_id="trace-ep-1",
        paused_at_stage="generating",
    )

    admin_user = User(
        email="admin@calienne.ai",
        role="admin",
        password_hash="dummy",
    )

    response = await resume_run(
        trace_id="trace-ep-1",
        payload=ResumeRequest(value="2026-01-01 to 2026-08-31"),
        current_user=admin_user,
    )

    assert response["status"] == "resumed"
    assert response["trace_id"] == "trace-ep-1"
    assert response["resumed_with"] == "2026-01-01 to 2026-08-31"
    assert response["command"]["value"] == "2026-01-01 to 2026-08-31"


def test_validate_inputs_reruns_on_resume() -> None:
    class DummyNode:
        task_id = "task-hitl"
        input_contract = InputContract(
            required_fields=["user_query", "human_answer"],
        )

    node = DummyNode()
    initial_inputs = {"user_query": "What is the status?"}
    violations_init = validate_inputs(node, initial_inputs)
    assert len(violations_init) == 1
    assert violations_init[0].field == "human_answer"

    # Resume adds the human input
    resume_cmd = resume_with(value="completed", trace_id="trace-103")
    resumed_inputs = {**initial_inputs, "human_answer": resume_cmd.value}
    violations_resumed = validate_inputs(node, resumed_inputs)
    assert len(violations_resumed) == 0


def test_pause_inside_repair() -> None:
    sm = StateMachine(request_id="trace-repair")
    sm.transition(PipelineState.NORMALIZING)
    sm.transition(PipelineState.BREACH_CHECKING)
    sm.transition(PipelineState.GENERATING)
    sm.transition(PipelineState.EVALUATING)

    pause = interrupt(
        payload={"defect": "contradiction", "suggested_action": "pick option A or B"},
        trace_id="trace-repair",
        paused_at_stage="evaluating",
        state_machine=sm,
    )

    assert pause.trace_id == "trace-repair"
    assert sm.current_state == PipelineState.PAUSED

    # Resume into evaluating stage
    cmd = resume_with(value="Option A", trace_id="trace-repair", target_state=PipelineState.EVALUATING)
    assert cmd.value == "Option A"
    assert sm.current_state == PipelineState.EVALUATING
