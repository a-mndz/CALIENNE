"""Phase 1 — Authentication subsystem targeted regression tests.

Covers CRIT-004 (CORS), CRIT-005 (JWT secret), CRIT-007 (live key rejection),
HIGH-002 (duplicate error unification), HIGH-013 (httpOnly cookie),
HIGH-014 (rate limit), HIGH-015 (session ownership), MED-021 (input validation).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.unit


class TestCRIT007LiveKeyRejection:
    def test_live_openrouter_key_rejected_via_validator(self, monkeypatch) -> None:
        from pydantic import ValidationError

        from core.config import calienneConfig
        monkeypatch.delenv("CALIENNE_ALLOW_LIVE_KEYS", raising=False)
        # Use kwargs and disable .env so explicit kwargs take precedence.
        with pytest.raises(ValidationError) as exc:
            calienneConfig(
                _env_file=None,
                JWT_SECRET_KEY="strong-validator-test-secret-not-real-12345",
                OPENROUTER_API_KEY="sk-or-v1-aaaaaaaaaaaaaaaaaaa",
                NVIDIA_NIM_API_KEY="",
                GROQ_API_KEY="",
                GITHUB_TOKEN="",
                MISTRAL_API_KEY="",
                GOOGLE_API_KEY="",
                OPENAI_API_KEY="",
                KIE_API_KEY="",
                UNLI_DEV_API_KEY="",
            )
        assert "OPENROUTER_API_KEY" in str(exc.value)

    def test_live_nvidia_key_rejected(self, monkeypatch) -> None:
        from pydantic import ValidationError

        from core.config import calienneConfig
        monkeypatch.delenv("CALIENNE_ALLOW_LIVE_KEYS", raising=False)
        with pytest.raises(ValidationError):
            calienneConfig(
                _env_file=None,
                JWT_SECRET_KEY="strong-validator-test-secret-not-real-12345",
                OPENROUTER_API_KEY="",
                NVIDIA_NIM_API_KEY="nvapi-aaaaaaaaaaaaaaaaaaa",
                GROQ_API_KEY="",
                GITHUB_TOKEN="",
                MISTRAL_API_KEY="",
                GOOGLE_API_KEY="",
                OPENAI_API_KEY="",
                KIE_API_KEY="",
                UNLI_DEV_API_KEY="",
            )

    def test_empty_keys_pass(self) -> None:
        from core.config import calienneConfig
        s = calienneConfig(
            _env_file=None,
            JWT_SECRET_KEY="strong-validator-test-secret-not-real-12345",
            OPENROUTER_API_KEY="",
            NVIDIA_NIM_API_KEY="",
            GROQ_API_KEY="",
            GITHUB_TOKEN="",
            MISTRAL_API_KEY="",
            GOOGLE_API_KEY="",
            OPENAI_API_KEY="",
            KIE_API_KEY="",
            UNLI_DEV_API_KEY="",
        )
        assert s.OPENROUTER_API_KEY == ""


class TestCRIT005JWTSecretHardening:
    @staticmethod
    def _construct(**overrides):
        old = os.environ.pop("CALIENNE_JWT_SECRET_KEY", None)
        try:
            from core.config import calienneConfig
            return calienneConfig(_env_file=None, **overrides)
        finally:
            if old is not None:
                os.environ["CALIENNE_JWT_SECRET_KEY"] = old

    def test_empty_secret_rejected(self) -> None:
        from pydantic import ValidationError

        from core.config import calienneConfig
        with pytest.raises(ValidationError) as exc:
            self._construct(
                JWT_SECRET_KEY="",
                OPENROUTER_API_KEY="",
                NVIDIA_NIM_API_KEY="",
                GROQ_API_KEY="",
                GITHUB_TOKEN="",
                MISTRAL_API_KEY="",
                GOOGLE_API_KEY="",
                OPENAI_API_KEY="",
                KIE_API_KEY="",
                UNLI_DEV_API_KEY="",
            )
        assert "JWT_SECRET_KEY" in str(exc.value)

    def test_known_demo_secret_rejected(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._construct(
                JWT_SECRET_KEY="09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7",
                OPENROUTER_API_KEY="",
                NVIDIA_NIM_API_KEY="",
                GROQ_API_KEY="",
                GITHUB_TOKEN="",
                MISTRAL_API_KEY="",
                GOOGLE_API_KEY="",
                OPENAI_API_KEY="",
                KIE_API_KEY="",
                UNLI_DEV_API_KEY="",
            )

    def test_short_secret_rejected(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._construct(
                JWT_SECRET_KEY="short",
                OPENROUTER_API_KEY="",
                NVIDIA_NIM_API_KEY="",
                GROQ_API_KEY="",
                GITHUB_TOKEN="",
                MISTRAL_API_KEY="",
                GOOGLE_API_KEY="",
                OPENAI_API_KEY="",
                KIE_API_KEY="",
                UNLI_DEV_API_KEY="",
            )

    def test_strong_secret_accepted(self) -> None:
        os.environ["CALIENNE_JWT_SECRET_KEY"] = "strong-operator-managed-32char-secret-12345"
        try:
            from core.config import calienneConfig
            s = calienneConfig(
                _env_file=None,
                OPENROUTER_API_KEY="",
                NVIDIA_NIM_API_KEY="",
                GROQ_API_KEY="",
                GITHUB_TOKEN="",
                MISTRAL_API_KEY="",
                GOOGLE_API_KEY="",
                OPENAI_API_KEY="",
                KIE_API_KEY="",
                UNLI_DEV_API_KEY="",
            )
        finally:
            os.environ["CALIENNE_JWT_SECRET_KEY"] = os.environ.get("CALIENNE_JWT_SECRET_KEY", "test-only-do-not-use-in-production-32chars-min")  # noqa: E501
        assert "strong-" in s.JWT_SECRET_KEY


class TestHIGH002DuplicateErrorUnification:
    def test_same_identity_for_both_imports(self) -> None:
        from core.error_handlers import SecurityValidationError as Err
        from core.security import SecurityValidationError as Sec
        assert Sec is Err


class TestCRIT004CORSRequiresExplicitOrigins:
    def test_wildcard_origin_rejected(self) -> None:
        from unittest.mock import patch

        from server import _resolve_cors_origins
        with patch("server.get_settings") as m:
            m.return_value.CORS_ORIGINS = "*"
            with pytest.raises(RuntimeError) as exc:
                _resolve_cors_origins()
        assert "CORS" in str(exc.value) or "wildcard" in str(exc.value).lower()

    def test_explicit_origins_accepted(self) -> None:
        from unittest.mock import patch

        from server import _resolve_cors_origins
        with patch("server.get_settings") as m:
            m.return_value.CORS_ORIGINS = "http://localhost:5173,http://localhost:8000"
            result = _resolve_cors_origins()
        assert "http://localhost:5173" in result


class TestHIGH015SessionOwnership:
    def test_owner_email_recorded_on_create(self) -> None:
        from orchestrator.conversation import ConversationDirector
        director = ConversationDirector()
        sess = director.create_session("sess", owner_email="alice@example.com")
        assert sess.owner_email == "alice@example.com"

    def test_ownerless_session_accepts_any_authenticated_user(self) -> None:
        from orchestrator.conversation import ConversationDirector
        director = ConversationDirector()
        director.create_session("sess-public")
        assert director.verify_access("sess-public", "anyone@example.com") is True

    def test_owned_session_rejects_other_user(self) -> None:
        from orchestrator.conversation import ConversationDirector
        director = ConversationDirector()
        director.create_session("sess-private", owner_email="alice@example.com")
        assert director.verify_access("sess-private", "alice@example.com") is True
        assert director.verify_access("sess-private", "bob@example.com") is False

    def test_unknown_session_rejects(self) -> None:
        from orchestrator.conversation import ConversationDirector
        director = ConversationDirector()
        assert director.verify_access("nope", "alice@example.com") is False


class TestHIGH014AuthRateLimit:
    def test_rate_limit_blocks_after_threshold(self) -> None:
        from server import _enforce_auth_rate_limit
        _test_ip = f"203.0.113.{uuid.uuid4().int % 250 + 1}"
        # First N requests should pass
        for _ in range(5):
            assert _enforce_auth_rate_limit(_test_ip) is True
        # 6th should be blocked
        assert _enforce_auth_rate_limit(_test_ip) is False


class TestHIGH013HttpOnlyCookie:
    def test_cookie_attributes_set(self) -> None:
        from fastapi.responses import JSONResponse

        from server import _set_auth_cookie
        response = JSONResponse({"hello": "world"})
        _set_auth_cookie(response, "fake-jwt-token")
        cookie_header = response.headers.get("set-cookie", "")
        assert "HttpOnly" in cookie_header
        assert "SameSite=strict" in cookie_header or "samesite=strict" in cookie_header.lower()
        assert "calienne_auth=" in cookie_header or "calienne_auth=" in cookie_header


class TestMED021AuthInputValidation:
    def test_email_validator_rejects_garbage(self) -> None:
        from pydantic import ValidationError

        from server import AuthRegisterRequest
        with pytest.raises(ValidationError):
            AuthRegisterRequest(email="not-an-email", password="hunter2!!")

    def test_email_validator_normalises_case(self) -> None:
        from server import AuthRegisterRequest
        req = AuthRegisterRequest(email="Alice@Example.COM", password="hunter2!!")
        assert req.email == "alice@example.com"

    def test_password_too_short_rejected(self) -> None:
        from pydantic import ValidationError

        from server import AuthRegisterRequest
        with pytest.raises(ValidationError):
            AuthRegisterRequest(email="alice@example.com", password="short")

    def test_password_low_entropy_rejected(self) -> None:
        from pydantic import ValidationError

        from server import AuthRegisterRequest
        with pytest.raises(ValidationError):
            AuthRegisterRequest(email="alice@example.com", password="aaaaaaaa")
