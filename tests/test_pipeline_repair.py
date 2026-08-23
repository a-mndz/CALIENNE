"""Phase 1 — Pipeline subsystem targeted regression tests.

Covers CRIT-001 (dual paths), HIGH-019 (claim toggle), HIGH-011 (task safety).
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.unit


class TestCRIT001LegacyPathBlocked:
    """CRIT-001 — DecisionEngine is the sole execution path."""

    def test_missing_decision_engine_raises(
        self, monkeypatch: pytest.MonkeyPatch, stub_gateway, stub_strategy, stub_pool
    ) -> None:
        monkeypatch.delenv("calienne_LEGACY_PIPELINE_ENABLED", raising=False)
        from orchestrator.pipelines import run_micro_mode

        with pytest.raises(RuntimeError) as exc:
            import asyncio as _aio
            _aio.run(run_micro_mode(
                user_query="hello",
                gateway=stub_gateway,
                strategy=stub_strategy,
                pool=stub_pool,
                decision_engine=None,
            ))
        assert "CRIT-001" in str(exc.value)
        assert "decision_engine is required" in str(exc.value)

    def test_legacy_opt_in_flag_no_longer_revives_legacy_path(
        self, monkeypatch: pytest.MonkeyPatch, stub_gateway, stub_strategy, stub_pool
    ) -> None:
        """The legacy inline branch is deleted — the env var must not resurrect it."""
        from orchestrator import pipelines

        monkeypatch.setenv("calienne_LEGACY_PIPELINE_ENABLED", "true")
        assert not hasattr(pipelines, "_is_legacy_pipeline_opted_in")
        assert not hasattr(pipelines, "_legacy_pipeline_blocked_msg")

        with pytest.raises(RuntimeError, match="CRIT-001"):
            import asyncio as _aio
            _aio.run(pipelines.run_micro_mode(
                user_query="hello",
                gateway=stub_gateway,
                strategy=stub_strategy,
                pool=stub_pool,
                decision_engine=None,
            ))


class TestHIGH019ClaimExtractionToggle:
    """Step 14 — firewall is on by default and env var is now an emergency bypass."""

    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("calienne_DISABLE_CLAIM_EXTRACTION", raising=False)
        from orchestrator.pipelines import _is_claim_extraction_enabled
        assert _is_claim_extraction_enabled() is True

    def test_enabled_when_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("calienne_DISABLE_CLAIM_EXTRACTION", "0")
        from orchestrator.pipelines import _is_claim_extraction_enabled
        assert _is_claim_extraction_enabled() is True

    def test_enabled_when_off_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("calienne_DISABLE_CLAIM_EXTRACTION", "off")
        from orchestrator.pipelines import _is_claim_extraction_enabled
        assert _is_claim_extraction_enabled() is True

    def test_disabled_when_explicit_bypass_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("calienne_DISABLE_CLAIM_EXTRACTION", "1")
        from orchestrator.pipelines import _is_claim_extraction_enabled
        assert _is_claim_extraction_enabled() is False


class TestHIGH011FireAndForgetTaskSafety:
    """HIGH-011 — streamed tasks must surface exceptions via callback."""

    @pytest.mark.asyncio
    async def test_callback_runs_on_exception(self) -> None:
        from orchestrator.decisions import safe_create_task_broadcast

        async def crash():
            raise RuntimeError("simulated streaming failure")

        task = safe_create_task_broadcast(crash(), name="test-crash")
        await asyncio.sleep(0.05)
        assert task.done()
        assert isinstance(task.exception(), RuntimeError)

    @pytest.mark.asyncio
    async def test_callback_runs_on_success(self) -> None:
        from orchestrator.decisions import safe_create_task_broadcast

        async def ok():
            return "ok"

        task = safe_create_task_broadcast(ok(), name="test-ok")
        result = await task
        assert result == "ok"
