"""Typed feature-flag accessor for the v1 runtime.

Flags load with precedence: environment > config/feature_flags.json >
 hardcoded defaults. v2-reserved flags log a warning and remain disabled in v1.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

LOGGER = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "feature_flags.json"

_FLAG_FIELDS: tuple[tuple[str, str], ...] = (
    ("CALIENNE_ENABLE_PLANNER", "planner"),
    ("CALIENNE_ENABLE_DAG", "dag"),
    ("CALIENNE_ENABLE_CONSENSUS", "consensus"),
    ("CALIENNE_ENABLE_RAG", "rag"),
    ("CALIENNE_ENABLE_REPAIR", "repair"),
    ("CALIENNE_ENABLE_PREDICTION", "prediction"),
    ("CALIENNE_ENABLE_CONTEXT", "context"),
    ("CALIENNE_ENABLE_SKILLS", "skills"),
    ("CALIENNE_ENABLE_EXPERIENCE_DB", "experience_db"),
    ("CALIENNE_ENABLE_KNOWLEDGE_LAYER", "knowledge_layer"),
    ("CALIENNE_ENABLE_REPLAY", "replay"),
    ("CALIENNE_ENABLE_META_ESCALATION", "meta_escalation"),
    ("CALIENNE_ENABLE_SELF_LEARNING", "self_learning"),
)

_RESERVED_V2_FLAGS: frozenset[str] = frozenset(
    {
        "CALIENNE_ENABLE_META_ESCALATION",
        "CALIENNE_ENABLE_SELF_LEARNING",
        "CALIENNE_ENABLE_META_ESCALATION",
        "CALIENNE_ENABLE_SELF_LEARNING",
    }
)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}


@dataclass(frozen=True)
class FeatureFlags:
    planner: bool = False
    dag: bool = False
    consensus: bool = False
    rag: bool = False
    repair: bool = False
    prediction: bool = False
    context: bool = False
    skills: bool = False
    experience_db: bool = False
    knowledge_layer: bool = False
    replay: bool = False
    meta_escalation: bool = False
    self_learning: bool = False

    def as_env_map(self) -> dict[str, bool]:
        res: dict[str, bool] = {}
        for env_name, field_name in _FLAG_FIELDS:
            val = getattr(self, field_name)
            res[env_name] = val
            res[env_name.replace("CALIENNE_ENABLE_", "CALIENNE_ENABLE_")] = val
        return res


def _coerce_bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    return default


def _load_file_flags(config_path: Path) -> dict[str, bool]:
    if not config_path.is_file():
        return {}

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Failed to load feature flags from %s: %s", config_path, exc)
        return {}

    flags = payload.get("flags", {}) if isinstance(payload, dict) else {}
    if not isinstance(flags, dict):
        LOGGER.warning("Feature flag config at %s is missing a valid 'flags' object", config_path)
        return {}

    return {
        key: _coerce_bool(value)
        for key, value in flags.items()
        if not key.startswith("_")
    }


def load_flags(
    env: Mapping[str, object] | None = None,
    *,
    config_path: str | Path | None = None,
) -> FeatureFlags:
    """Load typed feature flags with env > file > hardcoded-off precedence."""

    environment = os.environ if env is None else env
    resolved_config_path = Path(config_path) if config_path is not None else _DEFAULT_CONFIG_PATH
    file_flags = _load_file_flags(resolved_config_path)

    resolved: dict[str, bool] = {}
    for env_name, field_name in _FLAG_FIELDS:
        legacy_name = env_name.replace("CALIENNE_ENABLE_", "CALIENNE_ENABLE_")
        default = file_flags.get(env_name, file_flags.get(legacy_name, False))
        matched_name = env_name if env_name in environment else legacy_name
        env_val = environment.get(env_name) if env_name in environment else environment.get(legacy_name)
        value = _coerce_bool(env_val, default=default)
        if (env_name in _RESERVED_V2_FLAGS or legacy_name in _RESERVED_V2_FLAGS) and value:
            LOGGER.warning("%s is reserved for v2 and remains disabled in v1", matched_name)
            value = False
        resolved[field_name] = value

    return FeatureFlags(**resolved)


FLAGS = load_flags()

