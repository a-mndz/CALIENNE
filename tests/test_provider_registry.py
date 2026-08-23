"""Unit tests for ProviderRegistry, OS Keyring persistence, and dynamic role/judge assignments."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from api_gateway.strategy import ProviderStrategy
from api_gateway.rate_limiter import ProviderPool
from core.provider_registry import ProviderRegistry, CustomModelSpec, CustomProviderSpec


@pytest.fixture
def temp_registry(tmp_path: Path) -> ProviderRegistry:
    cfg_file = tmp_path / "custom_providers.json"
    return ProviderRegistry(config_path=cfg_file)


def test_provider_registry_register_and_get(temp_registry: ProviderRegistry) -> None:
    strategy = ProviderStrategy("HYBRID")
    pool = ProviderPool()

    models = [
        {"id": "llama3.3:70b", "name": "Llama 3.3 70B", "roles": ["generation", "judge"]},
        {"id": "qwen2.5:32b", "name": "Qwen 2.5 32B", "roles": ["breaker"]},
    ]

    provider = temp_registry.register_or_update_provider(
        name="Local Ollama",
        base_url="http://localhost:11434/v1",
        api_key="sk-test-secret-key-12345",
        models=models,
        provider_id="ollama_local",
        strategy=strategy,
        pool=pool,
    )

    assert provider.id == "ollama_local"
    assert provider.has_api_key is True
    assert len(provider.models) == 2
    assert provider.models[0].full_id == "ollama_local/llama3.3:70b"

    # Verify models were injected into strategy and pool
    assert "ollama_local/llama3.3:70b" in strategy.get_model_chain("generation")
    assert "ollama_local/llama3.3:70b" in strategy.get_model_chain("judge")
    assert "ollama_local/qwen2.5:32b" in strategy.get_model_chain("breaker")

    # Verify list view masks the key
    views = temp_registry.list_providers_view()
    assert len(views) == 1
    assert "2345" in views[0]["masked_key"]
    assert views[0]["name"] == "Local Ollama"


def test_set_primary_judge_and_role_updates(temp_registry: ProviderRegistry) -> None:
    strategy = ProviderStrategy("HYBRID")
    pool = ProviderPool()

    models = [
        {"id": "deepseek-chat", "name": "DeepSeek Chat", "roles": ["generation"]},
        {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner (R1)", "roles": ["judge"]},
    ]

    temp_registry.register_or_update_provider(
        name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-deepseek-key-9999",
        models=models,
        provider_id="deepseek",
        strategy=strategy,
        pool=pool,
    )

    judge_model = "deepseek/deepseek-reasoner"
    assert judge_model in strategy.get_model_chain("judge")

    # Set as primary judge
    temp_registry.set_primary_role_model("judge", judge_model, strategy=strategy)
    assert strategy.get_model_chain("judge")[0] == judge_model
    assert temp_registry.get_role_preferences()["primary_judge"] == judge_model

    # Update roles for deepseek-chat to also be a judge
    chat_model = "deepseek/deepseek-chat"
    temp_registry.update_model_roles(chat_model, ["generation", "judge"], strategy=strategy, pool=pool)
    assert chat_model in strategy.get_model_chain("judge")
    assert chat_model in strategy.get_model_chain("generation")


def test_provider_delete(temp_registry: ProviderRegistry) -> None:
    strategy = ProviderStrategy("HYBRID")
    pool = ProviderPool()

    models = [{"id": "m1", "roles": ["generation"]}]
    temp_registry.register_or_update_provider(
        name="Test Provider",
        base_url="http://test.local",
        models=models,
        provider_id="test_prov",
        strategy=strategy,
        pool=pool,
    )

    assert "test_prov/m1" in strategy.get_model_chain("generation")
    deleted = temp_registry.delete_provider("test_prov", strategy=strategy, pool=pool)
    assert deleted is True
    assert "test_prov/m1" not in strategy.get_model_chain("generation")
    assert temp_registry.get_provider("test_prov") is None


def test_parse_models_response_formats(temp_registry: ProviderRegistry) -> None:
    # OpenAI format
    openai_payload = {
        "data": [
            {"id": "gpt-4o", "name": "GPT-4o", "context_length": 128000},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
        ]
    }
    parsed = temp_registry._parse_models_response(openai_payload)
    assert len(parsed) == 2
    assert parsed[0]["id"] == "gpt-4o"

    # Ollama format
    ollama_payload = {
        "models": [
            {"name": "llama3.3:latest", "size": 4200000000},
            {"name": "deepseek-r1:14b", "size": 9000000000},
        ]
    }
    parsed_ollama = temp_registry._parse_models_response(ollama_payload)
    assert len(parsed_ollama) == 2
    assert any(m["id"] == "deepseek-r1:14b" for m in parsed_ollama)


@pytest.mark.asyncio
async def test_discover_models_endpoint(temp_registry: ProviderRegistry) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"id": "deepseek-ai/DeepSeek-V3", "name": "DeepSeek V3"},
            {"id": "meta-llama/Llama-3.3-70B-Instruct", "name": "Llama 3.3 70B"},
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        models = await temp_registry.discover_models("https://api.together.xyz/v1", api_key="test-key")
        assert len(models) == 2
        assert models[0]["id"] == "deepseek-ai/DeepSeek-V3"


@pytest.mark.asyncio
async def test_fastapi_discover_endpoint() -> None:
    import httpx
    import uuid
    from server import app
    from core.security import get_current_user
    from core.models import User

    fake_admin = User(id=uuid.uuid4(), email="admin@test.com", password_hash="hash", role="admin")
    app.dependency_overrides[get_current_user] = lambda: fake_admin

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [{"id": "model-1", "name": "Model 1"}]
    }

    try:
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post(
                    "/api/providers/discover",
                    json={"base_url": "https://api.openai.com/v1", "api_key": "sk-12345"},
                )
                assert res.status_code == 200
                data = res.json()
                assert data["status"] == "success"
                assert len(data["models"]) == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
