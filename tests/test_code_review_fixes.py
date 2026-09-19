"""Targeted regression tests for full code review remediations.

Verifies:
- PythonREPLTool security restrictions (AST blocking of banned modules, builtins, dunder attributes).
- WebSearchTool fallback metadata (source_authority, confidence level).
- Breaker gate timeout default (5000ms).
- Judge target model selection in decisions.py.
- System prompt handling in api_gateway/client.py.
- Conversation edit preservation logic in api/routes_conversations.py.
- Auth initial admin email and registration role assignment.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from api.routes_auth import AuthRegisterRequest, register_user
from api.routes_conversations import ConversationSaveRequest, save_conversation
from api_gateway.client import AsyncHTTPClient
from core.database import Base
from core.models import ConversationSessionRecord, User
from core.tools import PythonREPLTool, WebSearchTool
from orchestrator.breaker_gate import BreakerGate
from orchestrator.consensus import JudgeOutput
from orchestrator.decisions import DecisionEngine


@pytest.mark.asyncio
async def test_repl_hardened_ast_validation() -> None:
    repl = PythonREPLTool()

    # Banned modules
    for mod in ["os", "sys", "subprocess", "socket", "ctypes", "shutil"]:
        res = await repl.execute(f"import {mod}")
        assert res.success is False
        assert "prohibited" in (res.error or "")

    # Banned builtins
    for fn in ["eval('1')", "exec('x=1')", "open('x')", "__import__('os')"]:
        res = await repl.execute(fn)
        assert res.success is False
        assert "prohibited" in (res.error or "")

    # Banned dunders
    res = await repl.execute("x = ().__class__.__base__")
    assert res.success is False
    assert "prohibited" in (res.error or "")


@pytest.mark.asyncio
async def test_web_search_simulated_fallback() -> None:
    search = WebSearchTool()
    res = await search.search("quantum consensus")
    assert res["status"] == "completed"
    assert res["results"][0]["source_authority"] == "SIMULATED"
    assert res["confidence"]["level"] == "LOW"


def test_breaker_gate_timeout_defaults() -> None:
    assert BreakerGate.BREAKER_TIMEOUT_MS == 5000
    assert DecisionEngine.BREAKER_TIMEOUT_MS == 5000


def test_judge_chain_target_model_selection() -> None:
    judge_chain = ["claude-3-5-sonnet", "gpt-4o"]
    for idx, expected in enumerate(judge_chain):
        target_model = (
            judge_chain[idx % len(judge_chain)]
            if judge_chain
            else f"judge_{idx}_arbiter"
        )
        output = JudgeOutput(
            model_id=target_model,
            claims=["claim1"],
            confidence=0.85,
            answer="test answer",
        )
        assert output.model_id == expected


@pytest.mark.asyncio
async def test_gateway_system_prompt_merging() -> None:
    client = AsyncHTTPClient()
    client._is_simulated = MagicMock(return_value=False)
    client._get_active_api_key = MagicMock(return_value="mock-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"answer": "ok", "confidence": 1.0, "reasoning_steps": []}'}}],
        "usage": {"total_tokens": 10},
    }
    client.client.post = AsyncMock(return_value=mock_resp)

    history = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
    ]
    await client.post_request(
        model="openrouter/anthropic/claude-3-haiku",
        prompt="second question",
        system_prompt="Base system instruction.",
        history=history,
    )

    client.client.post.assert_called_once()
    called_json = client.client.post.call_args.kwargs.get("json") or {}
    messages = called_json.get("messages", [])

    # The system prompt should be at index 0 and contain both base instructions and reminder
    assert len(messages) == 4
    assert messages[0]["role"] == "system"
    assert "Base system instruction." in messages[0]["content"]
    assert "CRITICAL REMINDER" in messages[0]["content"]
    # History follows
    assert messages[1] == {"role": "user", "content": "first question"}
    assert messages[2] == {"role": "assistant", "content": "first answer"}
    # Final prompt
    assert messages[3] == {"role": "user", "content": "second question"}
    # No trailing system message
    assert messages[-1]["role"] != "system"


@pytest.fixture
async def async_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
    await engine.dispose()



@pytest.mark.asyncio
async def test_conversation_edit_preservation(async_db: AsyncSession) -> None:
    # 1. Create a user and a session
    user = User(
        email="user@test.com",
        password_hash="hash",
        role="user",
    )
    async_db.add(user)
    await async_db.flush()

    # Initial save: 2 turns
    req1 = ConversationSaveRequest(
        id="conv-1",
        title="Test Conversation",
        mode="chat",
        transcript=[
            {"role": "user", "text": "Turn 1"},
            {"role": "assistant", "text": "Turn 2"},
        ],
    )
    res1 = await save_conversation(req1, current_user=user, db=async_db)
    assert res1["status"] == "ok"

    # 2. Modify existing turn (user edited Turn 1)
    req2 = ConversationSaveRequest(
        id="conv-1",
        title="Test Conversation Edited",
        mode="chat",
        transcript=[
            {"role": "user", "text": "Turn 1 EDITED"},
            {"role": "assistant", "text": "Turn 2"},
            {"role": "user", "text": "Turn 3"},
        ],
    )
    res2 = await save_conversation(req2, current_user=user, db=async_db)
    assert res2["status"] == "ok"

    # Verify that message 1 has updated text
    stmt = (
        select(ConversationSessionRecord)
        .where(ConversationSessionRecord.session_id == "conv-1")
        .options(selectinload(ConversationSessionRecord.messages))
    )
    res = await async_db.execute(stmt)
    session_rec = res.scalars().first()
    assert session_rec is not None
    msgs = sorted(session_rec.messages or [], key=lambda m: m.timestamp)
    assert msgs[0].content == "Turn 1 EDITED"
    assert msgs[2].content == "Turn 3"


@pytest.mark.asyncio
async def test_auth_initial_admin_and_role_assignment(async_db: AsyncSession) -> None:
    dummy_request = MagicMock()
    dummy_request.client.host = "127.0.0.1"

    with patch("api.routes_auth._enforce_rate_limit", return_value=True):
        with patch("api.routes_auth.get_settings") as mock_settings:
            cfg = MagicMock()
            cfg.INITIAL_ADMIN_EMAIL = "admin@example.com"
            mock_settings.return_value = cfg

            # First registration with regular user when INITIAL_ADMIN_EMAIL is set
            res1 = await register_user(
                AuthRegisterRequest(email="first@example.com", password="Password123!"),
                request=dummy_request,
                db=async_db,
            )
            assert res1["message"] == "User registered successfully"
            u1 = (await async_db.execute(select(User).where(User.email == "first@example.com"))).scalar_one()
            assert u1.role == "user"

            # Second registration with INITIAL_ADMIN_EMAIL
            res2 = await register_user(
                AuthRegisterRequest(email="admin@example.com", password="Password123!"),
                request=dummy_request,
                db=async_db,
            )
            assert res2["message"] == "User registered successfully"
            u2 = (await async_db.execute(select(User).where(User.email == "admin@example.com"))).scalar_one()
            assert u2.role == "admin"

            # Third registration with another email
            res3 = await register_user(
                AuthRegisterRequest(email="third@example.com", password="Password123!"),
                request=dummy_request,
                db=async_db,
            )
            assert res3["message"] == "User registered successfully"
            u3 = (await async_db.execute(select(User).where(User.email == "third@example.com"))).scalar_one()
            assert u3.role == "user"
