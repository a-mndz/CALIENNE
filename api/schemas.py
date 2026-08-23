"""Inbound request contracts (RFC-001 §4 critical-contract rule).

Unknown fields are rejected rather than silently ignored, so malformed or
unexpected client payloads fail fast instead of masking bugs. Response models
stay on plain ``BaseModel`` — only inbound request bodies are critical
contracts. Supersedes ``AetherisBaseModel`` once RFC-007 Step 2 lands
``core/base.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
