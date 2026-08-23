"""Auth routes: login page, register/login/logout/refresh.

The per-IP rate limiter's mutable state lives in ``server.py`` (tests
monkeypatch it there), so these handlers reach it late-bound at call time.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import _StrictRequestModel
from core.config import get_settings
from core.database import get_db
from core.models import User
from core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter()


def _enforce_rate_limit(client_ip: str) -> bool:
    # Late-bound: server.py owns the limiter and its monkeypatchable state.
    import server as _server

    return _server._enforce_auth_rate_limit(client_ip)


class AuthLoginRequest(_StrictRequestModel):
    email: str
    password: str

    @field_validator("password")
    @classmethod
    def _validate_password_length(cls, value: str) -> str:
        # bcrypt raises on passwords longer than 72 bytes instead of
        # truncating, which would surface as an opaque 500 on auth.
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password must not exceed 72 bytes")
        return value

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        normalised = value.strip().lower()
        if "@" not in normalised or " " in normalised or len(normalised) > 254:
            raise ValueError("email must be a well-formed address")
        return normalised


class AuthRegisterRequest(AuthLoginRequest):
    @field_validator("password")
    @classmethod
    def _validate_password_strength(cls, value: str) -> str:
        # MED-021 audit fix: enforce minimum strength baseline so trivially
        # guessable passwords cannot be registered.
        if len(value) < 8:
            raise ValueError("password must be at least 8 characters long")
        if len(set(value)) < 3:
            raise ValueError("password must contain at least 3 unique characters")
        return value


@router.get("/login")
async def serve_login():
    """Serve the login HTML page."""
    login_path = Path(__file__).resolve().parent.parent / "aetheris_login.html"
    if not login_path.exists():
        raise HTTPException(status_code=404, detail="Login page not found.")
    return FileResponse(login_path, media_type="text/html")


@router.get("/aetheris_hero_video_graded.mp4")
async def serve_login_hero_video():
    """Serve the login HTML hero video."""
    video_path = Path(__file__).resolve().parent.parent / "aetheris_hero_video_graded.mp4"
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Hero video not found.")
    return FileResponse(video_path, media_type="video/mp4")


@router.post("/auth/register", status_code=201)
async def register_user(req: AuthRegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Register a new user, checking if the email already exists."""
    client_ip = request.client.host if request.client else "unknown"
    if not _enforce_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts; slow down.",
        )

    stmt = select(User).where(User.email == req.email)
    result = await db.execute(stmt)
    if result.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Hash the password and store the user
    hashed = hash_password(req.password)
    new_user = User(email=req.email, password_hash=hashed)
    db.add(new_user)
    await db.commit()
    return {"message": "User registered successfully"}


def _set_auth_cookie(response: JSONResponse, token: str) -> None:
    """HIGH-013: deliver the JWT via an httpOnly, SameSite=Strict cookie."""
    import server as _server  # late-bound: tests patch server.get_settings

    settings = _server.get_settings()
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.ENVIRONMENT != "development",
        samesite="strict",
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )


@router.post("/auth/login")
async def login_user(req: AuthLoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Authenticate credentials and emit an httpOnly JWT cookie."""
    client_ip = request.client.host if request.client else "unknown"
    if not _enforce_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts; slow down.",
        )

    stmt = select(User).where(User.email == req.email)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(data={"sub": user.email})
    response = JSONResponse({"status": "ok"})
    _set_auth_cookie(response, token)
    return response


@router.post("/auth/logout")
async def logout_user() -> JSONResponse:
    """Clear the httpOnly auth cookie (HIGH-013)."""
    settings = get_settings()
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(settings.AUTH_COOKIE_NAME, path="/")
    return response


@router.post("/auth/refresh")
async def refresh_token(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """Refresh the authenticated user's httpOnly JWT cookie."""
    token = create_access_token(data={"sub": current_user.email})
    response = JSONResponse({"status": "ok"})
    _set_auth_cookie(response, token)
    return response
