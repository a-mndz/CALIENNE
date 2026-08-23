# CALIENNE Deep Research Report

## Executive Summary

CALIENNE (Adaptive Multi-Model Reasoning Orchestrator) is a sophisticated multi-agent reasoning system that implements a **validation-arbitration pipeline** (Logician + Creative + Synthesis Judge) with provider resilience, hallucination firewall, execution manifests, and adaptive DAG-based orchestration. This report provides a comprehensive technical analysis of its architecture, strengths, weaknesses, and relevant research landscape.

---

## 1. Architecture Overview

### 1.1 Core Pipeline (Micro-Mode — Legacy/Load-Bearing Path)

```
┌─────────────┐     ┌─────────────────┐     ┌──────────────┐
│   User      │────▶│  FastAPI Server │────▶│  Breaker     │
│  (Browser)  │     │  / CLI REPL     │     │  Gate        │
└─────────────┘     └─────────────────┘     └──────────────┘
                                                     │
                              ┌──────────────────────┘
                              ▼
              ┌─────────────────────────────┐
              │  Logician Agent  │  Creative │
              │  (deductive)     │  Agent    │
              │                  │ (lateral) │
              └────────┬─────────┴─────┬─────┘
                       │                 │
                       ▼                 ▼
              ┌─────────────────────────────┐
              │    Synthesis Judge           │
              │  (arbitrate + validate)     │
              └──────────────┬──────────────┘
                             │
                             ▼
              ┌─────────────────────────────┐
              │  Final Answer + Score +     │
              │  Agent Reasoning (expandable)│
              └─────────────────────────────┘
```

**Four-Stage Pipeline:**
1. **Breaker Gate** (100ms timeout) — Knowledge absence detection (confidence < 0.3 or sentinel "KNOWLEDGE ABSENCE DETECTED")
2. **Parallel Generation** (30s timeout) — Logician (deductive) + Creative (lateral) agents run concurrently
3. **Judge Synthesis** — Arbitrates between outputs, produces validation score (0-10), confidence, bias risk
4. **Firewall + Assembly** — Hallucination firewall qualifies/removes unsupported claims, returns ExecutionManifest

### 1.2 Adaptive Runtime v1 (Flag-Gated, Default OFF)

The system is migrating to a **planner-driven, DAG-based, async-first orchestration runtime** behind `CALIENNE_ENABLE_*` feature flags (architecture version `0.1.7`, 22/23 steps complete).

**Key Subsystems (landed, flagged off):**
| Subsystem | Flag | Description |
|-----------|------|-------------|
| Classifier + Deterministic Planner | `PLANNER` | IntentAnalyzer + rule-based fallback |
| Graph Planner + Event-Driven Scheduler | `DAG`, `PLANNER` | DAG builder, asyncio.Condition scheduler |
| Token Budget Manager + Prediction | `PREDICTION` | Cost/latency/token/confidence estimation |
| Context Manager | `CONTEXT` | Importance ranking, per-node window assembly |
| Dynamic Skill Composition | `SKILLS` | Skill fragments + compatibility rules |
| MetaReasoner + Early Exit | — | Graph mutation (merge/skip/downgrade/reorder) |
| Uncertainty Engine | — | Structured ClarificationRequest |
| Reflection/Repair Loop | `REPAIR` | max_repairs=2, re-judge |
| Weighted Consensus | `CONSENSUS` | Multi-judge allocation |
| Smart RAG | `RAG` | SourceCandidate ranking, route-gated |
| Memory Hierarchy | `CONTEXT` | 6 layers (short/long/user/agent/shared/vector) |
| Knowledge/Reasoning/Validation Layer Separation | `KNOWLEDGE_LAYER` | RFC-001 layer split |
| Agent I/O Contracts | — | validate_inputs/outputs, to_failure_response |
| Resource Manager + Capability Loader | — | Global/route/model concurrency ceilings |
| Versioning + Execution Manifest | — | SHA-256 graph fingerprint, host snapshot |
| Execution Replay | `REPLAY` | Append-only traces, 30-day retention |
| Experience DB | `EXPERIENCE_DB` | PostgreSQL (operational + learning tables) |

---

## 2. Strengths & Innovations

### 2.1 Validation Arbitrage (Core Differentiator)
- **Two independent reasoning agents** (Logician: deductive, Creative: lateral) reason orthogonally
- **Synthesis Judge** resolves contradictions and scores consistency (0-10 validation score)
- Produces **confidence score + diversity metric**, not just a guess
- Research-backed: Multi-agent debate improves factuality and reasoning (Du et al., 2023; Liang et al., 2023)

### 2.2 Provider Resilience (Production-Grade)
- **Multi-provider support**: OpenRouter, Groq, NVIDIA NIM, GitHub Models, Ollama (local)
- **Circuit Breaker**: 3 consecutive failures → DEAD state, 60s cooldown
- **Exponential backoff + jitter** for retries
- **Priority routing**: Automatic fallback chain on failure/timeout
- **Simulation Mode**: Zero-cost development without API keys (refused in production)

### 2.3 Hallucination Firewall (Default ON as of Step 14)
- **Claim extraction** → Evidence building → Deterministic validation → Firewall rewrites/qualifies unsupported claims
- Replaces previous placeholder (always returned UNVERIFIED at 0.3 confidence)
- Appends disagreement note: "Hallucination firewall qualified N unsupported claim(s)."
- Returns `firewall_result` payload with original/sanitized text and removed claim count

### 2.4 Execution Manifest & Observability
- **Immutable ExecutionManifest** per request: SHA-256 graph fingerprint, host snapshot, version stamps
- Serialized in `passport.to_dict()` → surfaced as `metrics` field in response
- **Rolling metrics**: breaker_pass_rate, judge_agreement_rate, synthesis_quality_avg (100-window)
- **SSE streaming** with per-agent progress events shared between streaming/blocking paths

### 2.5 Secure Authentication & Session Management
- JWT via httpOnly, SameSite=Strict cookies
- IP-scoped rate limiting on auth endpoints
- CSRF origin verification on state-changing requests
- PostgreSQL async ORM (SQLAlchemy 2.0 + asyncpg) for sessions/messages

### 2.6 Async-Native Architecture
- Built on `asyncio`, `httpx.AsyncClient`, FastAPI
- Concurrent agent calls without blocking
- Event-driven scheduler (asyncio.Condition) for DAG execution
- StreamingManager for real-time telemetry

### 2.7 Three Operating Modes (No Code Changes)
| Mode | Models | Cost | Use Case |
|------|--------|------|----------|
| `FREE` | Llama 3, Mistral, Gemma | $0 | Testing, dev, low-stakes |
| `HYBRID` | Claude 3.5 Sonnet + GPT-4o-mini + Llama 3 fallback | Low | Balanced quality/cost |
| `PAID` | Claude 3.5 Sonnet + GPT-4o + Llama 3.1 70B | Higher | Max accuracy, production |

---

## 3. Problems & Architectural Risks

### 3.1 God-Object DecisionEngine (HIGH RISK)
**Location:** `orchestrator/decisions.py` (~621 lines)

The `DecisionEngine` class concentrates too many responsibilities:
- Breaker gate execution (100ms timeout logic)
- Generation agent orchestration (3 strategies: PARALLEL/SEQUENTIAL/CONDITIONAL)
- Judge synthesis invocation
- Metrics tracking (rolling windows)
- Streaming event emission
- RuntimeEngine delegation (HIGH-009)
- Provider call dispatch (with/without RuntimeEngine)

**Problems:**
- Violates Single Responsibility Principle
- Hard to test in isolation (mocks required for gateway, strategy, pool, passport, streaming)
- Tight coupling to specific agent roles (breaker, logician, creative, judge)
- Strategy pattern embedded but not composable
- Metrics calculation mixed with execution logic

**Recommendation:** Decompose into:
- `BreakerGate` (breaker logic + timeout)
- `GenerationOrchestrator` (strategy-agnostic parallel/sequential/conditional)
- `JudgeSynthesizer` (judge invocation + placeholder handling)
- `DecisionMetricsCollector` (pure metrics aggregation)
- `AgentDispatcher` (provider call routing via RuntimeEngine)

### 3.2 Dual ResourceManager Instances (MEDIUM RISK)
**Locations:**
- `api_gateway/rate_limiter.py` → `ResourceManager` (provider-level: semaphores, circuit breakers, retry)
- `orchestrator/resource_manager.py` → `ResourceManager` (DAG-level: global/route/model concurrency ceilings)

**Problem:** Two classes with identical name but different responsibilities. In `calienne_orchestrator.py`:
```python
from api_gateway.rate_limiter import ResourceManager  # provider-level
from orchestrator.resource_manager import ResourceManager as DagResourceManager  # DAG-level
```

**Risk:** Confusion, accidental misuse, unclear ownership of concurrency limits.

**Recommendation:** Rename to `ProviderResourceManager` and `DagResourceManager` (or `ConcurrencyManager`).

### 3.3 Claim/Validation Overlap (MEDIUM RISK)
**Locations:**
- `orchestrator/claims.py` → `ClaimManager` (extract, validate, store, track provenance, firewall)
- `orchestrator/validation_layer.py` → `ValidationLayer` (process_claims, apply_firewall)

Both handle claim extraction, validation, and firewall application. `pipelines.py` calls both paths depending on flags:
```python
if validation_layer is not None:
    all_claims = validation_layer.process_claims(...)
    final_answer, unverified_dicts, firewall_result = validation_layer.apply_firewall(...)
else:
    all_claims = _process_claims_for_outputs(claim_manager, ...)
    final_answer, unverified_dicts, firewall_result = _apply_output_firewall(claim_manager, ...)
```

**Problem:** Duplicate logic paths, inconsistent behavior, unclear ownership.

### 3.4 Legacy Code Debt (MEDIUM RISK)
- **Legacy inline pipeline** preserved behind `calienne_LEGACY_PIPELINE_ENABLED` env var (~400 lines in `pipelines.py`)
- CRIT-001 enforces DecisionEngine as sole path, but legacy code remains for "staged rollouts"
- Dead code: `stream_micro_mode` generator removed but references persist
- Technical debt accumulates as adaptive v1 grows alongside legacy path

### 3.5 Observability Gaps (MEDIUM RISK)
- **No distributed tracing** (OpenTelemetry, Jaeger, Zipkin)
- **Passport logging** uses 3-retry with 1s delay — blocks completion on log backend failure
- **No structured logging** (JSON lines) for log aggregation
- **Metrics** only in-memory rolling windows, no Prometheus/OTel export
- **No alerting** on breaker_pass_rate drop, judge_agreement_rate decline, provider DEAD state

### 3.6 Configuration Complexity (LOW-MEDIUM)
- Capability data split across `config/capabilities/` (5 JSON files)
- Feature flags in `config/feature_flags.json` + env vars
- Prompt versions in `config/prompt_versions.json`
- No unified configuration schema or validation at startup
- Risk of capability drift between files

### 3.7 Experience DB — Offline Only (DESIGN DECISION)
- Two tables: `experience_operational` + `experience_learning`
- **Strictly offline in v1** (ADR-008) — no online learning
- Promotion policy: manual-PR only (governance gate)
- **Risk:** Experience DB becomes write-only landfill without automated analysis pipeline

### 3.8 Testing & Simulation Concerns
- **Simulation mode** fabricates deterministic mock responses
- In production (`CALIENNE_ENVIRONMENT=production`), missing keys raise `RuntimeError` + `CRITICAL` alarm
- **Risk:** Simulation path not exercised in CI against real providers
- No contract tests verifying simulation parity with real provider behavior

---

## 4. Research Landscape & Academic Context

### 4.1 Multi-Agent Orchestration Patterns

| Pattern | Description | CALIENNE Alignment |
|---------|-------------|-------------------|
| **Pipeline** | Sequential stages (Research → Draft → Critique → Revise) | Legacy micro-mode is linear pipeline |
| **Fan-out/Fan-in** | Parallel agents + aggregation (voting, weighted merge, LLM synthesis) | Logician + Creative parallel → Judge synthesis |
| **Debate** | Iterative multi-agent argument/refinement | Not implemented (could enhance Judge) |
| **Supervisor/Hierarchical** | Manager LLM routes to specialists | DecisionEngine acts as supervisor |
| **DAG/Graph** | Explicit dependency graph, topological execution | Adaptive v1: ExecutionPlanner → DAG → Scheduler |
| **Event-Driven** | Async pub/sub, reactive agents | Scheduler uses asyncio.Condition |
| **Actor Model** | Isolated state, message passing, supervision | Not used |

**Key Research:**
- **DynTaskMAS** (2025): Dynamic task graph + async parallel execution engine with priority-based scheduling
- **Microsoft Conductor** (2026): Deterministic orchestration — "orchestration should be deterministic and inspectable, not an LLM making routing decisions"
- **LangGraph/AutoGen v0.4**: Production frameworks converging on DAG + event-driven patterns

### 4.2 LLM-as-Judge & Validation Arbitrage

**Key Papers:**
- **ChatEval** (Chan et al., 2023): Multi-agent debate for better LLM evaluators
- **MAJ-EVAL** (2026): Multi-agent-as-judge with in-group deliberation + aggregation
- **Multi-Agent Debate for LLM Judges** (NeurIPS 2025): Beta-Binomial mixture for adaptive stability detection
- **Courtroom-Style PROClaim** (2026): Structured adversarial deliberation (Plaintiff/Defense/Judge roles)

**CALIENNE Approach:** Single Synthesis Judge (not multi-judge debate) with validation scoring. Weighted consensus (`CONSENSUS` flag) adds multi-judge allocation for high/critical tasks.

**Gap:** No iterative debate/refinement in Judge — single-pass arbitration. Could benefit from multi-round debate with stability detection.

### 4.3 Hallucination Firewall & Claim Validation

**State of the Art:**
- **Claimify** (Microsoft Research, 2024): 99% claim entailment, best precision/recall balance
- **Fact in Fragments** (2025): Atomic fact extraction + multi-hop verification
- **Lightweight Hallucination Firewall** (2024): TF-IDF evidence + deterministic self-check
- **Pelican** (2025): Claim decomposition + program-of-thought verification (8-32% hallucination reduction)

**CALIENNE Approach:** Deterministic evidence checker (Step 14) with claim extraction → evidence building → validation → firewall rewrite. Claims tracked in ReasoningGraph with provenance.

**Strengths:** Default ON, integrated with passport, returns structured `firewall_result`.

**Gaps:** No external knowledge retrieval (RAG flag-gated), no programmatic verification (code execution), no multi-hop reasoning for complex claims.

### 4.4 Circuit Breaker & Provider Resilience

**Industry Patterns (Portkey, TrueFoundry, NiteAgent):**
- **Layered**: Retry (transient) → Fallback (provider) → Circuit Breaker (systemic)
- **Circuit Breaker**: 3 states (Closed/Open/Half-Open), configurable thresholds
- **Hedging**: Near p95 latency, speculative parallel requests
- **Exponential backoff + jitter** standard

**CALIENNE:** Implements all three layers in `api_gateway/rate_limiter.py`:
- `AsyncAPIGateway.execute_with_fallback` with retry/backoff
- `ProviderPool` with circuit breaker (3 failures → DEAD, 60s cooldown)
- Provider priority chains per role

**Gap:** No hedging, no per-route SLO tuning, no cost-aware routing.

### 4.5 Execution Manifest & Versioning

**Related Work:**
- **Chain & Hash** (Russinovich et al., 2024): SHA-256 fingerprinting for model provenance
- **Docker manifest v2**: SHA-256 versioned manifests
- **Graph Praxis** (2025): JSON-defined agent graphs with declarative execution

**CALIENNE:** `ExecutionManifest` with:
- SHA-256 graph fingerprint (via `TopologyNormalizer`)
- Monotonic `graph_version` (via `VersionRegistry`)
- Host primitives (process start snapshot)
- Full feature-flag snapshot
- Per-skill prompt version pins
- Decoupled `manifest_schema_version` from `architecture_version`

**Strength:** Immutable, replayable, audit-ready. **Gap:** No remote manifest registry, no signed manifests.

---

## 5. Comparative Analysis

| Dimension | CALIENNE | LangGraph | AutoGen v0.4 | CrewAI | Microsoft Conductor |
|-----------|----------|-----------|--------------|--------|---------------------|
| **Orchestration Style** | Pipeline → DAG (v1) | DAG/Graph native | Event-driven actor | Sequential/Hierarchical | Deterministic workflow |
| **Validation** | Built-in Judge + Firewall | User-defined | User-defined | User-defined | Human-in-loop built-in |
| **Provider Resilience** | Multi-provider + CB + fallback | Manual | Manual | Manual | Multi-model routing |
| **Observability** | Passport + SSE + metrics | LangSmith | AutoGen Studio | Limited | Built-in tracing |
| **Session/Conversation** | PostgreSQL + ConversationDirector | Checkpointing | Built-in | Limited | Built-in |
| **Auth/Security** | JWT httpOnly + CSRF + injection detection | External | External | External | Built-in |
| **Adaptive/Dynamic** | Flag-gated v1 (planner + DAG) | Dynamic graphs | Dynamic handoffs | Limited | Static workflows |
| **Execution Manifest** | SHA-256 + host snapshot | No | No | No | No |
| **Hallucination Firewall** | Default ON (claim-level) | No | No | No | No |
| **Maturity** | Active dev (v0.1.7) | Production | Production | Production | Early OSS |

---

## 6. Recommended Improvements

### 6.1 Immediate (High Impact, Low Effort)

1. **Decompose DecisionEngine** — Split into 4-5 focused classes
2. **Rename dual ResourceManager** — `ProviderResourceManager` / `DagConcurrencyManager`
3. **Unify Claim/Validation paths** — Single `ValidationPipeline` owning extraction → validation → firewall
4. **Add structured JSON logging** — Replace `basicConfig` with `structlog` or `python-json-logger`
5. **Prometheus metrics endpoint** — Export breaker_pass_rate, judge_agreement_rate, provider health
6. **Remove legacy pipeline code** — Delete `calienne_LEGACY_PIPELINE_ENABLED` branch after v1 stabilization
7. **Add OpenTelemetry tracing** — Distributed traces across agents, gateway, database

### 6.2 Short-Term (1-2 Sprints)

8. **Implement Judge Debate** — Multi-round synthesis with stability detection (per NeurIPS 2025 paper)
9. **Add hedging support** — Speculative parallel requests near p95 latency
10. **External RAG integration** — Enable `RAG` flag with configurable retrievers (vector, keyword, hybrid)
11. **Cost-aware routing** — Prediction layer + Token Budget Manager for cost/latency optimization
12. **Manifest registry** — Store manifests in PostgreSQL with query API
13. **Contract testing** — Verify simulation mode parity with real providers in CI

### 6.3 Medium-Term (Architectural)

14. **Experience DB analysis pipeline** — Automated pattern mining, calibration promotion workflow
15. **Multi-tenant ResourceManager** — Per-user/per-org concurrency ceilings
16. **Signed Execution Manifests** — Cryptographic signing for audit trails
17. **Plugin architecture** — Custom agents, validators, retrievers via entry points
18. **Model distillation pipeline** — Train small router from Experience DB (v2)

### 6.4 Research Opportunities

19. **Adaptive early exit with formal guarantees** — MetaReasoner decisions with confidence bounds
20. **Uncertainty calibration** — Temperature scaling / conformal prediction for validation scores
21. **Cross-provider semantic equivalence** — Detect when different models produce semantically identical outputs
22. **Attack surface analysis** — Prompt injection, jailbreak, data exfiltration testing framework

---

## 7. Key Files Reference

| File | Purpose | Lines | Risk |
|------|---------|-------|------|
| `main.py` | CLI REPL entry point | 362 | Low |
| `server.py` | FastAPI server + auth + API | 1384 | Medium (monolithic) |
| `orchestrator/pipelines.py` | Micro-mode + DecisionEngine path | 1077 | High (dual paths) |
| `orchestrator/decisions.py` | DecisionEngine (god object) | 621 | **High** |
| `orchestrator/calienne_orchestrator.py` | Component factory | 193 | Low |
| `orchestrator/evaluation.py` | Judge synthesis | 114 | Low |
| `orchestrator/claims.py` | ClaimManager + firewall | ~400 | Medium |
| `orchestrator/validation_layer.py` | ValidationLayer (overlaps claims) | ~300 | Medium |
| `core/passport.py` | ExecutionPassport (thread-safe) | 355 | Low |
| `core/runtime.py` | RuntimeEngine + contracts | ~500 | Medium |
| `api_gateway/rate_limiter.py` | ProviderResourceManager + CB | ~600 | Medium |
| `api_gateway/client.py` | AsyncAPIGateway + simulation | ~400 | Low |
| `api_gateway/strategy.py` | ProviderStrategy (FREE/HYBRID/PAID) | ~300 | Low |
| `docs/new/plan.md` | Master roadmap (this analysis based on) | 314 | — |
| `docs/new/guide.md` | 23-step build tracker | — | — |
| `docs/new/rfcs/` | RFC-001..008 | — | — |
| `docs/new/adrs/` | ADR-001..008 | — | — |

---

## 8. Conclusion

CALIENNE is an **ambitious, well-architected system** with genuine innovations:
- Validation arbitrage (Logician + Creative + Judge) — rare in production systems
- Hallucination firewall default-ON with deterministic evidence checking
- ExecutionManifest for reproducibility and audit
- Provider resilience with circuit breaking built-in
- Clean migration path from pipeline → adaptive DAG behind feature flags

**Primary risks are architectural:** God-object DecisionEngine, dual ResourceManager, claim/validation overlap, and observability gaps. These are fixable with focused refactoring.

**Research alignment is strong:** The adaptive v1 design mirrors 2025-2026 academic trends (DynTaskMAS, Conductor, multi-agent debate judges). The hallucination firewall implements claim-level verification per Microsoft Claimify and Pelican approaches.

**Recommendation:** Prioritize DecisionEngine decomposition and observability (OpenTelemetry + Prometheus) before expanding adaptive v1 surface area. The foundation is solid but the god-object will become a bottleneck as DAG complexity grows.

---

## Appendix: Research Sources

### Academic Papers
1. Du et al. (2023) — "Improving Factuality and Reasoning in Language Models through Multi-Agent Debate"
2. Liang et al. (2023) — "Encouraging Divergent Thinking in LLMs through Multi-Agent Debate"
3. Chan et al. (2023) — "ChatEval: Towards Better LLM-based Evaluators through Multi-Agent Debate" (ICLR 2024)
4. NeurIPS 2025 — "Multi-Agent Debate for LLM Judges with Adaptive Stability Detection"
5. ACL 2026 — "MAJ-EVAL: Aligning LLM-Agent-Based Automated Evaluation with Multi-Dimensional Criteria"
6. arXiv 2025 — "DynTaskMAS: Dynamic Task Graph-driven Framework for Async/Parallel LLM-based MAS"
7. arXiv 2026 — "Courtroom-Style Multi-Agent Debate with Progressive RAG and Role-Switching" (PROClaim)
8. Microsoft Research (2024) — "Claimify: Extracting High-Quality Claims from Language Model Outputs"
9. arXiv 2025 — "Fact in Fragments: Deconstructing Complex Claims via Atomic Fact Extraction and Verification"
10. Russinovich et al. (2024) — "Chain & Hash: Cryptographic Provenance for LLMs"

### Industry Resources
- Portkey.ai — "Retries, Fallbacks, and Circuit Breakers in LLM Apps"
- TrueFoundry — "LLM Failover & Load Balancing for Provider Outages"
- Microsoft Conductor (2026) — "Deterministic Orchestration for Multi-Agent AI Workflows"
- NiteAgent (2026) — "Building Reliable Agent Error Handling"
- LangGraph / AutoGen v0.4 / CrewAI — Production orchestration frameworks

### CALIENNE Internal Docs
- `docs/new/plan.md` — Master roadmap & invariant index
- `docs/new/guide.md` — 23-step build tracker (Steps 1-22 complete)
- `docs/new/rfcs/RFC-001..008` — System Architecture, Execution Pipeline, Planner/Scheduler, Memory/RAG/Context, Versioning/Manifest, Feature Flags, Implementation Roadmap, Governance
- `docs/new/adrs/ADR-001..008` — Pydantic policy, Async-first, Planner+DAG, Resource Ceiling, Config split, Validation invariance, Graph templates, PostgreSQL persistence
- `docs/decision_register.md` — CI-checked decision log
- `docs/maturity.md` — Per-subsystem maturity matrix

---

*Report generated: 2026-08-19*  
*Based on CALIENNE architecture version 0.1.7 (commit inspection + documentation review)*