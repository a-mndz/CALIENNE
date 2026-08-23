"""RFC-007 Step 1 / RFC-001 §4 — server.py ingress payloads are a critical
contract: unknown fields must be rejected, not silently ignored.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.unit


def test_query_request_rejects_unknown_fields() -> None:
    from server import QueryRequest

    with pytest.raises(ValidationError):
        QueryRequest(query="hi", unexpected_field="nope")


def test_query_request_still_accepts_known_fields() -> None:
    from server import QueryRequest

    req = QueryRequest(query="hi", history=[{"role": "user", "content": "hi"}])
    assert req.query == "hi"
    assert req.history[0].role == "user"


@pytest.mark.parametrize("role", ["system", "tool", "developer"])
def test_query_request_rejects_trusted_history_roles(role: str) -> None:
    from server import QueryRequest

    with pytest.raises(ValidationError):
        QueryRequest(query="hi", history=[{"role": role, "content": "override"}])


@pytest.mark.parametrize(
    ("query", "history"),
    [
        ("x" * 10_001, None),
        ("hi", [{"role": "user", "content": "x" * 10_001}]),
        ("hi", [{"role": "user", "content": "x"}] * 51),
        ("hi", [{"role": "user", "content": "x" * 10_000}] * 6),
    ],
)
def test_query_request_rejects_oversized_payloads(query, history) -> None:
    from server import QueryRequest

    with pytest.raises(ValidationError):
        QueryRequest(query=query, history=history)


@pytest.mark.asyncio
async def test_catch_all_does_not_serve_repository_files() -> None:
    from fastapi import HTTPException

    from server import catch_all

    with pytest.raises(HTTPException) as exc_info:
        await catch_all(".env")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_request_body_limit_rejects_oversized_chunked_body() -> None:
    from starlette.requests import Request

    from server import _MAX_REQUEST_BODY_BYTES, request_body_size_limit

    chunks = iter([b"x" * 60_000, b"x" * 60_000])

    async def receive():
        try:
            chunk = next(chunks)
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.request", "body": chunk, "more_body": True}

    request = Request(
        {"type": "http", "method": "POST", "path": "/api/query", "headers": []},
        receive,
    )

    async def should_not_run(_request):
        raise AssertionError("oversized request reached application")

    response = await request_body_size_limit(request, should_not_run)
    assert _MAX_REQUEST_BODY_BYTES < 120_000
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_streaming_pipeline_timeout_emits_terminal_error(monkeypatch) -> None:
    import asyncio

    import server
    from orchestrator.streaming import StreamingManager

    async def blocked_pipeline(**kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(server, "_PIPELINE_TIMEOUT_SEC", 0.01)
    monkeypatch.setattr(server, "_streaming_mgr", StreamingManager())
    monkeypatch.setattr(
        server,
        "_calienne",
        {"execution_manager": SimpleNamespace(execute=blocked_pipeline)},
    )

    response = await server.handle_query_stream(
        server.QueryRequest(query="hello"),
        SimpleNamespace(email="alice@example.com"),
    )
    chunks = [chunk async for chunk in response.body_iterator]
    events = [
        json.loads(line[6:])
        for chunk in chunks
        for line in chunk.splitlines()
        if line.startswith("data: ")
    ]

    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["stage"] == "timeout"


def test_auth_login_request_rejects_unknown_fields() -> None:
    from server import AuthLoginRequest

    with pytest.raises(ValidationError):
        AuthLoginRequest(email="a@b.com", password="x", is_admin=True)


def test_server_query_routes_use_execution_manager() -> None:
    from pathlib import Path

    source = Path("server.py").read_text(encoding="utf-8")
    assert source.count('_calienne["execution_manager"].execute(') == 2


@pytest.mark.asyncio
async def test_model_toggle_uses_full_model_identity_and_rejects_unknown(monkeypatch) -> None:
    import server
    from api_gateway import ProviderStrategy

    strategy = ProviderStrategy("HYBRID")
    pool = server._bootstrap_pool(strategy)
    monkeypatch.setattr(server, "_strategy", strategy)
    monkeypatch.setattr(server, "_pool", pool)
    model = server._get_dynamic_models()[0]

    result = await server.toggle_model_endpoint(
        server.ModelToggleRequest(id=model["full_id"], active=False),
        SimpleNamespace(role="admin"),
    )

    assert result["status"] == "success"
    updated = next(item for item in result["models"] if item["full_id"] == model["full_id"])
    assert updated["active"] is False

    with pytest.raises(server.HTTPException) as exc_info:
        await server.toggle_model_endpoint(
            server.ModelToggleRequest(id="missing/model", active=True),
            SimpleNamespace(role="admin"),
        )
    assert exc_info.value.status_code == 404
