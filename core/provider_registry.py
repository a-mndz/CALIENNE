"""
Calienne — Dynamic Provider & Model Registry.

Manages dynamic AI providers (OpenAI-compatible endpoints, local Ollama, vLLM,
OpenRouter, DeepSeek, Together, Groq, Mistral, etc.), automated model discovery,
secure OS Keyring storage of API credentials, and runtime role assignment
(Generation, Circuit Breaker, Audit Judge).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from core.base import CalienneBaseModel

logger = logging.getLogger("calienne.providers")

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "custom_providers.json"
_KEYRING_SERVICE = os.environ.get(
    "CALIENNE_KEYRING_SERVICE",
    os.environ.get("CALIENNE_KEYRING_SERVICE", "Calienne")
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_slug(name: str) -> str:
    """Create a safe provider identifier slug."""
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", name.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "custom_provider"


def _read_keyring(service: str, account: str) -> Optional[str]:
    """Read secret from OS Keyring."""
    try:
        import keyring
        secret = keyring.get_password(service, account)
        if not secret and service != "Calienne":
            secret = keyring.get_password("Calienne", account)
        return secret if secret else None
    except Exception as exc:
        logger.debug("keyring.get_password(%r, %r) failed: %s", service, account, exc)
        return None


def _write_keyring(service: str, account: str, secret: str) -> bool:
    """Save secret to OS Keyring."""
    try:
        import keyring
        keyring.set_password(service, account, secret)
        if service != "Calienne":
            try:
                keyring.set_password("Calienne", account, secret)
            except Exception:
                pass
        return True
    except Exception as exc:
        logger.debug("keyring.set_password(%r, %r) failed: %s", service, account, exc)
        return False


def _delete_keyring(service: str, account: str) -> bool:
    """Delete secret from OS Keyring."""
    try:
        import keyring
        try:
            keyring.delete_password(service, account)
        except Exception:
            pass
        if service != "Calienne":
            try:
                keyring.delete_password("Calienne", account)
            except Exception:
                pass
        return True
    except Exception as exc:
        logger.debug("keyring.delete_password(%r, %r) failed: %s", service, account, exc)
        return False


class CustomModelSpec(CalienneBaseModel):
    id: str
    name: str
    full_id: str
    roles: list[str] = ["generation"]
    enabled: bool = True
    context_length: Optional[int] = None
    description: Optional[str] = None


class CustomProviderSpec(CalienneBaseModel):
    id: str
    name: str
    base_url: str
    has_api_key: bool = False
    models: list[CustomModelSpec] = []
    created_at: str = ""
    updated_at: str = ""


class ProviderRegistry:
    """
    Central registry for dynamic AI model providers, automated model discovery,
    OS Keyring secret management, and role assignments.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self.config_path = config_path or _CONFIG_PATH
        self._providers: dict[str, CustomProviderSpec] = {}
        self._in_memory_keys: dict[str, str] = {}
        self._role_preferences: dict[str, str] = {}
        self._load_from_disk()

    # ── Persistence & Secrets ────────────────────────────────────────────────

    def _load_from_disk(self) -> None:
        """Load provider metadata from config/custom_providers.json and read keys from keyring."""
        if not self.config_path.exists():
            return
        try:
            raw = self.config_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            raw_providers = data.get("providers", {})
            self._role_preferences = data.get("role_preferences", {})

            for pid, pdata in raw_providers.items():
                models = [CustomModelSpec(**m) for m in pdata.get("models", [])]
                spec = CustomProviderSpec(
                    id=pid,
                    name=pdata.get("name", pid),
                    base_url=pdata.get("base_url", ""),
                    has_api_key=pdata.get("has_api_key", False),
                    models=models,
                    created_at=pdata.get("created_at", _utcnow_iso()),
                    updated_at=pdata.get("updated_at", _utcnow_iso()),
                )
                self._providers[pid] = spec

                # Read key from keyring if configured
                account_key = f"PROVIDER_KEY_{pid}"
                secret = _read_keyring(_KEYRING_SERVICE, account_key)
                if secret:
                    self._in_memory_keys[pid] = secret
                    spec.has_api_key = True
                elif pdata.get("has_api_key"):
                    # Fallback check under plain env var
                    env_val = os.environ.get(f"CALIENNE_PROVIDER_{pid.upper()}_KEY", "")
                    if env_val:
                        self._in_memory_keys[pid] = env_val

        except Exception as exc:
            logger.error("Failed to load custom providers from %s: %s", self.config_path, exc)

    def _save_to_disk(self) -> None:
        """Persist metadata (without plaintext keys) to config/custom_providers.json."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            providers_data = {}
            for pid, spec in self._providers.items():
                providers_data[pid] = {
                    "id": spec.id,
                    "name": spec.name,
                    "base_url": spec.base_url,
                    "has_api_key": spec.has_api_key,
                    "models": [m.model_dump() for m in spec.models],
                    "created_at": spec.created_at,
                    "updated_at": spec.updated_at,
                }
            payload = {
                "providers": providers_data,
                "role_preferences": self._role_preferences,
            }
            self.config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to save custom providers to %s: %s", self.config_path, exc)

    # ── Model Discovery from URLs ────────────────────────────────────────────

    async def discover_models(
        self, base_url: str, api_key: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """
        Probe an OpenAI-compatible / OpenRouter / Ollama endpoint to discover models.
        """
        base = base_url.strip().rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[:-17]
        elif base.endswith("/completions"):
            base = base[:-12]

        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "Calienne-Model-Discovery/1.0",
        }
        if api_key and api_key.strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"

        candidates = [
            f"{base}/models",
            f"{base}/v1/models" if not base.endswith("/v1") else f"{base}/models",
            f"{base}/api/tags",
            f"{base}/api/v1/models",
        ]
        seen_urls: set[str] = set()
        urls_to_try: list[str] = []
        for u in candidates:
            if u not in seen_urls:
                seen_urls.add(u)
                urls_to_try.append(u)

        last_error = "Could not connect to model endpoint."
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            for url in urls_to_try:
                try:
                    res = await client.get(url, headers=headers)
                    if res.status_code == 200:
                        data = res.json()
                        models = self._parse_models_response(data)
                        if models:
                            return models
                    elif res.status_code in (401, 403):
                        last_error = f"Authentication failed (HTTP {res.status_code}). Please check your API key."
                    else:
                        last_error = f"Endpoint {url} returned HTTP {res.status_code}: {res.text[:150]}"
                except httpx.ConnectError:
                    last_error = f"Connection refused connecting to {url}. Ensure the server is running."
                except httpx.TimeoutException:
                    last_error = f"Timed out connecting to {url} after 15 seconds."
                except Exception as exc:
                    last_error = f"Error querying {url}: {exc}"

        raise ValueError(last_error)

    def _parse_models_response(self, data: Any) -> list[dict[str, Any]]:
        """Parse different provider model listing payloads into a standard format."""
        results: list[dict[str, Any]] = []

        if isinstance(data, dict):
            if "data" in data and isinstance(data["data"], list):
                for item in data["data"]:
                    if isinstance(item, dict) and "id" in item:
                        mid = str(item["id"])
                        name = item.get("name") or mid
                        desc = item.get("description")
                        ctx = item.get("context_length") or item.get("max_tokens")
                        results.append({
                            "id": mid,
                            "name": name,
                            "description": desc,
                            "context_length": ctx,
                        })
                    elif isinstance(item, str):
                        results.append({"id": item, "name": item})
            elif "models" in data and isinstance(data["models"], list):
                for item in data["models"]:
                    if isinstance(item, dict):
                        m_name = item.get("name") or item.get("model") or item.get("id")
                        if m_name:
                            results.append({
                                "id": str(m_name),
                                "name": str(m_name),
                                "description": f"Size: {item.get('size', 'N/A')}",
                            })
                    elif isinstance(item, str):
                        results.append({"id": item, "name": item})
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "id" in item:
                    results.append({"id": str(item["id"]), "name": item.get("name") or str(item["id"])})
                elif isinstance(item, str):
                    results.append({"id": item, "name": item})

        results.sort(key=lambda m: m["id"].lower())
        return results

    # ── Provider Management ──────────────────────────────────────────────────

    def register_or_update_provider(
        self,
        name: str,
        base_url: str,
        api_key: Optional[str] = None,
        models: Optional[list[dict[str, Any]]] = None,
        provider_id: Optional[str] = None,
        strategy: Optional[Any] = None,
        pool: Optional[Any] = None,
    ) -> CustomProviderSpec:
        """Register a new provider or update an existing one, saving secret to Keyring."""
        pid = _sanitize_slug(provider_id or name)
        base = base_url.strip().rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[:-17]
        elif base.endswith("/completions"):
            base = base[:-12]

        now = _utcnow_iso()
        existing = self._providers.get(pid)

        has_key = bool(existing and existing.has_api_key)
        if api_key is not None and api_key.strip():
            clean_key = api_key.strip()
            _write_keyring(_KEYRING_SERVICE, f"PROVIDER_KEY_{pid}", clean_key)
            self._in_memory_keys[pid] = clean_key
            has_key = True
            os.environ["CALIENNE_ALLOW_LIVE_KEYS"] = "1"
            os.environ["CALIENNE_ALLOW_LIVE_KEYS"] = "1"

        model_specs: list[CustomModelSpec] = []
        if models is not None:
            for m in models:
                mid = m["id"]
                m_name = m.get("name") or mid
                full_id = f"{pid}/{mid}"
                roles = m.get("roles") or ["generation"]
                enabled = m.get("enabled", True)
                model_specs.append(
                    CustomModelSpec(
                        id=mid,
                        name=m_name,
                        full_id=full_id,
                        roles=roles,
                        enabled=enabled,
                        context_length=m.get("context_length"),
                        description=m.get("description"),
                    )
                )
        elif existing:
            model_specs = existing.models

        spec = CustomProviderSpec(
            id=pid,
            name=name.strip(),
            base_url=base,
            has_api_key=has_key,
            models=model_specs,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._providers[pid] = spec
        self._save_to_disk()

        if strategy is not None and pool is not None:
            self._sync_provider_to_strategy_and_pool(spec, strategy, pool)

        return spec

    def delete_provider(
        self,
        provider_id: str,
        strategy: Optional[Any] = None,
        pool: Optional[Any] = None,
    ) -> bool:
        """Remove a custom provider, delete its keyring secrets, and unregister models."""
        if provider_id not in self._providers:
            return False

        spec = self._providers.pop(provider_id)
        self._in_memory_keys.pop(provider_id, None)
        _delete_keyring(_KEYRING_SERVICE, f"PROVIDER_KEY_{provider_id}")
        self._save_to_disk()

        if strategy is not None:
            for m in spec.models:
                strategy.remove_model(m.full_id)

        return True

    def get_provider(self, provider_id: str) -> Optional[CustomProviderSpec]:
        return self._providers.get(provider_id)

    def get_api_key(self, provider_id: str) -> Optional[str]:
        """Retrieve decrypted API key from in-memory cache or OS Keyring."""
        if provider_id in self._in_memory_keys:
            return self._in_memory_keys[provider_id]
        key = _read_keyring(_KEYRING_SERVICE, f"PROVIDER_KEY_{provider_id}")
        if key:
            self._in_memory_keys[provider_id] = key
            return key
        return None

    def get_custom_providers(self) -> dict[str, CustomProviderSpec]:
        return self._providers

    def list_providers_view(self) -> list[dict[str, Any]]:
        """Return public/masked view of all custom providers."""
        views = []
        for pid, p in self._providers.items():
            key = self.get_api_key(pid)
            masked = f"••••••••••••{key[-4:]}" if (key and len(key) >= 4) else ("Keyring Protected" if p.has_api_key else "No Key Required")  # noqa: E501
            views.append({
                "id": p.id,
                "name": p.name,
                "base_url": p.base_url,
                "has_api_key": p.has_api_key,
                "masked_key": masked,
                "models_count": len(p.models),
                "models": [m.model_dump() for m in p.models],
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            })
        return views

    # ── Role & Judge Configuration ───────────────────────────────────────────

    def update_model_roles(
        self,
        full_model_id: str,
        roles: list[str],
        strategy: Optional[Any] = None,
        pool: Optional[Any] = None,
    ) -> bool:
        """Update role assignments for a specific model (e.g. ['judge', 'generation'])."""
        parts = full_model_id.split("/")
        pid = parts[0]
        if pid in self._providers:
            provider = self._providers[pid]
            for m in provider.models:
                if m.full_id == full_model_id:
                    m.roles = list(roles)
                    self._save_to_disk()
                    break

        if strategy is not None:
            strategy.set_model_roles(full_model_id, roles)
            if pool is not None:
                pool.register_provider(full_model_id.split("/")[0], roles=roles)

        return True

    def set_primary_role_model(
        self,
        role: str,
        full_model_id: str,
        strategy: Optional[Any] = None,
    ) -> bool:
        """Designate a model as primary for a role (e.g. role='judge' or role='generation')."""
        self._role_preferences[f"primary_{role}"] = full_model_id
        self._save_to_disk()

        if strategy is not None:
            strategy.set_primary_model(role, full_model_id)
        return True

    def get_role_preferences(self) -> dict[str, str]:
        return self._role_preferences

    # ── Strategy & Pool Synchronization ──────────────────────────────────────

    def _sync_provider_to_strategy_and_pool(
        self, spec: CustomProviderSpec, strategy: Any, pool: Any
    ) -> None:
        """Register all enabled models of a provider into Strategy and Pool."""
        for m in spec.models:
            if m.enabled:
                for role in m.roles:
                    strategy.add_model(m.full_id, role=role)
                    pref_key = f"primary_{role}"
                    if pref_key not in self._role_preferences:
                        self._role_preferences[pref_key] = m.full_id
                        strategy.set_primary_model(role, m.full_id)
                pool.register_provider(spec.id, roles=m.roles)
            else:
                strategy.set_model_enabled(m.full_id, False)

    def bootstrap(self, strategy: Any, pool: Any) -> int:
        """
        Called at server startup to load all custom providers, keys from Keyring,
        and wire them into the Strategy and Pool.
        """
        count = 0
        for spec in self._providers.values():
            self._sync_provider_to_strategy_and_pool(spec, strategy, pool)
            count += len([m for m in spec.models if m.enabled])

        # Apply primary role preferences
        for pref_key, model_id in self._role_preferences.items():
            if pref_key.startswith("primary_"):
                role = pref_key[len("primary_"):]
                strategy.set_primary_model(role, model_id)

        logger.info("ProviderRegistry bootstrapped %d custom model(s).", count)
        return count


# Singleton accessor
_registry_instance: Optional[ProviderRegistry] = None


def get_provider_registry() -> ProviderRegistry:
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ProviderRegistry()
    return _registry_instance
