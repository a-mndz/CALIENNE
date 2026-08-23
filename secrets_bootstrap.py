"""
Calienne — Secret bootstrap.

Loads provider API keys from the OS-native secret store (Windows
Credential Manager, macOS Keychain, Linux Secret Service) and exports
them as ``CALIENNE_*`` and ``CALIENNE_*`` environment variables *before*
configuration is constructed.  This keeps live keys out of ``.env`` and
out of any file that could be committed to version control.
"""

from __future__ import annotations

import logging
import os
from typing import Iterable, Mapping

logger = logging.getLogger("calienne.secrets")

# Service name used in the OS secret store.  Override with
# ``CALIENNE_KEYRING_SERVICE`` or legacy ``CALIENNE_KEYRING_SERVICE``.
_KEYRING_SERVICE: str = os.environ.get(
    "CALIENNE_KEYRING_SERVICE",
    os.environ.get("CALIENNE_KEYRING_SERVICE", "Calienne")
)

# Account names map 1:1 to config field names (no prefix).
_ACCOUNTS: tuple[str, ...] = (
    "OPENROUTER_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "GROQ_API_KEY",
    "GITHUB_TOKEN",
    "MISTRAL_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "KIE_API_KEY",
    "UNLI_DEV_API_KEY",
)


def _read_keyring(service: str, account: str) -> str | None:
    """Read a single secret from the OS keyring.  Returns None on any
    failure (backend missing, key absent, backend error)."""
    try:
        import keyring  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        secret = keyring.get_password(service, account)
        if not secret and service != "Calienne":
            # Fallback to legacy Calienne keyring store if not found in Calienne
            secret = keyring.get_password("Calienne", account)
    except Exception as exc:  # noqa: BLE001 — defensive: any keyring error is non-fatal
        logger.debug("keyring.get_password(%r, %r) failed: %s", service, account, exc)
        return None
    return secret if secret else None


def _populate_env(secrets: Mapping[str, str]) -> int:
    """Export each secret to ``CALIENNE_<NAME>`` and ``CALIENNE_<NAME>`` unless
    already set."""
    set_count = 0
    for account, secret in secrets.items():
        if not secret:
            continue
        for prefix in ("CALIENNE_", "CALIENNE_"):
            env_name = f"{prefix}{account}"
            if env_name not in os.environ or not os.environ[env_name]:
                os.environ[env_name] = secret
        set_count += 1
    return set_count


def load_secrets(accounts: Iterable[str] = _ACCOUNTS) -> int:
    """Read each named secret from the OS keyring and export it to the
    environment.  Returns the number of env vars that were newly set.

    Safe to call multiple times — the second call is a no-op because
    ``os.environ`` already carries the values from the first.
    """
    secrets: dict[str, str] = {}
    for account in accounts:
        secret = _read_keyring(_KEYRING_SERVICE, account)
        if secret:
            secrets[account] = secret

    if not secrets:
        logger.debug(
            "No provider keys found in OS keyring under service=%r. "
            "Continuing in Simulation Mode.",
            _KEYRING_SERVICE,
        )
        return 0

    set_count = _populate_env(secrets)
    logger.info(
        "Loaded %d provider key(s) from OS keyring (service=%r).",
        set_count,
        _KEYRING_SERVICE,
    )

    # Allow live keys opt-in
    if set_count > 0:
        if "CALIENNE_ALLOW_LIVE_KEYS" not in os.environ:
            os.environ["CALIENNE_ALLOW_LIVE_KEYS"] = "1"
        if "CALIENNE_ALLOW_LIVE_KEYS" not in os.environ:
            os.environ["CALIENNE_ALLOW_LIVE_KEYS"] = "1"

    return set_count


# Run on import so a single ``import secrets_bootstrap`` is enough to arm the environment.
load_secrets()

