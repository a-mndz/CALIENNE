# CALIENNE Architecture Documentation

This document describes the component architecture of the Adaptive Multi-Model Reasoning Orchestrator (CALIENNE) integrated into the calienne codebase.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Frontend Layer (React)                          │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐               │
│  │ ChatWindow   │  │ ReasoningPanel│  │ TelemetryDrawer │               │
│  └──────┬───────┘  └──────┬───────┘  └────────┬────────┘               │
└─────────┼──────────────────┼───────────────────┼─────────────────────────┘
          │                  │                   │
          │            SSE Events Stream          │
          └──────────────────┴───────────────────┘
                             │
┌─────────────────────────────┴─────────────────────────────────────────────┐
│                          API Layer (FastAPI)                              │
│  ┌──────────────────┐  ┌─────────────────┐  ┌──────────────────┐        │
│  │  /query endpoint │  │ /status endpoint│  │ /stream endpoint │        │
│  └────────┬─────────┘  └────────┬────────┘  └────────┬─────────┘        │
└───────────┼─────────────────────┼────────────────────┼───────────────────┘
            │                     │                     │
┌───────────┴─────────────────────┴─────────────────────┴───────────────────┐
│                       Runtime Engine Layer                                │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │                      Execution Passport                          │    │
│  │  (request_id, session_id, security_metadata, execution_state)    │    │
│  └─────────────────┬────────────────────────────────────────────────┘    │
│                    │                                                      │
│  ┌─────────────────┴────────────────────────────────────────────┐        │
│  │              Security Validator                              │        │
│  │  ┌────────────────┐  ┌──────────────────┐  ┌─────────────┐  │        │
│  │  │ Input Escaping │  │ Injection Detect │  │ Secret Scrub│  │        │
│  │  └────────────────┘  └──────────────────┘  └─────────────┘  │        │
│  └───────────────────────────────┬──────────────────────────────┘        │
└────────────────────────────────────┼─────────────────────────────────────┘
                                    │
┌────────────────────────────────────┼─────────────────────────────────────┐
│                     Orchestration Layer                                  │
│  ┌──────────────────────────────────┴─────────────────────────────┐      │
│  │                    Pipeline Scheduler                          │      │
│  │  ┌─────────┐  ┌──────────┐  ┌────────┐  ┌──────────┐         │      │
│  │  │Normalize│→ │Breach    │→ │Generate│→ │Evaluate  │→ ···    │      │
│  │  │         │  │Check     │  │        │  │          │         │      │
│  │  └─────────┘  └──────────┘  └────────┘  └──────────┘         │      │
│  └───────────────────────┬──────────────────────────────────────┘      │
│                          │                                              │
│  ┌───────────────────────┴──────────────────┐                          │
│  │         Decision Engine                  │                          │
│  │  ┌────────────┐                          │                          │
│  │  │  Breaker   │ → Abort if absent        │                          │
│  │  └────────────┘                          │                          │
│  │  ┌────────────┐  ┌────────────┐         │                          │
│  │  │ Logician   │  │  Creative  │ Parallel │                          │
│  │  └──────┬─────┘  └──────┬─────┘         │                          │
│  │         └───────┬────────┘               │                          │
│  │         ┌───────┴────────┐               │                          │
│  │         │     Judge      │ Synthesize    │                          │
│  │         └────────────────┘               │                          │
│  └───────────────┬──────────────────────────┘                          │
│                  │                                                      │
│  ┌───────────────┴──────────────────────────────────────────┐          │
│  │          Conversation Director                            │          │
│  │  ┌────────────┐  ┌──────────────┐  ┌──────────────────┐ │          │
│  │  │History Mgmt│  │ Context Track│  │ State Transition │ │          │
│  │  └────────────┘  └──────────────┘  └──────────────────┘ │          │
│  └────────────────────────────────┬─────────────────────────┘          │
└────────────────────────────────────┼────────────────────────────────────┘
                                    │
┌────────────────────────────────────┼─────────────────────────────────────┐
│                     Knowledge & State Layer                              │
│  ┌──────────────────────┬──────────────────────────────────────┐        │
│  │  Reasoning Graph     │  ┌────────────┐  ┌────────────┐      │        │
│  │  ┌────────┐ ┌──────┐ │  │Claim Manager│  │  Memory   │      │        │
│  │  │Claims  │ │Edges │ │  │            │  │  Manager  │      │        │
│  │  └────────┘ └──────┘ │  └────────────┘  └────────────┘      │        │
│  └────────────────┬──────┴───────────────┬────────────────────┘        │
│                   │                      │                              │
│  ┌────────────────┴──────────────────────┴────────────────────┐        │
│  │               Checkpoint Manager                            │        │
│  │  ┌────────────┐  ┌──────────────┐  ┌──────────────────┐   │        │
│  │  │Save State  │  │Restore State │  │Expire Checkpoints│   │        │
│  │  └────────────┘  └──────────────┘  └──────────────────┘   │        │
│  └──────────────────────────────┬──────────────────────────────┘        │
└────────────────────────────────────┼─────────────────────────────────────┘
                                    │
┌────────────────────────────────────┼─────────────────────────────────────┐
│                      API Gateway Layer                                   │
│  ┌──────────────────────┴──────────────────────────────────────┐        │
│  │                   Resource Manager                           │        │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │        │
│  │  │ Rate Limiter │  │ Token Bucket │  │ Concurrency Ctrl│   │        │
│  │  └──────────────┘  └──────────────┘  └─────────────────┘   │        │
│  └───────────────────────────┬──────────────────────────────────┘        │
│  ┌───────────────────────────┴──────────────────────────────────┐        │
│  │                   Provider Registry                           │        │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │        │
│  │  │Health Track  │  │Circuit Break │  │Fallback Chains  │   │        │
│  │  └──────────────┘  └──────────────┘  └─────────────────┘   │        │
│  └─────────────────────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities and Interfaces

1. **Prompt Manager**
   - **Responsibility**: Dynamic loading and hierarchical assembly of XML prompts. Validates XML files and falls back to persona constants.
   - **Interfaces**: `load_runtime_contracts()`, `load_system_prompt()`, `validate_xml()`, `assemble_prompt()`, `get_load_order_verification()`

2. **Conversation Director**
   - **Responsibility**: Manages multi-turn dialogue state, token limits, history truncation, and contextual transitions.
   - **Interfaces**: `create_session()`, `add_turn()`, `get_history()`, `get_metadata()`, `transition_state()`, `should_truncate()`, `truncate_history()`, `cleanup_expired_sessions()`

3. **Pipeline Scheduler**
   - **Responsibility**: Orchestrates pipeline stages (Normalize → Breach_Check → Generation → Evaluation → Synthesis → Formatting) with state machine integration.
   - **Interfaces**: `execute_pipeline()`, `execute_stage()`, `execute_parallel_agents()`, `handle_stage_failure()`, `emit_stage_transition()`

4. **Runtime Engine**
   - **Responsibility**: Executes prompts enforcing contracts for security, streaming, and resources. Tracks execution metrics per agent and provider.
   - **Interfaces**: `register_contract()`, `execute_with_contracts()`, `validate_contracts()`, `track_execution_metrics()`, `get_metrics_report()`

5. **Execution Passport**
   - **Responsibility**: Tracks request identity, permissions, and execution state across the pipeline. Uses thread-safe mechanisms, UUID v4, and ISO 8601 timestamps.
   - **Interfaces**: `record_error()`, `record_warning()`, `update_stage()`, `add_agent_output()`, `add_checkpoint()`, `record_injection_attempt()`, `record_validation_failure()`, `to_dict()`

6. **Reasoning Graph**
   - **Responsibility**: Tracks epistemic failures, claims, and reasoning patterns. Generates semantic similarity search for failures.
   - **Interfaces**: `add_node()`, `add_edge()`, `find_similar_nodes()`, `record_failure_pattern()`, `get_failure_patterns()`, `expire_old_patterns()`, `get_graph_stats()`

7. **Claim Manager**
   - **Responsibility**: Extracts and validates factual claims from agent outputs to detect hallucinations.
   - **Interfaces**: `extract_claims()`, `classify_claim_type()`, `validate_claim()`, `store_claim()`, `get_unverified_claims()`, `track_claim_provenance()`

8. **Decision Engine**
   - **Responsibility**: Implements the Decision Gate Architecture (Breaker → Logician/Creative → Judge) with strict timing rules.
   - **Interfaces**: `execute_breaker_gate()`, `execute_generation_agents()`, `execute_judge_synthesis()`

9. **Streaming Manager**
   - **Responsibility**: Handles real-time Server-Sent Events (SSE) for frontend updates. Implements limits and buffer sizes.
   - **Interfaces**: `create_stream()`, `emit_event()`, `iter_events()`, `close_stream()`, `cleanup_stale_streams()`

10. **Provider Registry**
    - **Responsibility**: Tracks LLM provider capabilities and health status, applying circuit breaker and exponential backoff mechanisms.
    - **Interfaces**: `register_provider()`, `update_circuit_breaker()`, `calculate_health_status()`, `attempt_recovery()`, `get_health_metrics()`, `get_fallback_chain()`

11. **Resource Manager**
    - **Responsibility**: Monitors and enforces rate limits and concurrency limits per provider and per user using a token bucket approach.
    - **Interfaces**: `configure_provider_limit()`, `configure_user_limit()`, `acquire_resources()`, `queue_request()`, `get_resource_metrics()`, `adjust_limits_dynamic()`

12. **Checkpoint Manager**
    - **Responsibility**: Saves and restores pipeline states in persistent storage for failure recovery. Limits checkpoint sizes.
    - **Interfaces**: `save_checkpoint()`, `restore_checkpoint()`, `get_latest_checkpoint()`, `list_checkpoints()`, `expire_checkpoints()`, `delete_checkpoints()`

13. **State Machine**
    - **Responsibility**: Enforces legal pipeline transitions and triggers hooks (on_enter, on_exit).
    - **Interfaces**: `transition()`, `can_transition()`, `register_hook()`

14. **Memory Manager**
    - **Responsibility**: Computes context window capacity based on LLM limits and triggers history compression.
    - **Interfaces**: `track_tokens()`, `calculate_remaining_capacity()`, `should_compress()`, `compress_history()`, `get_context_metrics()`

15. **Security Validator**
    - **Responsibility**: Prevents prompt injection, scrubs secrets from logs, limits characters, and verifies inputs.
    - **Interfaces**: `validate_input()`, `detect_injection()`, `scrub_secrets()`, `escape_user_input()`, `separate_system_user_prompts()`

## Data Flows

**Request Lifecycle**
1. **Request Reception**: API Gateway receives `/query` request.
2. **ExecutionPassport Creation**: A unique UUID v4 is generated, initializing state and metadata.
3. **Security Validation**: `SecurityValidator` validates the query for length, character validity, and injection attempts.
4. **Pipeline Execution**: The `PipelineScheduler` guides the request through:
   - Normalize → Breach_Check → Generation → Evaluation → Synthesis → Formatting
5. **Component Updates**: At each stage, `ExecutionPassport` is updated with outputs, errors, checkpoints, and warnings.
6. **Response / Checkpoint**: Final metadata is logged, state is serialized to checkpoints, and the response is formulated and streamed via `StreamingManager`.

## Configuration Options

- **Rate Limits**: 
  - Provider Rate Limit: 100 requests/min.
  - User Rate Limit: 50 requests/min.
  - Global Concurrency: 100 requests.
- **Timeouts**:
  - Breaker Gate: 100ms.
  - Parallel Agents: 30 seconds.
  - Execution Limit: 300 seconds.
  - Checkpoint Save: 5 seconds.
  - Checkpoint Restore: 10 seconds.
- **Thresholds**:
  - Memory Truncation Threshold: 80% of Max Tokens.
  - Knowledge Absence Threshold: 0.3.
  - Provider Error Rate Degradation: 20%.
  - Provider Error Rate Dead: 50%.
- **Retention Periods**:
  - Checkpoints: Default 7 days (min 1 hour, max 30 days).
  - Reasoning Graph Patterns: 30 days.
  - Conversation Sessions: 24 hours.

## Error Handling

- **Fallback Strategies**: Configured via `ProviderRegistry` fallback chains if a primary LLM is degraded.
- **Retry Logic**: System features exponential backoff for recovering LLMs (Base 1.0s, Max 300.0s, Multiplier 2.0). Checkpoints support resuming pipelines without repeating earlier successes.
- **Circuit Breaker Behavior**: 
  - `CLOSED`: Normal operation.
  - `OPEN`: Triggered after 5 consecutive provider failures (blocks requests for 60 seconds).
  - `HALF_OPEN`: Allows 1 test request to check health. Restores to `CLOSED` after 3 consecutive successes.

## State Machine Diagram

```text
       ┌────────┐
       │  IDLE  │
       └────┬───┘
            │
      ┌─────▼──────┐
      │ NORMALIZING│
      └─────┬──────┘
            │
    ┌───────▼────────┐
    │ BREACH_CHECKING│
    └───────┬────────┘
            │
      ┌─────▼──────┐
      │ GENERATING │
      └─────┬──────┘
            │
      ┌─────▼──────┐
      │ EVALUATING │
      └─────┬──────┘
            │
     ┌──────▼───────┐
     │ SYNTHESIZING │
     └──────┬───────┘
            │
      ┌─────▼──────┐
      │ FORMATTING │
      └─────┬──────┘
            │
      ┌─────▼──────┐
      │ COMPLETED  │
      └────────────┘

[Note: All non-terminal states can transition directly to FAILED or ABORTED states if errors occur or knowledge absence is detected]
```

## Decision Engine Details

- **Breaker Gate**: Enforces a strict 100ms timeout for detecting if the system is completely lacking knowledge for a given query (Confidence < 0.3 or returning the sentinel string "KNOWLEDGE ABSENCE DETECTED"). If triggered, pipeline abortion begins within 10ms.
- **Parallel Generation**: Logician and Creative agents are executed concurrently with a strict timeout of 30 seconds.
- **Metrics Tracked**: `breaker_pass_rate`, `judge_agreement_rate` (judge validation score >= 7.0), and `synthesis_quality_avg`.
