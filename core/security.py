"""Authentication helpers and prompt-security validation for CALIENNE."""

from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.database import get_db
from core.models import User

logger = logging.getLogger(__name__)

settings = get_settings()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


@dataclass(frozen=True, slots=True)
class SecurityViolation:
    """A single input validation or prompt-injection finding."""

    violation_type: str
    severity: str
    description: str
    detected_pattern: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "violation_type": self.violation_type,
            "severity": self.severity,
            "description": self.description,
            "detected_pattern": self.detected_pattern,
        }


class SecurityValidationError(ValueError):
    """Raised when user-controlled input violates the security contract."""

    def __init__(self, violations: list[SecurityViolation]) -> None:
        self.violations = tuple(violations)
        injection_detected = any(
            violation.violation_type == "prompt_injection"
            for violation in violations
        )
        message = (
            "security policy violation"
            if injection_detected
            else "input validation failure"
        )
        super().__init__(message)

    def to_error_response(self) -> dict[str, Any]:
        """Return the stable error payload expected by API components."""
        return {
            "status": "error",
            "error": str(self),
            "violations": [violation.to_dict() for violation in self.violations],
        }


class SecurityValidator:
    """Validate user input and preserve the system/user prompt boundary."""

    MAX_INPUT_LENGTH = 10_000
    VALID_UNICODE_CATEGORIES = frozenset({"L", "N", "P", "S", "Z"})

    INJECTION_PATTERNS = (
        r"\bignore\s+(?:the\s+)?(?:previous|prior|all|above)\s+instructions?\b",
        r"\bdisregard\s+(?:the\s+)?(?:previous|prior|all|above)(?:\s+instructions?)?\b",
        r"\bnew\s+instructions?\s*:?",
        r"\byou\s+are\s+now\b",
        r"\bsystem\s*:",
        r"\bassistant\s*:",
        r"\bsystem\s+(?:override|prompt|instructions?)\b",
        r"\bforget\s+(?:everything|all|previous|prior)\b",
        r"<\s*/?\s*(?:system|prompt|instruction|assistant|user)\b[^>]*>",
        r"\{\s*[\"']?(?:system|prompt|instruction|role)[\"']?\s*:",
        r"[\"']role[\"']\s*:\s*[\"'](?:system|assistant)[\"']",
    )

    SECRET_PATTERNS = (
        re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b", re.IGNORECASE),
        re.compile(
            r"\b(?P<label>api[_-]?key|apikey)\b"
            r"(?P<separator>\s*[:=]\s*)"
            r"(?P<quote>[\"']?)(?P<value>[^\s,\"'}]+)(?P=quote)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?P<label>password|passwd|pwd)\b"
            r"(?P<separator>\s*[:=]\s*)"
            r"(?P<quote>[\"']?)(?P<value>[^\s,\"'}]+)(?P=quote)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?P<label>token|auth(?:[_-]?token)?|bearer)\b"
            r"(?P<separator>\s*(?::|=)?\s+|\s*[:=]\s*)"
            r"(?P<quote>[\"']?)(?P<value>[A-Za-z0-9._~+/-]+)(?P=quote)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?P<label>secret[_-]?key)\b"
            r"(?P<separator>\s*[:=]\s*)"
            r"(?P<quote>[\"']?)(?P<value>[^\s,\"'}]+)(?P=quote)",
            re.IGNORECASE,
        ),
    )

    def __init__(self) -> None:
        self._injection_attempt_count = 0
        self._validation_failure_count = 0
        self._blocked_requests = 0
        self._secrets_scrubbed = 0
        self._metrics_lock = threading.Lock()

    @property
    def injection_attempt_count(self) -> int:
        with self._metrics_lock:
            return self._injection_attempt_count

    @property
    def injection_attempts(self) -> int:
        """Compatibility alias used by the architecture design."""
        return self.injection_attempt_count

    @property
    def secrets_scrubbed(self) -> int:
        with self._metrics_lock:
            return self._secrets_scrubbed

    def validate_input(
        self,
        user_input: str,
    ) -> tuple[bool, list[SecurityViolation]]:
        """Validate length, printable Unicode categories, and injection patterns."""
        violations: list[SecurityViolation] = []

        if not isinstance(user_input, str):
            violations.append(
                SecurityViolation(
                    violation_type="invalid_type",
                    severity="high",
                    description="Input must be a string",
                )
            )
        else:
            if len(user_input) > self.MAX_INPUT_LENGTH:
                violations.append(
                    SecurityViolation(
                        violation_type="input_length",
                        severity="high",
                        description=(
                            "Input exceeds maximum length of "
                            f"{self.MAX_INPUT_LENGTH} characters"
                        ),
                    )
                )

            invalid_character = next(
                (
                    character
                    for character in user_input
                    if unicodedata.category(character)[0]
                    not in self.VALID_UNICODE_CATEGORIES
                ),
                None,
            )
            if invalid_character is not None:
                violations.append(
                    SecurityViolation(
                        violation_type="invalid_characters",
                        severity="high",
                        description=(
                            "Input contains control or non-printable "
                            "UTF-8 characters"
                        ),
                    )
                )

            violations.extend(self.detect_injection(user_input))

        is_valid = not violations
        if not is_valid:
            with self._metrics_lock:
                self._validation_failure_count += len(violations)
                self._blocked_requests += 1
            logger.warning(
                "Security validation failed. Blocked request. Violations: %s",
                [v.violation_type for v in violations],
                extra={"stage": "security_validation"}
            )
        return is_valid, violations

    def validate_or_raise(self, user_input: str) -> str:
        """Return input unchanged when valid, otherwise reject it."""
        is_valid, violations = self.validate_input(user_input)
        if not is_valid:
            raise SecurityValidationError(violations)
        return user_input

    def detect_injection(self, text: str) -> list[SecurityViolation]:
        """Return every prompt-injection pattern found in text."""
        if not isinstance(text, str):
            return []

        violations: list[SecurityViolation] = []
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                violations.append(
                    SecurityViolation(
                        violation_type="prompt_injection",
                        severity="high",
                        description="Detected prompt injection pattern",
                        detected_pattern=pattern,
                    )
                )

        if violations:
            with self._metrics_lock:
                self._injection_attempt_count += len(violations)
            logger.warning(
                "Prompt injection pattern detected! Count: %d",
                len(violations),
                extra={"stage": "security_validation", "injection_detected": True}
            )
        return violations

    def scrub_secrets(self, text: str) -> str:
        """Replace API keys, passwords, and authentication tokens in text."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        scrubbed = text
        scrub_count = 0

        def redact(match: re.Match[str]) -> str:
            nonlocal scrub_count
            scrub_count += 1
            group_names = match.re.groupindex
            if "label" in group_names:
                return (
                    f"{match.group('label')}"
                    f"{match.group('separator')}[REDACTED]"
                )
            return "[REDACTED]"

        for pattern in self.SECRET_PATTERNS:
            scrubbed = pattern.sub(redact, scrubbed)

        if scrub_count:
            with self._metrics_lock:
                self._secrets_scrubbed += scrub_count
            logger.info("Scrubbed %d secrets from input.", scrub_count, extra={"stage": "security_validation"})  # noqa: E501
        return scrubbed

    @staticmethod
    def escape_user_input(user_input: str) -> str:
        """Encode user text as a JSON string for safe structured embedding."""
        if not isinstance(user_input, str):
            raise TypeError("user_input must be a string")
        return json.dumps(user_input, ensure_ascii=False)

    def separate_system_user_prompts(
        self,
        system_prompt: str | None,
        user_input: str,
    ) -> list[dict[str, str]]:
        """Build distinct provider messages for trusted and untrusted content."""
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append(
            {"role": "user", "content": self.escape_user_input(user_input)}
        )
        return messages

    def get_security_metrics(self) -> dict[str, int]:
        with self._metrics_lock:
            return {
                "injection_attempt_count": self._injection_attempt_count,
                "injection_attempts": self._injection_attempt_count,
                "validation_failure_count": self._validation_failure_count,
                "blocked_requests": self._blocked_requests,
                "secrets_scrubbed": self._secrets_scrubbed,
            }


def hash_password(password: str) -> str:
    """
    Hash a plain text password using bcrypt.
    """
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain text password against a bcrypt hash.
    """
    pwd_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    try:
        return bcrypt.checkpw(pwd_bytes, hashed_bytes)
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """
    Generate a signed JWT access token.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


async def get_current_user(
    request: Request,
    bearer_token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """
    Dependency to validate the JWT token and return the current user.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = bearer_token or request.cookies.get(settings.AUTH_COOKIE_NAME)
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        email: str | None = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception from None

    # Query the user from the database
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if user is None:
        raise credentials_exception

    return user


def require_role(required_role: str):
    """FastAPI dependency factory enforcing role-based access (MED-023).

    Returns a dependency that resolves the current user and raises
    ``HTTPException(403)`` when the user's ``role`` column does not match the
    required value.  Use as ``Depends(require_role("admin"))``.
    """

    async def _role_check(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        user_role = getattr(current_user, "role", "user") or "user"
        if user_role != required_role and user_role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{required_role}' required (current role: '{user_role}').",
            )
        return current_user

    return _role_check
