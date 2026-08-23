"""
calienne — Adaptive Multi-Model Reasoning Orchestrator
Web Server: FastAPI backend serving the web UI and pipeline API.

Launch with:  python main.py --web
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional, Union

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator, model_validator
from pydantic import Field as PField
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# CRIT-007: load provider API keys from the OS secret store BEFORE
# anything that transitively imports ``core.config``.  Idempotent —
# safe to call even when ``main.py`` has already done so.
import secrets_bootstrap  # noqa: F401  (side-effecting import)
from api_gateway import AsyncAPIGateway, ProviderPool, ProviderStrategy
from api_gateway.rate_limiter import (
    HealthMetrics,
    ProviderStatus,
    extract_provider_key,
)
from core.config import configure_logging, get_settings
from core.database import get_db, verify_schema_current
from core.models import ConversationMessageRecord, ConversationSessionRecord, User
from core.provider_registry import get_provider_registry
from core.security import (
    SecurityValidationError,
    create_access_token,
    get_current_user,
    hash_password,
    require_role,
    verify_password,
)
from orchestrator import metrics
from orchestrator.background_tasks import cancel_background_tasks, create_background_tasks
from orchestrator.calienne_orchestrator import (
    create_request_passport,
    initialize_calienne_components,
)
from orchestrator.conversation import ConversationState
from orchestrator.memory_search import hydrate_history
from orchestrator.pipelines import _build_frontend_payload
from orchestrator.streaming import EventType, StreamingManager
from telemetry.observer import observer

logger = logging.getLogger("calienne.web")

_PIPELINE_TIMEOUT_SEC = 900
_MAX_REQUEST_BODY_BYTES = 100_000

# ── Global infrastructure (initialised in lifespan) ─────────────────────
_gateway: AsyncAPIGateway | None = None
_strategy: ProviderStrategy | None = None
_pool: ProviderPool | None = None
_streaming_mgr: StreamingManager = StreamingManager()
_calienne: dict[str, Any] = {}
_background_tasks: list[asyncio.Task] = []

# HIGH-014 — fixed-window in-process limiter for /auth/* routes.
_auth_rate_log: dict[str, list[float]] = {}
_AUTH_RATE_WINDOW_SEC = 60.0
# Hard cap on tracked IPs: the log is process-global, so without a bound a
# scrub of unique source IPs grows it without limit (memory-exhaustion
# vector). Expired entries are evicted first; under a full cap of live
# entries the oldest-inserted IP is dropped (best-effort limiter — real
# deployments should also limit at the reverse proxy).
_AUTH_RATE_LOG_MAX_IPS = 10_000


def _enforce_auth_rate_limit(client_ip: str) -> bool:
    """Return True if the IP is allowed to make another auth request."""
    now = datetime.now(timezone.utc).timestamp()
    settings = get_settings()
    limit = max(1, int(settings.AUTH_RATE_LIMIT_PER_MINUTE))
    if len(_auth_rate_log) >= _AUTH_RATE_LOG_MAX_IPS:
        expired = [
            ip for ip, entries in _auth_rate_log.items()
            if not entries or now - entries[-1] >= _AUTH_RATE_WINDOW_SEC
        ]
        for ip in expired:
            del _auth_rate_log[ip]
        while len(_auth_rate_log) >= _AUTH_RATE_LOG_MAX_IPS:
            _auth_rate_log.pop(next(iter(_auth_rate_log)))
    history = _auth_rate_log.setdefault(client_ip, [])
    history[:] = [t for t in history if now - t < _AUTH_RATE_WINDOW_SEC]
    if len(history) >= limit:
        return False
    history.append(now)
    return True


def _bootstrap_pool(strategy: ProviderStrategy) -> ProviderPool:
    """Create a ProviderPool and register every model from the strategy."""
    pool = ProviderPool()
    model_roles: dict[str, set[str]] = {}
    for role in strategy.supported_roles:
        for model in strategy.get_model_chain(role):
            model_roles.setdefault(model, set()).add(role)
    for model, roles in model_roles.items():
        pool.register_provider(extract_provider_key(model), roles=sorted(roles))
    return pool


def _resolve_cors_origins() -> list[str]:
    """CRIT-004: derive explicit allowlist from CORS_ORIGINS env var."""
    raw = get_settings().CORS_ORIGINS
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if any(o == "*" for o in origins):
        raise RuntimeError(
            "CRIT-004: CORS_ORIGINS cannot contain '*'.  Provide an explicit "
            "allowlist of fully-qualified origins."
        )
    if not origins:
        raise RuntimeError(
            "CRIT-004: CORS_ORIGINS must contain at least one explicit origin."
        )
    return origins


# ── Application Lifespan ────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _gateway, _strategy, _pool, _streaming_mgr, _calienne

    settings = get_settings()
    configure_logging(settings)

    logger.info("Verifying PostgreSQL schema revision...")
    try:
        await verify_schema_current()
    except Exception as exc:
        logger.error("PostgreSQL schema verification failed at startup: %s", exc)
        raise RuntimeError(
            "PostgreSQL is unreachable or not at the required Alembic revision. "
            "Verify DATABASE_URL and run 'alembic upgrade head'."
        ) from exc

    global _background_tasks

    _strategy = ProviderStrategy(mode="HYBRID")
    _pool = _bootstrap_pool(_strategy)
    get_provider_registry().bootstrap(_strategy, _pool)
    _gateway = AsyncAPIGateway()
    _calienne = initialize_calienne_components(streaming_manager=_streaming_mgr)

    # Publish singletons to the api/ route modules (late-bound, no cycles).
    from api.state import state as _api_state

    _api_state.calienne = _calienne
    _api_state.gateway = _gateway
    _api_state.strategy = _strategy
    _api_state.pool = _pool
    _api_state.streaming_manager = _streaming_mgr

    # Create background tasks for cleanup operations
    _background_tasks = create_background_tasks(_calienne)

    logger.info(
        "Calienne Web Server ready — mode=%s, providers=%d, background_tasks=%d",
        _strategy.mode.value,
        len(_pool.get_all_statuses()) if _pool else 0,
        len(_background_tasks),
    )
    yield

    # Cancel all background tasks gracefully
    if _background_tasks:
        logger.info("Cancelling %d background tasks...", len(_background_tasks))
        await cancel_background_tasks(_background_tasks)
        logger.info("All background tasks cancelled gracefully.")

    if _gateway:
        await _gateway.close()
    observer.print_session_report()
    logger.info("Calienne Web Server shut down.")


app = FastAPI(title="Calienne", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def request_body_size_limit(request: Request, call_next):
    """Reject oversized request bodies before validation or provider work."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_REQUEST_BODY_BYTES:
                return JSONResponse({"detail": "Request body too large"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_REQUEST_BODY_BYTES:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
    request._body = bytes(body)
    return await call_next(request)


@app.middleware("http")
async def csrf_origin_check(request: Request, call_next):
    """MED-019 lightweight CSRF origin check for state-changing requests.

    Browsers carry the Origin header on cross-site requests; we verify that
    incoming Origin / Referer hosts match the CORS allowlist before any
    POST / PUT / DELETE handler runs.  Health probes and GETs are skipped.
    """
    if request.method.upper() not in {"POST", "PUT", "DELETE", "PATCH"}:
        return await call_next(request)

    settings = get_settings()
    cookie_authenticated = (
        settings.AUTH_COOKIE_NAME in request.cookies
        and "authorization" not in request.headers
    )
    try:
        allowlist = _resolve_cors_origins()
    except RuntimeError:
        if cookie_authenticated:
            return JSONResponse(
                {"status": "error", "error": "CSRF origin policy unavailable"},
                status_code=503,
            )
        return await call_next(request)

    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if not origin:
        if cookie_authenticated:
            return JSONResponse(
                {"status": "error", "error": "CSRF origin required"},
                status_code=403,
            )
        return await call_next(request)

    from urllib.parse import urlparse
    parsed = urlparse(origin)
    candidate = f"{parsed.scheme}://{parsed.netloc}"
    if candidate not in allowlist:
        return JSONResponse(
            {"status": "error", "error": "CSRF check failed (origin not in allowlist)"},
            status_code=403,
        )
    return await call_next(request)


# CRIT-004 audit fix: CORS middleware uses an explicit allowlist (no wildcards).
app.add_middleware(
    CORSMiddleware,
    allow_origins=_resolve_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).parent / "frontend" / "dist"


# ── Request / Response Models ───────────────────────────────────────────

# Route handlers live in api/ (one module per domain); server.py assembles
# the app, owns shared runtime singletons, and re-exports the request models
# and handlers that tests import from here.
from api.routes_auth import router as _auth_router
from api.routes_conversations import router as _conversations_router
from api.routes_sessions import router as _sessions_router
from api.schemas import _StrictRequestModel

app.include_router(_auth_router)
app.include_router(_conversations_router)
app.include_router(_sessions_router)


class Message(_StrictRequestModel):
    role: Literal["user", "assistant"]
    content: str = PField(min_length=1, max_length=10_000)


class QueryRequest(_StrictRequestModel):
    query: str = PField(min_length=1, max_length=10_000)
    history: list[Message] | None = PField(default=None, max_length=50)

    @model_validator(mode="after")
    def _bound_history(self) -> "QueryRequest":
        if self.history and sum(len(message.content) for message in self.history) > 50_000:
            raise ValueError("history content must not exceed 50000 characters")
        return self


# ── Auth Request Schemas ──────────────────────────────────────────────────



class ProviderHealthResponse(BaseModel):
    provider_name: str
    health_status: str
    error_rate: float
    mean_latency_ms: float
    success_rate: float
    circuit_breaker_state: str
    last_success_timestamp: float | None = None
    last_failure_timestamp: float | None = None


class ProviderRecoveryRequest(_StrictRequestModel):
    pass


class ProviderRecoveryResponse(BaseModel):
    provider_name: str
    status: str
    health_status: str | None = None
    retry_after_sec: float | None = None


# ── Auth and Page Serving Routes ─────────────────────────────────────────


@app.post("/api/query")
async def handle_query(
    req: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run the micro-mode pipeline for a user query."""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    try:
        history_list = [msg.model_dump() for msg in req.history] if req.history else None
        if history_list is None:
            # Memory v1 (ReFind): no client history — hydrate the owner's
            # recent + topically relevant past turns. Scoped to
            # current_user.email inside the SQL; never another user's turns.
            # Memory is an enhancement, never a hard dependency: on any
            # storage failure the query proceeds without it (ADR-007).
            try:
                history_list = await hydrate_history(
                    db, owner_email=current_user.email, query=req.query.strip()
                )
            except Exception as exc:
                logger.warning("Memory hydration unavailable: %s", exc)
                history_list = None
        session_id = str(uuid.uuid4())
        passport = create_request_passport(user_id=current_user.email)
        result = await asyncio.wait_for(
            _calienne["execution_manager"].execute(
                user_query=req.query.strip(),
                gateway=_gateway,
                strategy=_strategy,
                pool=_pool,
                history=history_list,
                passport=passport,
                decision_engine=_calienne.get("decision_engine"),
                reasoning_graph=_calienne.get("reasoning_graph"),
                claim_manager=_calienne.get("claim_manager"),
                streaming_manager=_calienne.get("streaming_manager"),
                conversation_director=_calienne.get("conversation_director"),
                session_id=session_id,
                user_id=current_user.email,
            ),
            timeout=_PIPELINE_TIMEOUT_SEC,
        )

        return JSONResponse(_build_frontend_payload(result))

    except SecurityValidationError as exc:
        return JSONResponse(exc.to_error_response(), status_code=400)
    except asyncio.TimeoutError:
        return JSONResponse(
            {
                "status": "error",
                "answer": f"Pipeline timed out after {_PIPELINE_TIMEOUT_SEC}s.",
                "confidence_score": 0.0,
                "bias_risk": "Unknown",
                "decision": None,
                "agent_outputs": {
                    "logician": None,
                    "creative": None,
                }
            },
            status_code=504,
        )
    except Exception as exc:
        logger.exception("Pipeline error: %s", exc)
        return JSONResponse(
            {
                "status": "error",
                "answer": "Pipeline execution failed.",
                "confidence_score": 0.0,
                "bias_risk": "Unknown",
                "decision": None,
                "agent_outputs": {
                    "logician": None,
                    "creative": None,
                }
            },
            status_code=500,
        )


@app.post("/api/query/stream")
async def handle_query_stream(
    req: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream the micro-mode pipeline as Server-Sent Events.

    Each event is a JSON-encoded SSE data line.  The frontend reads the
    response via ``fetch()`` + ``ReadableStream`` and updates the UI in
    real time as each pipeline stage completes.
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    session_id = str(uuid.uuid4())
    passport = create_request_passport(session_id=session_id, user_id=current_user.email)
    request_id = passport.request_id
    history_list = [msg.model_dump() for msg in req.history] if req.history else None
    if history_list is None:
        # Memory v1: same hydration as /api/query, same owner scoping,
        # same fail-open posture.
        try:
            history_list = await hydrate_history(
                db, owner_email=current_user.email, query=req.query.strip()
            )
        except Exception as exc:
            logger.warning("Memory hydration unavailable: %s", exc)
            history_list = None

    try:
        _streaming_mgr.create_stream(request_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    async def _forward_pipeline_events():
        """Run the pipeline and forward its result into the StreamingManager.

        Routes through ``run_micro_mode``/``DecisionEngine`` — the same path
        as ``/api/query`` — so streaming and non-streaming requests share one
        execution path and telemetry contract (RFC-007 Step 1). Per-agent
        progress events are emitted internally by ``_run_with_decision_engine``
        via ``streaming_manager.emit(passport.request_id, ...)`` into this same
        ``_streaming_mgr``; this coroutine only needs to emit the terminal
        result/error event.
        """
        try:
            result = await asyncio.wait_for(
                _calienne["execution_manager"].execute(
                    user_query=req.query.strip(),
                    gateway=_gateway,
                    strategy=_strategy,
                    pool=_pool,
                    history=history_list,
                    passport=passport,
                    decision_engine=_calienne.get("decision_engine"),
                    reasoning_graph=_calienne.get("reasoning_graph"),
                    claim_manager=_calienne.get("claim_manager"),
                    streaming_manager=_streaming_mgr,
                    conversation_director=_calienne.get("conversation_director"),
                    session_id=session_id,
                    user_id=current_user.email,
                ),
                timeout=_PIPELINE_TIMEOUT_SEC,
            )
            await _streaming_mgr.emit(
                request_id,
                EventType.RESULT,
                {"payload": _build_frontend_payload(result)},
            )
        except asyncio.TimeoutError:
            await _streaming_mgr.emit(
                request_id,
                EventType.ERROR,
                {
                    "stage": "timeout",
                    "message": f"Pipeline timed out after {_PIPELINE_TIMEOUT_SEC}s.",
                },
            )
        except asyncio.CancelledError:
            logger.info("Pipeline forwarder cancelled for request_id=%s.", request_id)
            raise
        except Exception as exc:
            logger.exception("Pipeline forwarder error: %s", exc)
            await _streaming_mgr.emit(
                request_id,
                EventType.ERROR,
                {"stage": "unknown", "message": "Pipeline execution failed."},
            )
        finally:
            # Put sentinel to signal end of stream. Mirror emit()'s
            # drop-oldest policy if the buffer is full: a lost intermediate
            # event degrades one update, a lost terminator hangs the client
            # until its timeout.
            queue = _streaming_mgr._active_streams.get(request_id)
            if queue is not None:
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    logger.warning(
                        "SSE buffer full for request_id=%s — evicting oldest "
                        "event to guarantee stream termination.",
                        request_id,
                    )
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:  # pragma: no cover — raced consumer
                        pass
                    try:
                        queue.put_nowait(None)
                    except asyncio.QueueFull:  # pragma: no cover — consumer gone
                        logger.error(
                            "SSE sentinel undeliverable for request_id=%s; "
                            "closing stream.",
                            request_id,
                        )

    async def event_generator():
        # Start pipeline execution as background task
        forward_task = asyncio.create_task(_forward_pipeline_events())

        try:
            async for sse_event in _streaming_mgr.iter_events(request_id):
                yield f"data: {json.dumps(sse_event)}\n\n"
        except asyncio.CancelledError:
            logger.info("SSE stream cancelled by client for request_id=%s.", request_id)
            raise
        except Exception as exc:
            logger.exception("SSE stream error: %s", exc)
            error_event = {
                "event": "error",
                "data": {"stage": "unknown", "message": "Streaming failed."},
                "timestamp": datetime.utcnow().isoformat(),
            }
            yield f"data: {json.dumps(error_event)}\n\n"
        finally:
            forward_task.cancel()
            try:
                await forward_task
            except asyncio.CancelledError:
                pass
            _streaming_mgr.close_stream(request_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _clean_model_name(model_str: str) -> str:
    """Format a model identifier into an accurate, canonical display name."""
    # 1. Custom model explicit label from registry
    reg = get_provider_registry()
    parts = model_str.split("/")
    pid = parts[0]
    prov = reg.get_provider(pid)
    if prov:
        for m in prov.models:
            if m.full_id == model_str and m.name:
                return m.name

    base = parts[-1]
    name_map = {
        # Anthropic
        "claude-3.5-sonnet": "Claude 3.5 Sonnet",
        "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet",
        "claude-3-5-haiku-20241022": "Claude 3.5 Haiku",
        "claude-3-opus-20240229": "Claude 3 Opus",
        "claude-sonnet-5": "Claude Sonnet 5",
        "claude-opus-5": "Claude Opus 5",
        # OpenAI
        "gpt-4o": "GPT-4o",
        "gpt-4o-mini": "GPT-4o Mini",
        "gpt-4-turbo": "GPT-4 Turbo",
        "o1-preview": "o1 Preview",
        "o1-mini": "o1 Mini",
        "o3-mini": "o3 Mini",
        "gpt-oss-120b": "GPT-OSS 120B",
        "gpt-oss-20b": "GPT-OSS 20B",
        # Google
        "gemini-2.0-flash": "Gemini 2.0 Flash",
        "gemini-2.0-pro-exp": "Gemini 2.0 Pro",
        "gemini-1.5-pro": "Gemini 1.5 Pro",
        "gemini-1.5-flash": "Gemini 1.5 Flash",
        "gemini-3.7-flash": "Gemini 3.7 Flash",
        "gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite",
        "gemini-pro-latest": "Gemini Pro",
        # DeepSeek
        "deepseek-chat": "DeepSeek V3",
        "deepseek-reasoner": "DeepSeek R1",
        "deepseek-r1": "DeepSeek R1",
        "deepseek-v3": "DeepSeek V3",
        # Meta Llama
        "llama-3.3-70b-versatile": "Llama 3.3 70B",
        "llama-3.3-70b": "Llama 3.3 70B",
        "llama-3.1-8b-instant": "Llama 3.1 8B",
        "llama-3.1-70b-instruct": "Llama 3.1 70B",
        "llama-3.1-405b-instruct": "Llama 3.1 405B",
        # Mistral / Qwen
        "mistral-large-latest": "Mistral Large",
        "codestral-latest": "Codestral",
        "qwen-2.5-72b-instruct": "Qwen 2.5 72B",
        "qwen-2.5-coder-32b-instruct": "Qwen 2.5 Coder 32B",
    }
    if base in name_map:
        return name_map[base]
    if model_str in name_map:
        return name_map[model_str]
    return base


def _is_model_configured(model_str: str) -> bool:
    """Check if model's provider is a custom provider or has an active API key."""
    provider_key = extract_provider_key(model_str)
    provider_root = provider_key.split("/")[0].lower()

    # 1. Custom Provider? (Always configured once registered)
    reg = get_provider_registry()
    if provider_root in reg.get_custom_providers():
        return True

    # 2. Built-in provider account check
    key_account_map = {
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "groq": "GROQ_API_KEY",
        "nvidia": "NVIDIA_NIM_API_KEY",
        "mistral": "MISTRAL_API_KEY",
    }
    account = key_account_map.get(provider_root)
    if account:
        val = (
            os.environ.get(f"CALIENNE_{account}", "")
            or os.environ.get(account, "")
        )
        if val and len(val.strip()) > 4:
            return True
        key = reg.get_api_key(provider_root)
        if key and len(key.strip()) > 4:
            return True
    return False


def _get_dynamic_models() -> list[dict[str, Any]]:
    """Return dynamic model list with health status, latency, roles, and
    primary flags from active strategy."""
    if not _strategy:
        return []

    judge_chain = _strategy.get_model_chain("judge")
    gen_chain = _strategy.get_model_chain("generation")
    breaker_chain = _strategy.get_model_chain("breaker")
    primary_judge = judge_chain[0] if judge_chain else None
    primary_gen = gen_chain[0] if gen_chain else None
    primary_breaker = breaker_chain[0] if breaker_chain else None

    custom_pids = set(get_provider_registry().get_custom_providers().keys())

    models_dict: dict[str, dict[str, Any]] = {}
    for role in _strategy.supported_roles:
        for model_str in _strategy.get_configured_model_chain(role):
            if model_str not in models_dict:
                provider_key = extract_provider_key(model_str)
                provider_root = provider_key.split("/")[0]
                latency_str = "—"
                is_active = _strategy.is_model_enabled(model_str)
                if _pool:
                    metrics = _pool.get_health_metrics(provider_key)
                    if metrics and metrics.mean_latency_ms > 0:
                        latency_str = f"{(metrics.mean_latency_ms / 1000.0):.1f}s"
                    state = _pool._providers.get(provider_key)
                    if state:
                        is_active = (
                            is_active
                            and state.is_available
                            and state.status.value != "dead"
                        )

                clean_name = _clean_model_name(model_str)
                is_custom = provider_root in custom_pids
                is_conf = _is_model_configured(model_str)
                models_dict[model_str] = {
                    "id": clean_name.replace(".", "").replace("-", ""),
                    "name": clean_name,
                    "full_id": model_str,
                    "provider": provider_key,
                    "latency": latency_str,
                    "active": is_active,
                    "roles": [role],
                    "is_primary_judge": (model_str == primary_judge),
                    "is_primary_generation": (model_str == primary_gen),
                    "is_primary_breaker": (model_str == primary_breaker),
                    "custom": is_custom,
                    "configured": is_conf,
                    "has_key": is_conf,
                }
            else:
                if role not in models_dict[model_str]["roles"]:
                    models_dict[model_str]["roles"].append(role)

    # Prioritize custom models and configured models first
    return sorted(
        models_dict.values(),
        key=lambda m: (not m.get("custom", False), not m.get("configured", False), m["name"]),
    )


@app.get("/api/status")
async def get_status(current_user: User = Depends(get_current_user)) -> dict:
    """Return provider health, dynamic models, and session telemetry."""
    return {
        "user": {"email": current_user.email, "role": current_user.role},
        "providers": _pool.get_all_statuses() if _pool else [],
        "models": _get_dynamic_models(),
        "telemetry": observer.get_telemetry_dict(),
        "mode": _strategy.mode.value if _strategy else "UNKNOWN",
    }


@app.get("/api/models")
async def get_models(current_user: User = Depends(get_current_user)) -> dict:
    """Return active models configured in the orchestrator strategy."""
    return {"models": _get_dynamic_models()}


class ModelAddRequest(_StrictRequestModel):
    model: str
    role: str = "generation"


class ModelToggleRequest(_StrictRequestModel):
    id: str
    active: bool


class StrategyModeRequest(_StrictRequestModel):
    mode: str


@app.post("/api/models/add")
async def add_model_endpoint(
    req: ModelAddRequest,
    current_user: User = Depends(require_role("admin")),
) -> dict:
    """Dynamically register a new model in the active strategy and pool."""
    if not _strategy or not _pool:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized.")
    model_str = req.model.strip()
    if not model_str:
        raise HTTPException(status_code=400, detail="Model identifier cannot be empty.")
    _strategy.add_model(model_str, req.role)
    provider_key = extract_provider_key(model_str)
    _pool.register_provider(provider_key, roles=[req.role])
    return {"status": "success", "models": _get_dynamic_models()}


@app.post("/api/models/toggle")
async def toggle_model_endpoint(
    req: ModelToggleRequest,
    current_user: User = Depends(require_role("admin")),
) -> dict:
    """Enable or disable a model provider in the active pool."""
    if not _pool:
        raise HTTPException(status_code=503, detail="ProviderPool not initialized.")
    model = next((item for item in _get_dynamic_models() if item["full_id"] == req.id), None)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    if not _strategy or not _strategy.set_model_enabled(req.id, req.active):
        raise HTTPException(status_code=404, detail="Model not found.")
    return {"status": "success", "models": _get_dynamic_models()}


@app.post("/api/strategy/mode")
async def set_strategy_mode_endpoint(
    req: StrategyModeRequest,
    current_user: User = Depends(require_role("admin")),
) -> dict:
    """Switch the orchestrator strategy mode (FREE, HYBRID, PAID)."""
    if not _strategy or not _pool:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized.")
    try:
        _strategy.set_mode(req.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "success", "mode": _strategy.mode.value}




def _get_vault_status() -> list[dict[str, Any]]:
    """Return secure masked status of API keys for each provider."""
    providers_meta = [
        {"account": "OPENROUTER_API_KEY", "name": "OpenRouter", "description": "Unified gateway for Anthropic, Llama, DeepSeek & Qwen models"},  # noqa: E501
        {"account": "OPENAI_API_KEY", "name": "OpenAI", "description": "GPT-4o, GPT-4o-mini, and Reasoning models"},  # noqa: E501
        {"account": "GOOGLE_API_KEY", "name": "Google AI Studio", "description": "Gemini 2.5 Flash, Gemini 2.5 Pro"},  # noqa: E501
        {"account": "GROQ_API_KEY", "name": "Groq Cloud", "description": "Ultra-fast Llama 3.3 70B & Llama 3.1 8B inference"},  # noqa: E501
        {"account": "NVIDIA_NIM_API_KEY", "name": "NVIDIA NIM", "description": "Enterprise Nemotron & Llama 405B inference"},  # noqa: E501
        {"account": "MISTRAL_API_KEY", "name": "Mistral AI", "description": "Mistral Large & Codestral models"},  # noqa: E501
        {"account": "CUSTOM_GATEWAY_KEY", "name": "Custom API Gateway", "description": "Custom endpoint or Local LLM (Ollama / vLLM / LiteLLM)"},  # noqa: E501
    ]
    results = []
    for p in providers_meta:
        val = (
            os.environ.get(f"CALIENNE_{p['account']}", "")
            or os.environ.get(f"CALIENNE_{p['account']}", "")
            or os.environ.get(p["account"], "")
        )
        has_key = bool(val and len(val.strip()) > 4)
        masked = f"••••••••••••{val.strip()[-4:]}" if has_key else "Not Configured"
        results.append({
            "account": p["account"],
            "name": p["name"],
            "description": p["description"],
            "configured": has_key,
            "masked": masked,
        })
    return results


class VaultSaveRequest(_StrictRequestModel):
    account: str
    secret: str


class CustomModelRequest(_StrictRequestModel):
    model_id: str
    role: str = "generation"


class ProviderDiscoverRequest(_StrictRequestModel):
    base_url: str
    api_key: Optional[str] = None


class ProviderImportModelItem(_StrictRequestModel):
    id: str
    name: Optional[str] = None
    roles: list[str] = PField(default_factory=lambda: ["generation"])
    enabled: bool = True
    context_length: Optional[int] = None
    description: Optional[str] = None


class ProviderSaveRequest(_StrictRequestModel):
    id: Optional[str] = None
    name: str
    base_url: str
    api_key: Optional[str] = None
    models: list[ProviderImportModelItem] = PField(default_factory=list)


class ModelRolesUpdateRequest(_StrictRequestModel):
    model_id: str
    roles: list[str]


class ModelPrimaryUpdateRequest(_StrictRequestModel):
    role: str
    model_id: str


class ModelDeleteRequest(_StrictRequestModel):
    id: str


VaultSaveRequest.model_rebuild()
CustomModelRequest.model_rebuild()
ProviderDiscoverRequest.model_rebuild()
ProviderImportModelItem.model_rebuild()
ProviderSaveRequest.model_rebuild()
ModelRolesUpdateRequest.model_rebuild()
ModelPrimaryUpdateRequest.model_rebuild()
ModelDeleteRequest.model_rebuild()


@app.get("/api/config/vault")
async def get_vault_status(current_user: User = Depends(require_role("admin"))) -> dict:
    """Return secure masked status of provider API keys in vault.

    Admin-only like the write path: even masked key status (configured flag,
    last 4 chars) describes the server's secrets, not the caller's own data.
    """
    return {"providers": _get_vault_status()}


@app.post("/api/config/vault")
async def save_vault_secret(
    req: VaultSaveRequest,
    current_user: User = Depends(require_role("admin")),
) -> dict:
    """Save an API key securely into OS Keyring and running memory enclave."""
    account = req.account.strip()
    secret = req.secret.strip()
    allowed_accounts = {
        "OPENROUTER_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
        "GROQ_API_KEY", "NVIDIA_NIM_API_KEY", "MISTRAL_API_KEY",
        "CUSTOM_GATEWAY_KEY", "GITHUB_TOKEN",
    }
    is_custom_provider_key = account.startswith("PROVIDER_KEY_")
    if account not in allowed_accounts and not is_custom_provider_key:
        raise HTTPException(status_code=400, detail="Invalid account identifier.")
    if secret:
        os.environ[f"CALIENNE_{account}"] = secret
        os.environ[f"CALIENNE_{account}"] = secret
        os.environ[account] = secret
        storage = "memory"
        try:
            import keyring
            keyring.set_password("Calienne", account, secret)
            keyring.set_password("Calienne", account, secret)
            storage = "keyring"
        except Exception as exc:
            logger.debug("OS Keyring unavailable or non-writable: %s", exc)
    return {
        "status": "success",
        "storage": storage if secret else "unchanged",
        "providers": _get_vault_status(),
    }


@app.post("/api/providers/discover")
async def discover_provider_models(
    req: ProviderDiscoverRequest,
    current_user: User = Depends(require_role("admin")),
) -> dict:
    """Probe model provider endpoint to automatically fetch available models."""
    if not req.base_url.strip():
        raise HTTPException(status_code=400, detail="Provider base URL is required.")
    try:
        models = await get_provider_registry().discover_models(req.base_url, req.api_key)
        return {"status": "success", "models": models}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Provider discovery failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=400, detail="Model discovery failed. Check server logs.") from exc


@app.get("/api/providers")
async def list_providers_endpoint(
    current_user: User = Depends(require_role("admin")),
) -> dict:
    """List all custom providers with secure masked status and model counts."""
    return {
        "providers": get_provider_registry().list_providers_view(),
        "preferences": get_provider_registry().get_role_preferences(),
    }


@app.post("/api/providers")
async def save_provider_endpoint(
    req: ProviderSaveRequest,
    current_user: User = Depends(require_role("admin")),
) -> dict:
    """Register or update a custom provider, saving key securely in OS Keyring."""
    if not _strategy or not _pool:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized.")
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Provider name cannot be empty.")
    if not req.base_url.strip():
        raise HTTPException(status_code=400, detail="Provider base URL cannot be empty.")

    try:
        models_data = [m.model_dump() for m in req.models]
        spec = get_provider_registry().register_or_update_provider(
            name=req.name,
            base_url=req.base_url,
            api_key=req.api_key,
            models=models_data,
            provider_id=req.id,
            strategy=_strategy,
            pool=_pool,
        )
        return {
            "status": "success",
            "provider": spec.model_dump(),
            "models": _get_dynamic_models(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Provider save failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=400, detail="Failed to save provider. Check server logs.") from exc


@app.delete("/api/providers/{provider_id}")
async def delete_provider_endpoint(
    provider_id: str,
    current_user: User = Depends(require_role("admin")),
) -> dict:
    """Delete a custom provider and purge its secrets from OS Keyring."""
    if not _strategy or not _pool:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized.")
    success = get_provider_registry().delete_provider(provider_id, _strategy, _pool)
    if not success:
        raise HTTPException(status_code=404, detail="Provider not found.")
    return {"status": "success", "models": _get_dynamic_models()}


@app.post("/api/models/roles")
async def update_model_roles_endpoint(
    req: ModelRolesUpdateRequest,
    current_user: User = Depends(require_role("admin")),
) -> dict:
    """Update role assignments (e.g. Judge, Generation, Breaker) for any model."""
    if not _strategy or not _pool:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized.")
    get_provider_registry().update_model_roles(req.model_id, req.roles, _strategy, _pool)
    return {"status": "success", "models": _get_dynamic_models()}


@app.post("/api/models/primary")
async def set_primary_model_endpoint(
    req: ModelPrimaryUpdateRequest,
    current_user: User = Depends(require_role("admin")),
) -> dict:
    """Designate a model as the Primary model for a role (e.g. Primary Judge)."""
    if not _strategy or not _pool:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized.")
    get_provider_registry().set_primary_role_model(req.role, req.model_id, _strategy)
    return {"status": "success", "models": _get_dynamic_models()}


class ModelChainUpdateRequest(_StrictRequestModel):
    role: str
    chain: list[str]


ModelChainUpdateRequest.model_rebuild()


@app.post("/api/models/chain")
async def update_model_chain_endpoint(
    req: ModelChainUpdateRequest,
    current_user: User = Depends(require_role("admin")),
) -> dict:
    """Update the priority order / fallback chain of models for a role."""
    if not _strategy or not _pool:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized.")
    _strategy.set_model_chain(req.role, req.chain)
    return {"status": "success", "models": _get_dynamic_models()}


@app.post("/api/models/delete")
async def delete_model_endpoint(
    req: ModelDeleteRequest,
    current_user: User = Depends(require_role("admin")),
) -> dict:
    """Remove a model from the active orchestrator strategy."""
    if not _strategy or not _pool:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized.")
    _strategy.remove_model(req.id)
    parts = req.id.split("/")
    pid = parts[0]
    prov = get_provider_registry().get_provider(pid)
    if prov:
        prov.models = [m for m in prov.models if m.full_id != req.id]
        get_provider_registry()._save_to_disk()
    return {"status": "success", "models": _get_dynamic_models()}


@app.post("/api/models/custom")
async def register_custom_model(
    req: CustomModelRequest,
    current_user: User = Depends(require_role("admin")),
) -> dict:
    """Register a custom model and optional gateway URL in orchestrator."""
    if not _strategy or not _pool:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized.")
    model_str = req.model_id.strip()
    if not model_str:
        raise HTTPException(status_code=400, detail="Model ID cannot be empty.")
    _strategy.add_model(model_str, req.role)
    provider_key = extract_provider_key(model_str)
    _pool.register_provider(provider_key, roles=[req.role])
    return {"status": "success", "models": _get_dynamic_models()}


@app.get("/api/telemetry")
async def get_telemetry(current_user: User = Depends(get_current_user)) -> dict:
    """Return session telemetry metrics."""
    return observer.get_telemetry_dict()


@app.get("/api/config")
async def get_config(current_user: User = Depends(get_current_user)) -> dict:
    """Return non-sensitive configuration."""
    settings = get_settings()
    return {
        "mode": _strategy.mode.value if _strategy else "UNKNOWN",
        "roles": _strategy.supported_roles if _strategy else [],
        "simulation_mode": not settings.OPENROUTER_API_KEY,
        "log_level": settings.LOG_LEVEL,
    }


# ── Session Management Endpoints ──────────────────────────────────────────


# ── Execution Replay Debug Endpoint (Step 20a) ────────────────────────────

@app.get("/api/debug/replay/{trace_id}")
async def get_replay_trace(
    trace_id: str,
    current_user: User = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Return a recorded execution trace for offline replay/debugging.

    Gated by ``CALIENNE_ENABLE_REPLAY`` — when the flag is off the
    ``replay_store`` component is ``None`` and this reports 503 rather
    than fabricating an empty trace (ADR-007).
    """
    replay_store = _calienne.get("replay_store")
    if not replay_store:
        raise HTTPException(status_code=503, detail="Execution replay is disabled")

    trace = replay_store.load(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Replay trace {trace_id} not found or expired")

    return trace.model_dump(mode="json")


@app.get("/metrics")
async def prometheus_metrics(request: Request) -> Response:
    """Prometheus text exposition of decision and provider-health metrics.

    Auth: a scraper cannot present the httpOnly JWT cookie the admin endpoints
    rely on, so this path uses its own bearer token (``CALIENNE_METRICS_TOKEN``).
    In production the token is mandatory — an unset token means the endpoint
    refuses to serve rather than silently exposing internals. Outside production
    an unset token leaves it open so local scraping needs no setup.
    """
    settings = get_settings()
    expected = settings.METRICS_TOKEN

    if not expected:
        if settings.ENVIRONMENT == "production":
            logger.error("CALIENNE_METRICS_TOKEN unset — refusing to serve /metrics.")
            raise HTTPException(
                status_code=503,
                detail="Metrics endpoint unconfigured: set CALIENNE_METRICS_TOKEN.",
            )
    else:
        header = request.headers.get("authorization", "")
        scheme, _, presented = header.partition(" ")
        # Compare as bytes: compare_digest on str raises TypeError for
        # non-ASCII input, turning a malformed header into a 500.
        if scheme.lower() != "bearer" or not secrets.compare_digest(
            presented.encode("utf-8"), expected.encode("utf-8")
        ):
            raise HTTPException(status_code=401, detail="Invalid metrics token.")

    metrics.refresh(
        decision_engine=_calienne.get("decision_engine"),
        pool=_pool,
    )
    return Response(content=metrics.render(), media_type=metrics.CONTENT_TYPE)


# ── Provider Health Monitoring Endpoints ──────────────────────────────────

@app.get("/api/providers/health", response_model=list[ProviderHealthResponse])
async def get_providers_health(
    current_user: User = Depends(require_role("admin")),
) -> list[ProviderHealthResponse]:
    """Return health metrics for all registered providers."""
    if not _pool:
        return []

    health_list = []
    for provider_name in _pool._priority_order:
        if provider_name not in _pool._providers:
            continue

        state = _pool._providers[provider_name]
        metrics = _pool.get_health_metrics(provider_name)
        health_status = _pool.calculate_health_status(provider_name)

        if metrics is None:
            metrics = HealthMetrics()

        health_list.append(
            ProviderHealthResponse(
                provider_name=provider_name,
                health_status=health_status,
                error_rate=metrics.error_rate,
                mean_latency_ms=metrics.mean_latency_ms,
                success_rate=metrics.success_rate,
                circuit_breaker_state=state.circuit_breaker_state.value,
                last_success_timestamp=state.last_success_timestamp,
                last_failure_timestamp=state.last_failure_timestamp,
            )
        )

    return health_list


@app.post("/api/providers/{provider_name}/recovery", response_model=ProviderRecoveryResponse)
async def trigger_provider_recovery(
    provider_name: str,
    req: ProviderRecoveryRequest,
    current_user: User = Depends(require_role("admin")),
) -> ProviderRecoveryResponse:
    """Manually trigger recovery for a DEAD provider (admin only — MED-023)."""
    if not _pool:
        raise HTTPException(status_code=503, detail="Provider pool not available")

    if provider_name not in _pool._providers:
        raise HTTPException(status_code=404, detail=f"Provider {provider_name} not found")

    state = _pool._providers[provider_name]
    if state.status is not ProviderStatus.DEAD:
        return ProviderRecoveryResponse(
            provider_name=provider_name,
            status="already_healthy",
            health_status=state.status.value,
        )

    recovery_success = _pool.attempt_recovery(provider_name)

    if recovery_success:
        updated_state = _pool._providers[provider_name]
        return ProviderRecoveryResponse(
            provider_name=provider_name,
            status="recovered",
            health_status=updated_state.status.value,
        )
    else:
        # Calculate retry-after based on backoff delay
        retry_after = state.backoff_delay if state.backoff_delay > 0 else 60.0
        return ProviderRecoveryResponse(
            provider_name=provider_name,
            status="recovery_failed",
            health_status=state.status.value,
            retry_after_sec=retry_after,
        )


# ── Static File Serving ─────────────────────────────────────────────────

@app.get("/")
async def serve_index():
    """Serve the main HTML page."""
    index = WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend not found.")
    return FileResponse(index, media_type="text/html")


if (WEB_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")

@app.api_route("/{full_path:path}", methods=["GET"])
async def catch_all(full_path: str):
    """Catch-all route for SPA client-side routing."""
    # Skip API routes and auth routes
    if full_path.startswith("api/") or full_path.startswith("auth/") or full_path == "login":
        raise HTTPException(status_code=404, detail="Not found")

    # Check if the requested file exists in WEB_DIR (e.g., favicon.svg)
    import mimetypes
    web_dir_resolved = WEB_DIR.resolve()
    requested_file = (WEB_DIR / full_path).resolve()
    if requested_file.is_relative_to(web_dir_resolved) and requested_file.is_file():
        media_type, _ = mimetypes.guess_type(str(requested_file))
        return FileResponse(requested_file, media_type=media_type)

    # If it's a request for a static asset that doesn't exist, return 404
    if "." in full_path.split("/")[-1]:
        raise HTTPException(status_code=404, detail="Asset not found")

    index = WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend not found.")
    return FileResponse(index, media_type="text/html")


# ── Re-exports (tests import these from `server`) ────────────────────────
from api.routes_auth import (  # noqa: E402,F401
    AuthLoginRequest,
    AuthRegisterRequest,
    _set_auth_cookie,
    login_user,
    logout_user,
    refresh_token,
    register_user,
)
from api.routes_conversations import (  # noqa: E402,F401
    ConversationSaveRequest,
    delete_conversation,
    get_conversations,
    purge_conversations,
    save_conversation,
)
from api.routes_sessions import (  # noqa: E402,F401
    CheckpointDeleteResponse,
    CheckpointListResponse,
    CheckpointRestoreRequest,
    CheckpointRestoreResponse,
    SessionCloseResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionHistoryResponse,
    SessionMetadataResponse,
    close_session,
    create_session,
    delete_checkpoints,
    get_session_history,
    get_session_metadata,
    list_checkpoints,
    restore_checkpoint,
)
