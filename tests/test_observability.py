"""Observability tests — structured logging config and Prometheus exposition.

Covers `core.config.configure_logging` and `orchestrator.metrics`.
"""

from __future__ import annotations

import json
import logging

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def restore_root_logging():
    """Undo the global logging mutation configure_logging() performs."""
    import core.config as cfg

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_flag = cfg._logging_configured
    saved_settings = cfg._settings
    try:
        yield
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_level)
        cfg._logging_configured = saved_flag
        cfg._settings = saved_settings


def _configure(monkeypatch, environment: str):
    import core.config as cfg

    cfg._settings = None
    monkeypatch.setenv("AETHERIS_ENVIRONMENT", environment)
    cfg.configure_logging(force=True)
    return logging.getLogger()


class TestStructuredLogging:
    def test_production_emits_parseable_json(
        self, monkeypatch: pytest.MonkeyPatch, capsys, restore_root_logging
    ) -> None:
        _configure(monkeypatch, "production")

        # A stdlib logger with %-style args — the shape the whole codebase uses.
        logging.getLogger("aetheris.demo").info(
            "provider call ok provider=%s latency=%d", "groq", 42
        )

        line = capsys.readouterr().err.strip().splitlines()[-1]
        payload = json.loads(line)
        assert payload["event"] == "provider call ok provider=groq latency=42"
        assert payload["level"] == "info"
        assert payload["logger"] == "aetheris.demo"
        assert "timestamp" in payload

    def test_development_is_not_json(
        self, monkeypatch: pytest.MonkeyPatch, capsys, restore_root_logging
    ) -> None:
        _configure(monkeypatch, "development")
        logging.getLogger("aetheris.demo").info("human readable please")

        line = capsys.readouterr().err.strip().splitlines()[-1]
        assert "human readable please" in line
        with pytest.raises(json.JSONDecodeError):
            json.loads(line)

    def test_production_traceback_omits_locals(
        self, monkeypatch: pytest.MonkeyPatch, capsys, restore_root_logging
    ) -> None:
        """Security: locals in scope at raise time must never reach the log sink.

        structlog's default ``dict_tracebacks`` serialises every local, which
        would put API keys and DB passwords into the aggregator.
        """
        _configure(monkeypatch, "production")

        def inner() -> None:
            api_key = "sk-secret-must-not-be-logged"  # noqa: F841
            raise ValueError("boom")

        try:
            inner()
        except ValueError:
            logging.getLogger("aetheris.demo").exception("call failed")

        captured = capsys.readouterr().err
        assert "sk-secret-must-not-be-logged" not in captured

        payload = json.loads(captured.strip().splitlines()[-1])
        frames = payload["exception"][0]["frames"]
        assert frames, "frames must survive — only locals are dropped"
        assert all("locals" not in frame for frame in frames)

    def test_idempotent_without_force(
        self, monkeypatch: pytest.MonkeyPatch, restore_root_logging
    ) -> None:
        """Both main.py and server.py call it; the second must not stack handlers."""
        import core.config as cfg

        _configure(monkeypatch, "development")
        count = len(logging.getLogger().handlers)
        cfg.configure_logging()
        cfg.configure_logging()
        assert len(logging.getLogger().handlers) == count


class TestPrometheusExposition:
    def test_render_includes_refreshed_series(self) -> None:
        from orchestrator import metrics

        class _Metrics:
            breaker_pass_rate = 0.5
            judge_agreement_rate = 0.25
            synthesis_quality_avg = 7.5
            total_decisions = 8

        class _Engine:
            def get_metrics(self) -> _Metrics:
                return _Metrics()

        class _Pool:
            def get_all_statuses(self) -> list[dict]:
                return [{
                    "provider": "groq/llama3",
                    "status": "degraded",
                    "consecutive_failures": 1,
                    "is_available": True,
                }]

        metrics.refresh(decision_engine=_Engine(), pool=_Pool())
        text = metrics.render().decode()

        assert "aetheris_breaker_pass_rate 0.5" in text
        assert "aetheris_synthesis_quality_avg 7.5" in text
        assert 'provider="groq/llama3",status="degraded"} 1.0' in text
        # Inactive statuses must still be emitted, otherwise a status="dead"
        # alert has no series to evaluate and can never fire.
        assert 'provider="groq/llama3",status="dead"} 0.0' in text

    def test_refresh_tolerates_missing_components(self) -> None:
        """A scrape during startup must not 500."""
        from orchestrator import metrics

        metrics.refresh(decision_engine=None, pool=None)

        class _Broken:
            def get_metrics(self):
                raise RuntimeError("not ready")

        metrics.refresh(decision_engine=_Broken(), pool=_Broken())
        assert b"aetheris_breaker_pass_rate" in metrics.render()

    def test_self_check_passes(self) -> None:
        from orchestrator import metrics

        metrics.demo()


class TestMetricsEndpointAuth:
    """The scrape path has its own bearer token — Prometheus has no JWT cookie.

    Calls the handler directly: no TestClient, so no lifespan and no PostgreSQL.
    """

    @staticmethod
    def _request(authorization: str | None = None):
        from starlette.datastructures import Headers

        class _Req:
            headers = Headers({"authorization": authorization} if authorization else {})

        return _Req()

    def _call(self, monkeypatch: pytest.MonkeyPatch, environment: str, token: str,
              authorization: str | None = None):
        import asyncio

        import core.config as cfg
        import server

        cfg._settings = None
        monkeypatch.setenv("AETHERIS_ENVIRONMENT", environment)
        monkeypatch.setenv("AETHERIS_METRICS_TOKEN", token)
        try:
            return asyncio.run(server.prometheus_metrics(self._request(authorization)))
        finally:
            cfg._settings = None

    def test_open_in_development_when_token_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = self._call(monkeypatch, "development", "")
        assert response.status_code == 200
        assert b"aetheris_breaker_pass_rate" in response.body

    def test_production_refuses_when_token_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unconfigured must fail closed, not silently expose internals."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            self._call(monkeypatch, "production", "")
        assert exc.value.status_code == 503

    @pytest.mark.parametrize(
        "authorization",
        [
            None,
            "Bearer wrong-token",
            "Basic scrape-me-please",
            "scrape-me-please",
            # compare_digest on str raises TypeError for non-ASCII input —
            # a malformed header must be a clean 401, never a 500.
            "Bearer ñoño-pi-token",
        ],
    )
    def test_rejects_bad_credentials(
        self, monkeypatch: pytest.MonkeyPatch, authorization: str | None
    ) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            self._call(monkeypatch, "production", "scrape-me-please", authorization)
        assert exc.value.status_code == 401

    def test_accepts_correct_bearer_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = self._call(
            monkeypatch, "production", "scrape-me-please", "Bearer scrape-me-please"
        )
        assert response.status_code == 200
        assert response.media_type.startswith("text/plain")
