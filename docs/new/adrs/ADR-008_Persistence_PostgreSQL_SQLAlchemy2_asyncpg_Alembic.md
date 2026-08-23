# ADR-008: Persistence Stack — PostgreSQL + SQLAlchemy 2 + asyncpg + Alembic

- **Status:** Accepted
- **Date:** 2026-07-13
- **Deciders:** CALIENNE architecture working group
- **Related RFCs:** RFC-004

## Context

The Experience DB was originally specified as SQLite for v1. As the
architecture grew, three things changed the trade-off:

1. **Two physical tables with different lifecycles** —
   `experience_operational` (high-write, short retention) and
   `experience_learning` (read-heavy, long retention). SQLite's
   single-writer constraint becomes a real bottleneck on the
   operational table under sustained load.
2. **A vector memory layer is on the roadmap** (RFC-004, Phase 3).
   SQLite's vector extensions (`sqlite-vss`) are fragile and not
   production-grade. `pgvector` is.
3. **The repo already has `migrations/` and `alembic.ini`** — the
   Alembic toolchain is already in the stack.

A persistence stack is not just "which database"; it is the database
plus the driver, the ORM, the migration tool, and the operational
model. Choosing PostgreSQL without a coherent stack leaves the
driver/ORM/migration questions open and creates drift risk where
every contributor picks differently.

## Decision

CALIENNE's persistence stack for v1 is **PostgreSQL + SQLAlchemy 2
(async) + `asyncpg` + Alembic**. `pgvector` is reserved for v2.

- **PostgreSQL** — the database. Multi-writer; supports the two-table
  write/read split cleanly; production-grade; has `pgvector` when we
  need it.
- **SQLAlchemy 2.0 async** — the ORM / query layer. Async-native,
  matches the async-first runtime (ADR-002); provides a repository
  interface that hides raw SQL (per `plan.md` invariant viii).
- **`asyncpg`** — the driver. Non-blocking I/O matches the orchestrator
  loop's requirements.
- **Alembic** — schema migrations. Already in the repo; provides
  structured version control for database state.
- **`pgvector`** — installed but unused in v1. Semantic memory lights
  up in v2 against the same `experience_learning` table.

### Test isolation

Tests use **Testcontainers** (Python) to spin up a disposable
PostgreSQL per test session. No shared database, no schema isolation,
no SQLite shim. Justification:

- Isolated, deterministic, reproducible.
- Identical PostgreSQL engine match for every worker thread.
- Zero test flakiness from cross-test state pollution.
- CI-friendly; zero developer setup.

### Operational model

- **Repository interfaces only.** No orchestration module talks
  directly to SQL. Every persistence boundary goes through an
  `ExperienceRepository`, `ReplayRepository`, etc. (per
  `plan.md` invariant viii).
- **Connection pool** owned by the `ResourceManager` (with CPU /
  memory limits), not by individual repositories.
- **Migrations are additive-first.** Alembic migrations prefer
  additive column adds + backfills over destructive in-place changes;
  destructive changes are gated by a `RFC-004` migration plan.

## Consequences

Easier:

- Async-native I/O matches the orchestrator loop; no thread-bridge
  seam.
- Future multi-user support, Alembic migrations, and pgvector
  integration are aligned from day one.
- Two physical tables (`experience_operational` +
  `experience_learning`) prevent write-lock contention on the SQLite
  engine and ensure optimal indexing.
- Repository interfaces make the persistence layer swappable for
  tests and future stack changes.

Harder:

- Requires a running PostgreSQL for local dev. Mitigation:
  `docker-compose.yml` with a `postgres:16` service.
- CI requires Docker. Acceptable; Testcontainers handles this
  cleanly.
- Connection-pool tuning is a real concern under load. Mitigation:
  bounded pool size in `ResourceManager`; metrics in the
  `resources.*` namespace surface pool saturation.
- Sync-to-async migration of any existing SQLite-touching code.
  Mitigation: the existing `tests/test_database_repair.py` and
  `tests/test_crit003_checkpoint_db.py` are exercised against the
  new stack first to surface migration friction early.

## Alternatives Considered

- **SQLite.** Rejected: single-writer bottleneck on the operational
  table; `sqlite-vss` is fragile; requires a second migration when
  vector memory lights up.
- **PostgreSQL + psycopg3 async.** Rejected: `asyncpg` is faster
  for the use case (raw async insert/select) and has a cleaner
  SQLAlchemy 2 async story.
- **PostgreSQL + raw asyncpg (no ORM).** Rejected: loses the
  repository pattern, makes schema migrations harder to reason
  about, and pushes schema definition into Python code.
- **DynamoDB / Firestore / other NoSQL.** Rejected: the data is
  relational; the two-table split is fundamentally relational; loses
  SQL tooling for offline analysis.
- **Redis-only.** Rejected: experience data is durable and
  queryable; Redis is a cache, not a store of record.

## Supersedes

None.
