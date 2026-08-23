"""Exit-gate tests for the capability loader (Step 18, RFC-002 §5, ADR-005).

Covers the fail-safe contract: missing file, malformed JSON, out-of-range
weight, unknown task_type, ``AETHERIS_CAPABILITIES_PATH`` override, and the
``_meta`` metadata-key strip. Construction must never raise.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from api_gateway.capabilities import (
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_PROVIDER_LIMIT,
    NEUTRAL_WEIGHT,
    CapabilityRegistry,
    ProviderConfig,
    get_capability_registry,
)


def _scratch_dir() -> Path:
    root = Path("C:/Users/amand/AppData/Local/Temp/opencode") / f"caps-{uuid.uuid4()}"
    root.mkdir(parents=True, exist_ok=True)
    return root


# ── Missing files ────────────────────────────────────────────────────────


def test_missing_files_fall_back_to_neutral_and_flag_failure() -> None:
    reg = CapabilityRegistry(capabilities_dir=_scratch_dir())  # empty dir
    assert reg.capability_load_failed is True
    assert set(reg.load_errors)  # every section recorded a reason
    # Accessors degrade to documented defaults, never raise.
    assert reg.model_weight("google/gemini-pro-latest", "coding") == NEUTRAL_WEIGHT
    assert reg.max_concurrency("google/gemini-pro-latest") == DEFAULT_MAX_CONCURRENCY
    assert reg.provider_parallel_limit("google") == DEFAULT_PROVIDER_LIMIT["parallel_limit"]


# ── Malformed JSON ───────────────────────────────────────────────────────


def test_malformed_json_records_error_and_neutral_weight() -> None:
    d = _scratch_dir()
    (d / "model_capabilities.json").write_text("{ this is not json ", encoding="utf-8")
    reg = CapabilityRegistry(capabilities_dir=d)
    assert "model_capabilities" in reg.load_errors
    assert reg.capability_load_failed is True
    assert reg.model_weight("google/gemini-pro-latest", "coding") == NEUTRAL_WEIGHT


# ── Out-of-range weight ──────────────────────────────────────────────────


def test_out_of_range_weight_falls_back_to_neutral() -> None:
    d = _scratch_dir()
    (d / "model_capabilities.json").write_text(
        json.dumps(
            {
                "models": {
                    "acme/model": {
                        "max_concurrency": 3,
                        "weights": {"coding": 1.5, "math": -0.2, "general": 0.7},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    reg = CapabilityRegistry(capabilities_dir=d)
    # Out-of-range values are rejected → neutral; valid value passes through.
    assert reg.model_weight("acme/model", "coding") == NEUTRAL_WEIGHT
    assert reg.model_weight("acme/model", "math") == NEUTRAL_WEIGHT
    assert reg.model_weight("acme/model", "general") == 0.7
    # max_concurrency still read from the same (valid) block.
    assert reg.max_concurrency("acme/model") == 3


# ── Unknown task_type / unknown model ────────────────────────────────────


def test_unknown_task_type_and_model_return_neutral() -> None:
    d = _scratch_dir()
    (d / "model_capabilities.json").write_text(
        json.dumps({"models": {"acme/model": {"weights": {"coding": 0.9}}}}),
        encoding="utf-8",
    )
    reg = CapabilityRegistry(capabilities_dir=d)
    assert reg.model_weight("acme/model", "astrology") == NEUTRAL_WEIGHT  # unknown task
    assert reg.model_weight("ghost/model", "coding") == NEUTRAL_WEIGHT  # unknown model


# ── Env-path override ────────────────────────────────────────────────────


def test_env_override_path_is_used(monkeypatch) -> None:
    d = _scratch_dir()
    (d / "provider_limits.json").write_text(
        json.dumps({"providers": {"acme": {"parallel_limit": 99}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AETHERIS_CAPABILITIES_PATH", str(d))
    # No explicit dir → must consult the env var.
    reg = CapabilityRegistry()
    assert reg.provider_parallel_limit("acme") == 99
    # And the module singleton honors refresh under the same env.
    reg2 = get_capability_registry(refresh=True)
    assert reg2.provider_parallel_limit("acme") == 99
    # Restore the module singleton to the real repo config so later tests /
    # default-constructed strategies don't see this scratch dir.
    monkeypatch.delenv("AETHERIS_CAPABILITIES_PATH")
    get_capability_registry(refresh=True)


# ── _meta strip ──────────────────────────────────────────────────────────


def test_meta_keys_are_stripped() -> None:
    d = _scratch_dir()
    (d / "routing_defaults.json").write_text(
        json.dumps({"_meta": {"owner": "x"}, "early_exit": {"confidence": 0.95}}),
        encoding="utf-8",
    )
    reg = CapabilityRegistry(capabilities_dir=d)
    defaults = reg.routing_defaults()
    assert "_meta" not in defaults
    assert defaults["early_exit"]["confidence"] == 0.95


# ── Real config loads clean ──────────────────────────────────────────────


def test_repo_config_loads_without_errors() -> None:
    reg = CapabilityRegistry()  # default dir = config/capabilities/
    assert reg.capability_load_failed is False, reg.load_errors
    assert reg.max_concurrency("google/gemini-pro-latest") == 4
    assert reg.provider_parallel_limit("google") == 8


def test_provider_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProviderConfig(parallel_limit=5, typo_limit=10)
