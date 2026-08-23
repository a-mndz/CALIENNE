from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from orchestrator.checkpoints import CheckpointManager

pytestmark = pytest.mark.security


@pytest.mark.asyncio
async def test_checkpoint_routes_isolate_users(monkeypatch) -> None:
    import server

    manager = CheckpointManager()
    alice_id = await manager.save_checkpoint(
        request_id="shared-request",
        session_id="alice-session",
        stage="generation",
        agent_outputs={},
        partial_results={},
        user_email="alice@example.com",
    )
    bob_id = await manager.save_checkpoint(
        request_id="shared-request",
        session_id="bob-session",
        stage="generation",
        agent_outputs={},
        partial_results={},
        user_email="bob@example.com",
    )
    monkeypatch.setattr(server, "_calienne", {"checkpoint_manager": manager})
    alice = SimpleNamespace(email="alice@example.com")

    listed = await server.list_checkpoints("shared-request", alice)
    assert [item["checkpoint_id"] for item in listed.checkpoints] == [alice_id]

    with pytest.raises(HTTPException) as exc_info:
        await server.restore_checkpoint(
            bob_id, server.CheckpointRestoreRequest(), alice
        )
    assert exc_info.value.status_code == 404

    deleted = await server.delete_checkpoints("shared-request", alice)
    assert deleted.deleted_count == 1
    assert await manager.restore_checkpoint(bob_id, "bob@example.com") is not None


def test_session_create_rejects_caller_selected_owner() -> None:
    from pydantic import ValidationError

    from server import SessionCreateRequest

    with pytest.raises(ValidationError):
        SessionCreateRequest(user_id="bob@example.com")


@pytest.mark.asyncio
async def test_get_current_user_accepts_auth_cookie(monkeypatch) -> None:
    import core.security as security

    user = SimpleNamespace(email="alice@example.com")

    class Result:
        class Scalars:
            @staticmethod
            def first():
                return user

        @staticmethod
        def scalars():
            return Result.Scalars()

    class Database:
        @staticmethod
        async def execute(_statement):
            return Result()

    token = security.create_access_token({"sub": user.email})
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/status",
            "headers": [(b"cookie", f"{security.settings.AUTH_COOKIE_NAME}={token}".encode())],
        }
    )

    assert await security.get_current_user(request, None, Database()) is user


def test_auth_cookie_secure_outside_development(monkeypatch) -> None:
    from fastapi.responses import JSONResponse

    import server

    settings = SimpleNamespace(
        AUTH_COOKIE_NAME="calienne_auth",
        JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60,
        ENVIRONMENT="production",
    )
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    response = JSONResponse({})

    server._set_auth_cookie(response, "token")

    assert "Secure" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_csrf_requires_origin_for_cookie_authenticated_write(monkeypatch) -> None:
    import server

    settings = SimpleNamespace(
        AUTH_COOKIE_NAME="calienne_auth",
        CORS_ORIGINS="http://localhost:8000",
    )
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/query",
            "headers": [(b"cookie", b"calienne_auth=token")],
        }
    )

    async def should_not_run(_request):
        raise AssertionError("request bypassed CSRF policy")

    response = await server.csrf_origin_check(request, should_not_run)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_login_returns_cookie_without_script_readable_token(monkeypatch) -> None:
    import server
    from core.security import hash_password

    user = SimpleNamespace(
        email="alice@example.com",
        password_hash=hash_password("correct-password"),
    )

    class Result:
        class Scalars:
            @staticmethod
            def first():
                return user

        @staticmethod
        def scalars():
            return Result.Scalars()

    class Database:
        @staticmethod
        async def execute(_statement):
            return Result()

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/login",
            "headers": [],
            "client": ("198.51.100.25", 1234),
        }
    )
    monkeypatch.setattr(server, "_enforce_auth_rate_limit", lambda _ip: True)

    response = await server.login_user(
        server.AuthLoginRequest(
            email="alice@example.com", password="correct-password"
        ),
        request,
        Database(),
    )
    payload = json.loads(response.body)

    assert payload == {"status": "ok"}
    assert "access_token" not in payload
    assert "HttpOnly" in response.headers["set-cookie"]
