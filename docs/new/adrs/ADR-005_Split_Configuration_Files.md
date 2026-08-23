# ADR-005: Split Configuration Files under `config/capabilities/`

- **Status:** Accepted
- **Date:** 2026-07-13
- **Deciders:** CALIENNE architecture working group
- **Related RFCs:** RFC-002, RFC-005

## Context

`MODEL_CAPABILITY_WEIGHTS` was originally proposed as a single inline
dict in `api_gateway/strategy.py`. As the system grows, several
distinct concerns need to be configured separately:

- **What models are good at** (per-task-type weights).
- **Infrastructure limits** (`max_parallel`, `rpm`, `tpm`, `burst`,
  `timeout_ms`).
- **Cost data** (per-model and per-route pricing).
- **Default orchestration policies** (per-route `preferred_model_tier`,
  `max_judges`, `allow_repair`, `target_latency_ms`, `requires_rag`,
  `minimum_sources`).
- **Calibration priors** for the prediction layer.

Conflating all of these into a single file makes every change
high-friction: editing the calibration table would touch the same
file as pricing, and review tools would not surface the change
category.

## Decision

Capability configuration is split into a directory at the repository
root:

```text
config/
└── capabilities/
    ├── model_capabilities.json
    ├── provider_limits.json
    ├── pricing.json
    ├── routing_defaults.json
    └── prediction_calibration.json
```

Per-skill prompt versioning lives separately at
`config/prompt_versions.json` (not under `capabilities/`, because
prompts are not capabilities).

A loader in `api_gateway/capabilities.py` reads on import and on a
config-reload signal, with the override path
`CALIENNE_CAPABILITIES_PATH=/abs/path/to/dir` for tests and per-env
overrides. On load failure (missing file, malformed JSON, out-of-range
weight, unknown `task_type`): log a warning, fall back to a neutral
default of `0.5` for the affected model, and emit a
`capability_load_failed` metric. **Never** raise into the request
path.

The `MODEL_CAPABILITY_WEIGHTS` dict is removed from
`api_gateway/strategy.py`; the strategy module consults the loader.
Tests must not depend on the real config; they pass a temp directory
or use a `monkeypatch`-able loader.

## Consequences

Easier:

- Each file is owned by a specific concern; reviews and PRs are
  categorically clear.
- Calibration, pricing, and limits can evolve on different cadences.
- Local dev can override one file without affecting others.
- Schema validation can be per-file with tighter rules.

Harder:

- Five files to keep coherent. Mitigation: the loader validates
  cross-references (e.g. every model referenced in `routing_defaults`
  exists in `model_capabilities`).
- One extra layer in the loader. Acceptable.

## Alternatives Considered

- **Single `config/capabilities.json` with nested keys.** Rejected: a
  single file makes every change touch every concern, and schema
  validation cannot be per-concern.
- **Config in environment variables only.** Rejected: env vars are
  poor at expressing structured data, and history / diffs become
  unreadable.
- **Config in a database.** Rejected: introduces a runtime dependency
  for a system that should be configurable without a live DB.
