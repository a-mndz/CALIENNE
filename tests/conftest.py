"""Shared pytest fixtures and configuration for aetheris backend tests.

Provides:
- Fastapi dependency overrides (database, JWT)
- Mock AsyncAPIGateway / ProviderPool / StreamingManager
- Stub ExecutionPassport / SecurityValidator factories
- Deterministic UTC clock for time-sensitive tests
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

# Ensure tests can import aetheris modules regardless of cwd.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
VENV_SCRIPTS = ROOT / ".venv" / "Scripts"
if VENV_SCRIPTS.is_dir():
    os.environ["PATH"] = f"{VENV_SCRIPTS};{os.environ.get('PATH', '')}"

# Provide sane defaults so importing core/config.py does not blow up in tests.
# Note: pydantic-settings with case_sensitive=True and uppercase prefix reads
# ``UPPERCASE`` env vars; we set both forms for backwards compatibility.
_TEST_SECRET = "test-only-do-not-use-in-production-32chars-min"
os.environ.setdefault("AETHERIS_JWT_SECRET_KEY", _TEST_SECRET)
os.environ.setdefault("aetheris_JWT_SECRET_KEY", _TEST_SECRET)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/aetheris_test")
for _key in (
    "OPENROUTER_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "GROQ_API_KEY",
    "GITHUB_TOKEN",
    "MISTRAL_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "KIE_API_KEY",
    "UNLI_DEV_API_KEY",
):
    os.environ.setdefault(f"AETHERIS_{_key}", "")
    os.environ.setdefault(f"aetheris_{_key}", "")

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Override the default function-scoped loop so async fixtures survive."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@dataclass
class StubMetrics:
    """Stand-in for AgentExecutionMetrics that always reports success."""
    total_executions: int = 0
    successful_executions: int = 0


class StubProviderPool:
    """Minimal pool stand-in with predictable health for unit tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._priority_order: list[str] = ["local/sim"]

    def register_provider(self, name: str, roles: list[str] | None = None) -> None:
        if name not in self._priority_order:
            self._priority_order.append(name)

    def is_provider_healthy(self, name: str) -> bool:
        return True

    def is_provider_available(self, name: str) -> bool:
        return True

    def report_success(self, name: str) -> None:
        self.calls.append(("success", name))

    def report_failure(self, name: str) -> None:
        self.calls.append(("failure", name))

    def mark_provider_dead(self, name: str, cooldown_seconds: float = 60.0) -> None:
        self.calls.append(("dead", name))

    def get_health_metrics(self, name: str) -> Optional[dict]:
        return {"error_rate": 0.0, "success_rate": 1.0, "mean_latency_ms": 10.0}

    def get_all_statuses(self) -> list[dict]:
        return [{"provider": n, "status": "healthy"} for n in self._priority_order]

    def get_status(self, name: str) -> Optional[dict]:
        return {"provider": name, "status": "healthy", "is_available": True}


class StubStrategy:
    """Strategy that returns a deterministic single-item chain."""

    def __init__(self, mode: str = "HYBRID") -> None:
        self.mode = type("Mode", (), {"value": mode})()
        self.supported_roles = ["breaker", "generation", "judge"]

    def get_model_chain(self, role: str) -> list[str]:
        return [f"local/sim-for-{role}"]


class StubGateway:
    """Async gateway stub that returns deterministic canned responses."""

    def __init__(self, response_text: str = '{"answer":"stub","confidence":0.9}') -> None:
        self.response_text = response_text
        self.calls: list[dict] = []
        self._semaphore = asyncio.Semaphore(5)

    async def execute_with_fallback(
        self,
        *,
        prompt: str,
        role: str,
        strategy: Any,
        pool: Any,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> str:
        self.calls.append({"role": role, "prompt_len": len(prompt or "")})
        # Simulate an instruction-following model: when the caller asks for
        # specific JSON keys (DAG contract prompts), return exactly those
        # keys instead of the generic canned shape.
        if system_prompt and "exactly these keys:" in system_prompt:
            keys_part = system_prompt.split("exactly these keys:", 1)[1].strip().rstrip(".")
            keys = [k.strip() for k in keys_part.split(",") if k.strip()]
            if keys:
                import json as _json

                return _json.dumps({k: f"stub {k}" for k in keys})
        return self.response_text

    async def close(self) -> None:
        return None


class StubStreamingManager:
    """No-op streaming manager that satisfies the protocol used in pipeline."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def emit(self, request_id: str, event_type: Any, data: dict) -> None:
        self.events.append({"type": str(event_type), "data": data})

    async def emit_event(self, request_id: str, event: Any) -> None:
        self.events.append({"type": str(event.event if hasattr(event, "event") else event), "data": event.data if hasattr(event, "data") else {}})  # noqa: E501


class StubClaimManager:
    """Returns empty results so callers do not crash."""

    def extract_claims(self, text: str, agent: str) -> list:
        return []

    def validate_claim(self, claim: Any, evidence: Any = None) -> Any:
        return claim

    def store_claim(self, claim: Any, graph: Any) -> None:
        return None

    def track_claim_provenance(self, *args, **kwargs) -> None:
        return None

    def get_unverified_claims(self, claims: list) -> list:
        return []


class StubReasoningGraph:
    def get_failure_patterns(self, query: str) -> list:
        return []

    def record_failure_pattern(self, **kwargs) -> None:
        return None


@pytest.fixture
def stub_pool() -> StubProviderPool:
    return StubProviderPool()


@pytest.fixture
def stub_strategy() -> StubStrategy:
    return StubStrategy()


@pytest.fixture
def stub_gateway() -> StubGateway:
    return StubGateway()


@pytest.fixture
def stub_streaming() -> StubStreamingManager:
    return StubStreamingManager()


@pytest.fixture
def stub_claims() -> StubClaimManager:
    return StubClaimManager()


@pytest.fixture
def stub_graph() -> StubReasoningGraph:
    return StubReasoningGraph()


@pytest.fixture
def fixed_uuid() -> str:
    """Deterministic UUID for reproducible failure messages."""
    return "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def utc_now() -> datetime:
    """Frozen UTC timestamp for time-sensitive assertions."""
    return datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc)
