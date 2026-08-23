# ADR-002: Async-First Event Loop

- **Status:** Accepted
- **Date:** 2026-07-13
- **Deciders:** CALIENNE architecture working group
- **Related RFCs:** RFC-002, RFC-003

## Context

CALIENNE's orchestrator manages multiple parallel I/O-bound operations
(RAG vector searches, concurrent agent calls, multi-judge consensus
matrices, web search, vector DB calls, streaming responses, repair loops,
timeouts, cancellations). Bridging a sync-first execution manager with
an async scheduler via thread-pool executors leads to context-switching
overhead, edge-case race conditions, and thread-pool exhaustion under
load. Retrofitting async after the fact is more expensive than adopting
it now.

## Decision

Every orchestrator component is **async** (`asyncio` natively throughout
the runtime). The main runtime, planner, scheduler, execution manager,
resource manager, memory, RAG, and consensus all run inside a single
event loop. Provider boundaries that rely on synchronous third-party SDKs
are wrapped:

```python
result = await asyncio.to_thread(sync_provider.generate, prompt)
```

If the provider is already async-native, it is awaited directly.

The event-driven scheduler is the only consumer of the ready-set. Worker
coroutines pull from the ready-set via `asyncio.Condition`. The
concurrency cap is a semaphore sourced from the `ResourceManager`; it is
never hardcoded.

Async DAG trap rules (see RFC-003):

- The scheduler is a long-lived task; never a function that `await`s the
  whole graph in a wave loop.
- No blocking sync LLM client calls inside the loop.
- On dependency failure, cancel in-flight workers for the branch and
  emit `NodeCancelled`.
- Telemetry, streaming SSE writes, and health checks run on their own
  coroutines and never queue behind LLM calls.

## Consequences

Easier:

- Event-driven scheduler (P2-6) becomes a natural fit.
- True parallel I/O for RAG, consensus, multi-judge, and streaming.
- Cancellation, timeout propagation, and bounded backpressure work the
  way asyncio expects.
- Replay (RFC-004) can replay the event stream deterministically.

Harder:

- Sync provider SDKs require `asyncio.to_thread` wrappers everywhere.
- Tests that previously used `time.sleep` must use `asyncio.sleep` or
  inject a fake clock.
- A naïve `for n in ready: await run(n)` will block the event loop on
  the slowest sibling and starve sibling work. Mitigation: per-worker
  coroutines + `asyncio.Condition`.

## Alternatives Considered

- **Sync-first runtime with async islands.** Rejected: a sync-first
  execution manager cannot naturally drive an event-driven scheduler;
  the seam would be a thread pool and would be the first thing to
  exhaust under load.
- **Curio / Trio.** Rejected: asyncio is the de facto Python standard;
  the entire ecosystem (httpx, aiohttp, asyncpg, SQLAlchemy 2 async)
  targets it.
- **Per-call threading model.** Rejected: the same starvation
  pathologies as sync-first, with worse observability.
