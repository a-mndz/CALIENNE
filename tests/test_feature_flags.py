from __future__ import annotations

import logging
import uuid
from pathlib import Path

from orchestrator.feature_flags import load_flags


def _scratch_file(name: str) -> Path:
    root = Path("C:/Users/amand/AppData/Local/Temp/opencode")
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{uuid.uuid4()}-{name}"


def test_load_flags_precedence_env_over_file_over_default() -> None:
    config_path = _scratch_file("feature_flags.json")
    config_path.write_text(
        """
        {
          "flags": {
            "CALIENNE_ENABLE_PLANNER": false,
            "CALIENNE_ENABLE_DAG": true,
            "CALIENNE_ENABLE_CONTEXT": true
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    flags = load_flags(
        {
            "CALIENNE_ENABLE_PLANNER": "true",
            "CALIENNE_ENABLE_DAG": "false",
        },
        config_path=config_path,
    )

    assert flags.planner is True
    assert flags.dag is False
    assert flags.context is True
    assert flags.consensus is False


def test_reserved_v2_flags_warn_and_remain_disabled(caplog) -> None:
    config_path = _scratch_file("feature_flags.json")
    config_path.write_text('{"flags": {}}', encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        flags = load_flags(
            {
                "CALIENNE_ENABLE_META_ESCALATION": "true",
                "CALIENNE_ENABLE_SELF_LEARNING": "1",
            },
            config_path=config_path,
        )

    assert flags.meta_escalation is False
    assert flags.self_learning is False
    assert "CALIENNE_ENABLE_META_ESCALATION is reserved for v2" in caplog.text
    assert "CALIENNE_ENABLE_SELF_LEARNING is reserved for v2" in caplog.text
