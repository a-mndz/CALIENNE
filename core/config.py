"""
aetheris — Adaptive Multi-Model Reasoning Orchestrator
Configuration module using pydantic-settings for environment variable loading
with optional API credentials, hardware constraints, and logging validation.
"""

import logging
import os
import sys
from typing import Any, ClassVar, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class aetherisConfig(BaseSettings):
    """
    Central configuration for the aetheris multi-agent orchestration system.

    All values are loaded from environment variables (or a `.env` file).
    Prefix: aetheris_  (e.g. aetheris_OPENROUTER_API_KEY)
    """

    model_config = SettingsConfigDict(
        env_prefix="AETHERIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        # The ``aetheris_`` lowercase prefix remains documented for legacy
        # callers; uppercase ``AETHERIS_*`` is canonical because the
        # settings class uses ``case_sensitive=True``.
        env_ignore_empty=False,
    )

    # ── API Keys (optional; blank values activate Simulation Mode) ───────

    # CRIT-007 audit fix: each provider key is rejected when it contains
    # a hardcoded leak marker prefix that triggered the audit (e.g. live
    # ``sk-…`` OpenRouter keys, NVIDIA ``nvapi-…`` tokens, etc.).  Even when
    # operators delete the demo .env values, any keys that still cycle
    # through the environment are refused — defence in depth.

    LEAKED_KEY_PREFIXES: ClassVar[tuple[str, ...]] = (
        "sk-or-v1-",
        "sk-proj-",
        "sk-ZO",
        "nvapi-",
        "gsk_p",
        "github_pat_",
        "AQ.Ab8",
    )

    @classmethod
    def _sanitize_provider_key(cls, field_name: str, value: str) -> str:
        """Reject any non-empty key carrying a known live prefix (CRIT-007).

        Operators who intentionally want to use live keys sourced from
        the OS secret store (see ``secrets_bootstrap.py``) can opt in
        by exporting ``AETHERIS_ALLOW_LIVE_KEYS=1`` in the process
        environment before invoking the application.  This keeps the
        audit guard active for *unintended* loads (a key ending up in
        ``.env``, a typo'd CI secret, etc.) while letting developers
        run with their real keys when they knowingly choose to.

        The opt-in is logged so it leaves a paper trail in startup
        output — never a silent override.
        """
        if value and any(value.startswith(prefix) for prefix in cls.LEAKED_KEY_PREFIXES):
            if os.environ.get("AETHERIS_ALLOW_LIVE_KEYS") == "1":
                logger.warning(
                    "CRIT-007 override active (AETHERIS_ALLOW_LIVE_KEYS=1); "
                    "loading live %s. Audit trail: %s.",
                    field_name,
                    "intentional developer opt-in",
                )
                return value
            raise ValueError(f"Live API key prefix detected for {field_name}. Refusing to load.")
        return value

    OPENROUTER_API_KEY: str = Field(
        default="",
        description="API key for the OpenRouter inference gateway. Leave empty for Simulation Mode.",
    )
    NVIDIA_NIM_API_KEY: str = Field(
        default="",
        description="API key for NVIDIA NIM micro-services. Leave empty for Simulation Mode.",
    )
    GROQ_API_KEY: str = Field(
        default="",
        description="API key for Groq.",
    )
    GITHUB_TOKEN: str = Field(
        default="",
        description="GitHub models token.",
    )
    MISTRAL_API_KEY: str = Field(
        default="",
        description="API key for Mistral.",
    )
    GOOGLE_API_KEY: str = Field(
        default="",
        description="API key for Google AI Studio.",
    )
    OPENAI_API_KEY: str = Field(
        default="",
        description="API key for OpenAI.",
    )
    KIE_API_KEY: str = Field(
        default="",
        description="API key for Kie.ai.",
    )
    UNLI_DEV_API_KEY: str = Field(
        default="",
        description="API key for UNLI.dev. Leave empty for Simulation Mode.",
    )

    @field_validator(
        "OPENROUTER_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "GROQ_API_KEY",
        "GITHUB_TOKEN",
        "MISTRAL_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "KIE_API_KEY",
        "UNLI_DEV_API_KEY",
        mode="after",
    )
    @classmethod
    def _reject_live_provider_keys(cls, value: str) -> str:
        return cls._sanitize_provider_key("provider_key", value)

    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://user:password@localhost:5432/aetheris",
        validation_alias="DATABASE_URL",
        description="PostgreSQL connection string using asyncpg",
    )

    # HIGH-016: Database SSL is configurable via environment (Phase 1).
    DATABASE_SSL: bool = Field(
        default=False,
        validation_alias="DATABASE_SSL",
        description=(
            "Enable SSL for database connections.  Default off to keep local "
            "development friction-free; production deployments MUST set this to true."
        ),
    )

    # CRIT-004: explicit CORS allowlist.  Wildcards combined with credentials
    # are forbidden by the CORS spec; we read a comma-separated allowlist
    # from CORS_ORIGINS and refuse the wildcard.
    CORS_ORIGINS: str = Field(
        default="http://localhost:5173,http://localhost:8000,http://127.0.0.1:8000",
        validation_alias="CORS_ORIGINS",
        description=(
            "Comma-separated explicit origin allowlist used by the CORS middleware. "
            "Wildcards are rejected to preserve authenticated session semantics."
        ),
    )

    # MED-019 / MED-021 helpers for Authentication middleware.
    AUTH_COOKIE_NAME: str = Field(
        default="aetheris_auth",
        validation_alias="AETHERIS_AUTH_COOKIE_NAME",
        description="Name of the httpOnly session cookie used for JWT delivery.",
    )

    # HIGH-014: per-IP rate limit on /auth/login and /auth/register.
    AUTH_RATE_LIMIT_PER_MINUTE: int = Field(
        default=5,
        validation_alias="AETHERIS_AUTH_RATE_LIMIT_PER_MINUTE",
        description="Maximum number of /auth/* requests a single IP may issue per minute.",
    )

    BREAKER_TIMEOUT_MS: int = Field(
        default=100,
        ge=100,
        le=60_000,
        validation_alias="AETHERIS_BREAKER_TIMEOUT_MS",
        description=(
            "Breaker gate budget in milliseconds. 100 (the default) fits "
            "simulation mode; a live LLM round-trip needs ~5000-8000. On "
            "expiry the gate fails open and the pipeline continues."
        ),
    )

    JWT_SECRET_KEY: str = Field(
        default="",
        validation_alias="AETHERIS_JWT_SECRET_KEY",
        description=(
            "REQUIRED: secret key used for signing JWT tokens.  Set via "
            "AETHERIS_JWT_SECRET_KEY environment variable.  Application "
            "startup rejects the empty default (CRIT-005)."
        ),
    )

    # CRIT-005 audit finding: a hardcoded fallback secret makes every
    # shipped install forgeable; reject any value not provided by the
    # operator and enforce a minimum key length.
    _FORBIDDEN_JWT_DEFAULTS: ClassVar[set[str]] = {
        "",
        "change-me",
        "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7",
    }
    MIN_JWT_SECRET_LENGTH: ClassVar[int] = 32

    @field_validator("JWT_SECRET_KEY", mode="after")
    @classmethod
    def _reject_default_or_weak_secret(cls, value: str) -> str:
        """Refuse to start with the canonical demo fallback or a weak key (CRIT-005)."""
        if value in cls._FORBIDDEN_JWT_DEFAULTS:
            raise ValueError(
                "JWT_SECRET_KEY must be set to a non-default value via "
                "the aetheris_JWT_SECRET_KEY environment variable. "
                "An empty/known-demo value is refused because JWTs would "
                "be forgeable."
            )
        if len(value) < cls.MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                "JWT_SECRET_KEY must be at least "
                f"{cls.MIN_JWT_SECRET_LENGTH} characters long."
            )
        return value

    JWT_ALGORITHM: str = Field(
        default="HS256",
        # Tier 0.6: the alias was lowercase "aetheris_*", which silently
        # ignored the documented uppercase AETHERIS_* form. Both accepted,
        # uppercase first.
        validation_alias=AliasChoices(
            "AETHERIS_JWT_ALGORITHM", "aetheris_JWT_ALGORITHM"
        ),
        description="Algorithm used for signing JWT tokens",
    )

    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60,
        validation_alias=AliasChoices(
            "AETHERIS_JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
            "aetheris_JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        ),
        description="Duration in minutes that access tokens are valid for",
    )


    # ── Hardware Constraints (local fallback models) ─────────────────────

    LOCAL_MODEL_VRAM_LIMIT_MB: int = Field(
        default=6144,  # 6 GB = 6 × 1024 MB
        description=(
            "Hard ceiling (in MB) on VRAM that local fallback models may "
            "allocate. Defaults to 6 144 MB (6 GB) to prevent OOM crashes "
            "on the host GPU."
        ),
    )

    @field_validator("LOCAL_MODEL_VRAM_LIMIT_MB", mode="after")
    @classmethod
    def _enforce_vram_cap(cls, value: int) -> int:
        """
        Strictly cap VRAM allocation at 6 GB (6 144 MB).
        """
        max_allowed_mb = 6144  # 6 GB hard cap
        if value > max_allowed_mb:
            raise ValueError(
                f"LOCAL_MODEL_VRAM_LIMIT_MB={value} MB exceeds the 6 GB "
                f"({max_allowed_mb} MB) safety cap. Refusing to allocate "
                "more VRAM to prevent OOM crashes on the host GPU."
            )
        if value <= 0:
            raise ValueError(
                "LOCAL_MODEL_VRAM_LIMIT_MB must be a positive integer."
            )
        return value

    # ── Logging ──────────────────────────────────────────────────────────

    LOG_LEVEL: str = Field(
        default="INFO",
        description="Python logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).",
    )
    LOG_FORMAT: str = Field(
        default="%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s",
        description=(
            "Format string for Python's logging.Formatter. Only consulted by the "
            "legacy plain-text fallback in configure_logging() when structlog is "
            "unavailable; the structlog renderers ignore it."
        ),
    )
    ENVIRONMENT: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias="AETHERIS_ENVIRONMENT",
        description="Runtime environment used for security-sensitive defaults.",
    )
    LOG_MODEL_IO: bool = Field(
        default=False,
        validation_alias="AETHERIS_LOG_MODEL_IO",
        description="Write full model prompts and responses to logs/model_io.log.",
    )
    METRICS_TOKEN: str = Field(
        default="",
        validation_alias="AETHERIS_METRICS_TOKEN",
        description=(
            "Bearer token required to scrape /metrics. Prometheus cannot present "
            "the JWT cookie the admin endpoints use, so the scrape path gets its "
            "own credential. Mandatory in production; optional elsewhere."
        ),
    )

    @field_validator("LOG_LEVEL", mode="after")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        normalised = value.upper().strip()
        if normalised not in allowed:
            raise ValueError(
                f"LOG_LEVEL must be one of {allowed}, got '{value}'."
            )
        return normalised

    # ── Lowercase Property Backwards Compatibility ──────────────────────

    @property
    def openrouter_api_key(self) -> str:
        return self.OPENROUTER_API_KEY

    @property
    def nvidia_nim_api_key(self) -> str:
        return self.NVIDIA_NIM_API_KEY

    @property
    def groq_api_key(self) -> str:
        return self.GROQ_API_KEY

    @property
    def github_token(self) -> str:
        return self.GITHUB_TOKEN

    @property
    def mistral_api_key(self) -> str:
        return self.MISTRAL_API_KEY

    @property
    def google_api_key(self) -> str:
        return self.GOOGLE_API_KEY

    @property
    def openai_api_key(self) -> str:
        return self.OPENAI_API_KEY

    @property
    def kie_api_key(self) -> str:
        return self.KIE_API_KEY

    @property
    def unli_dev_api_key(self) -> str:
        return self.UNLI_DEV_API_KEY

    @property
    def database_url(self) -> str:
        return self.DATABASE_URL


# ── Singleton accessor ───────────────────────────────────────────────────

_settings: aetherisConfig | None = None


def get_settings() -> aetherisConfig:
    """Return a cached, validated aetherisConfig instance (singleton)."""
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = aetherisConfig()  # type: ignore[call-arg]
    return _settings


# ── Structured Logging ───────────────────────────────────────────────────

_logging_configured = False


def configure_logging(
    settings: aetherisConfig | None = None,
    *,
    force: bool = False,
) -> None:
    """Route every log record — stdlib and structlog alike — through one chain.

    JSON lines when ``ENVIRONMENT == "production"`` so log aggregators can parse
    them; a coloured console renderer everywhere else, because JSON in a dev
    terminal is unreadable and people respond by turning logging off.

    The whole codebase logs via ``logging.getLogger(__name__)`` with ``%``-style
    args. Those records are *foreign* to structlog, so they are piped through
    :class:`structlog.stdlib.ProcessorFormatter`, which applies the same
    processor chain and renderer. No call sites need to change.

    Idempotent — safe to call from both ``main.py`` and ``server.py``'s lifespan.
    Pass ``force=True`` to re-apply after a settings change (tests).
    """
    global _logging_configured  # noqa: PLW0603
    if _logging_configured and not force:
        return

    settings = settings or get_settings()
    level = getattr(logging, settings.LOG_LEVEL, logging.INFO)
    root = logging.getLogger()

    try:
        import structlog
    except ImportError:  # pragma: no cover - structlog is a declared dependency
        # ponytail: plain-text fallback so a missing optional wheel degrades
        # instead of taking the process down. Remove once CI pins are enforced.
        logging.basicConfig(level=level, format=settings.LOG_FORMAT, force=True)
        root.warning("structlog unavailable — falling back to plain-text logging.")
        _logging_configured = True
        return

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.ENVIRONMENT == "production":
        # show_locals=False is a security requirement, not a style choice: the
        # default dict_tracebacks serialises every local in scope at raise time,
        # which puts API keys, JWTs, and DB passwords into the log aggregator.
        exc_processor = structlog.processors.ExceptionRenderer(
            structlog.tracebacks.ExceptionDictTransformer(show_locals=False)
        )
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        exc_processor = structlog.processors.format_exc_info
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            *shared_processors,
            exc_processor,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[*shared_processors, exc_processor],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )

    for existing in root.handlers[:]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
    _logging_configured = True
