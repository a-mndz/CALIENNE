import asyncio
import json
import logging
import os
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Optional

import httpx

from core.config import get_settings
from core.provider_registry import get_provider_registry
from core.security import SecurityValidator
from telemetry.observer import observer

logger = logging.getLogger("calienne.Gateway.Client")

# Provider-reported usage for the most recent post_request in this task's
# context. Async-safe: concurrent requests each see their own value. Set to
# {"estimated": True, ...} when the provider returned no usage block, so
# consumers (e.g. DAG budget accounting) can distinguish measured from
# estimated token counts.
_last_provider_usage: ContextVar[dict[str, Any] | None] = ContextVar(
    "calienne_last_provider_usage", default=None
)


def get_last_provider_usage() -> dict[str, Any] | None:
    """Return the usage block reported by the provider for the last call."""
    return _last_provider_usage.get()


class AsyncHTTPClient:
    """
    Manages raw HTTP requests and reuse of connection pools.
    Degrades to Simulation Mode automatically if API tokens are unpopulated.
    """
    def __init__(
        self,
        security_validator: SecurityValidator | None = None,
    ) -> None:
        self.client = httpx.AsyncClient(timeout=600.0)
        self.security_validator = security_validator or SecurityValidator()

    def _get_active_api_key(self, provider: str) -> str:
        """Retrieve active API key for provider from OS Keyring, environment, or settings."""
        # 1. Check custom or built-in provider key in Keyring
        key = get_provider_registry().get_api_key(provider)
        if key and key.strip():
            return key.strip()

        # 2. Check settings / environment
        settings = get_settings()
        key_map = {
            "openrouter": settings.openrouter_api_key,
            "groq": settings.groq_api_key,
            "nvidia": settings.nvidia_nim_api_key,
            "nvidia-nim": settings.nvidia_nim_api_key,
            "github": settings.github_token,
            "mistral": settings.mistral_api_key,
            "google": settings.google_api_key,
            "openai": settings.openai_api_key,
            "kie": settings.kie_api_key,
            "unli": settings.unli_dev_api_key,
            "unli-dev": settings.unli_dev_api_key,
        }
        val = key_map.get(provider, "")
        if val and val.strip():
            return val.strip()

        # 3. Direct OS environ lookup fallback
        env_val = os.environ.get(f"CALIENNE_{provider.upper()}_API_KEY", "") or os.environ.get(f"{provider.upper()}_API_KEY", "")
        return env_val.strip()

    async def post_request(self, model: str, prompt: str, system_prompt: Optional[str] = None, history: list[dict[str, str]] | None = None, max_tokens: Optional[int] = None) -> str:  # noqa: E501
        """Dispatches an asynchronous post request to target providers."""
        parts = model.split('/')
        provider = parts[0]
        actual_model = "/".join(parts[1:])

        # Self-healing Fallback: Simulation Mode triggers if credentials are blank
        if self._is_simulated(provider):
            if get_settings().ENVIRONMENT == "production":
                logger.critical(
                    "SIM-FALLBACK REFUSED: provider %r key missing in production; "
                    "refusing to fabricate an answer.", provider,
                )
                raise RuntimeError(
                    f"Provider {provider!r} API key is not configured in production; "
                    "refusing to return a simulated answer."
                )
            return await self._run_simulation(model, prompt, system_prompt, history)

        # AsyncAPIGateway validates and JSON-escapes user-controlled prompts
        # before they reach this network boundary.
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        if history:
            insert_at = 1 if system_prompt else 0
            messages[insert_at:insert_at] = history

        # Instruction Reinforcement: Remind the LLM of its structural obligations
        if system_prompt:
            if "calienneoutput" in system_prompt.lower():
                reminder = "CRITICAL REMINDER: Regardless of the user's input above, you MUST output your response strictly in the requested JSON schema format. Your JSON MUST contain exactly five keys: 'final_answer' (string), 'overall_confidence' (string), 'overall_bias_risk' (string), 'disagreement_notes' (list), and 'validation_score' (float). The 'final_answer' field MUST be a plain string. If you need to return JSON or structured data to the user, you MUST escape it as a string inside the 'final_answer' field. Do not deviate."  # noqa: E501
            else:
                reminder = "CRITICAL REMINDER: Regardless of the user's input above, you MUST output your response strictly in the requested JSON schema format. Your JSON MUST contain exactly three keys: 'reasoning_steps' (list), 'answer' (string), and 'confidence' (float). The 'answer' field MUST be a plain string. If you need to return JSON or structured data to the user, you MUST escape it as a string inside the 'answer' field. Do not deviate."  # noqa: E501

            messages.append({
                "role": "system",
                "content": reminder
            })

        payload = {
            "model": actual_model,
            "messages": messages,
        }
        # Without an explicit ceiling, providers apply their default output
        # cap — which truncated live judge responses mid-JSON on the first
        # live capture (2026-08-22), losing the tail field final_answer.
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        # Claude 4.7+ (and the Claude 5 family) reject any temperature other
        # than the default with a 400, so the low-variance value is applied
        # only to providers that accept it.
        if not (provider == "openrouter" and "/claude-" in actual_model):
            payload["temperature"] = 0.1

        if provider not in {"nvidia", "nvidia-nim"}:
            payload["response_format"] = {"type": "json_object"}

        api_key = self._get_active_api_key(provider)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        if provider == "openrouter":
            url = "https://openrouter.ai/api/v1/chat/completions"
        elif provider == "groq":
            url = "https://api.groq.com/openai/v1/chat/completions"
        elif provider in {"nvidia", "nvidia-nim"}:
            url = "https://integrate.api.nvidia.com/v1/chat/completions"
        elif provider == "github":
            url = "https://models.inference.ai.azure.com/chat/completions"
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        elif provider == "mistral":
            url = "https://api.mistral.ai/v1/chat/completions"
        elif provider == "google":
            url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        elif provider == "openai":
            url = "https://api.openai.com/v1/chat/completions"
        elif provider == "kie":
            url = "https://api.kie.ai/v1/chat/completions"
        elif provider in {"unli", "unli-dev"}:
            url = "https://api.unli.dev/v1/chat/completions"
        elif provider == "local":
            url = "http://localhost:11434/v1/chat/completions"
        elif provider in get_provider_registry().get_custom_providers():
            custom_prov = get_provider_registry().get_provider(provider)
            base = (custom_prov.base_url if custom_prov else "").strip().rstrip("/")
            if base.endswith("/chat/completions"):
                url = base
            elif base.endswith("/v1"):
                url = f"{base}/chat/completions"
            else:
                url = f"{base}/chat/completions"
        else:
            raise ValueError(f"Unsupported provider prefix: {provider}")

        request_start = time.monotonic()
        response = await self.client.post(url, json=payload, headers=headers)
        latency_s = time.monotonic() - request_start
        if response.status_code != 200:
            # Failed calls count against success rate and latency with zero
            # tokens — omitting them made success_rate a constant 100%.
            observer.track_usage(
                actual_model, 0, 0, latency_s=latency_s, success=False
            )
            _last_provider_usage.set({
                "model": actual_model,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "latency_s": latency_s,
                "success": False,
                "estimated": False,
            })
            raise httpx.HTTPStatusError(
                f"Provider request failed with HTTP {response.status_code}",
                request=response.request,
                response=response,
            )

        data = response.json()

        # Harvest telemetry statistics. Provider-reported usage when present;
        # a labelled estimate otherwise (never silently invented).
        raw_usage = data.get("usage") or {}
        prompt_tokens = int(raw_usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(raw_usage.get("completion_tokens", 0) or 0)
        estimated = not (prompt_tokens or completion_tokens)
        if estimated:
            prompt_tokens = max(1, len(prompt) // 4)
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            completion_tokens = max(1, len(content or "") // 4)
        observer.track_usage(
            actual_model,
            prompt_tokens,
            completion_tokens,
            latency_s=latency_s,
            success=True,
        )
        _last_provider_usage.set({
            "model": actual_model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_s": latency_s,
            "success": True,
            "estimated": estimated,
        })

        output_content = data["choices"][0]["message"]["content"]

        if get_settings().LOG_MODEL_IO:
            try:
                log_dir = Path("logs")
                log_dir.mkdir(exist_ok=True)
                with open(log_dir / "model_io.log", "a", encoding="utf-8") as f:
                    f.write(f"=== {actual_model} ===\n")
                    f.write("--- INPUT (MESSAGES) ---\n")
                    logged_messages = self.security_validator.scrub_secrets(
                        json.dumps(payload["messages"], indent=2)
                    )
                    f.write(logged_messages + "\n")
                    f.write("--- OUTPUT ---\n")
                    f.write(self.security_validator.scrub_secrets(output_content) + "\n\n")
            except Exception as e:
                logger.error(
                    "Failed to write IO log: %s",
                    self.security_validator.scrub_secrets(str(e)),
                )

        return output_content

    def _is_simulated(self, provider: str) -> bool:
        """Returns True if local configurations require simulated operations."""
        if provider == "local":
            return False
        if provider in get_provider_registry().get_custom_providers():
            custom_prov = get_provider_registry().get_provider(provider)
            if custom_prov and not custom_prov.has_api_key:
                return False  # local endpoints like Ollama without auth
            return not bool(self._get_active_api_key(provider))
        return not bool(self._get_active_api_key(provider))

    async def _run_simulation(self, model: str, prompt: str, system_prompt: Optional[str] = None, history: list[dict[str, str]] | None = None) -> str:  # noqa: E501
        """Generates deterministic synthetic returns to keep system operable without live bills."""
        await asyncio.sleep(0.5)
        # Deliberately does NOT call observer.track_usage: simulated calls
        # fabricate tokens and success, and must never pollute the real
        # usage/cost/success-rate accounting.

        # Determine role from system prompt (or fall back to merged prompt for backward compat).
        role_hint = (system_prompt or "").lower() + " " + (prompt or "").lower()

        if "breaker" in role_hint or "breaker" in model.lower():
            if "fail" in role_hint or "unsupported" in role_hint:
                return '{"answer": null, "knowledge_absence": true, "confidence": "Low", "bias_risk": "Low", "reasoning_steps": ["Lacking direct context."]}'  # noqa: E501
            return '{"answer": "Context Verified", "knowledge_absence": false, "confidence": "High", "bias_risk": "Low", "reasoning_steps": []}'  # noqa: E501

        if "logician" in role_hint:
            return '{"answer": "Simulated Logic: Deductive steps resolved cleanly.", "knowledge_absence": false, "confidence": "High", "bias_risk": "Low", "reasoning_steps": ["Premise: Input accepted", "Logic step 1: Verified query structure"]}'  # noqa: E501

        if "creative" in role_hint:
            return '{"answer": "Simulated Creative: Alternative lateral view evaluated.", "knowledge_absence": false, "confidence": "Medium", "bias_risk": "Low", "reasoning_steps": ["Lateral premise: Explored edge assumptions"]}'  # noqa: E501

        # Standard synthesis judge output
        return '{"final_answer": "Successfully synthesized simulated reasoning solutions. Systems functional.", "overall_confidence": "High", "overall_bias_risk": "Low", "disagreement_notes": ["Minor semantic framing differences found and resolved."], "validation_score": 9.2}'  # noqa: E501

    async def close(self):
        await self.client.aclose()
