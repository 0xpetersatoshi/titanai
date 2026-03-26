# Research: Multi-Tenant Library Catalog Service

**Phase 0 Output** | **Date**: 2026-03-25

All technical context was provided upfront — no NEEDS CLARIFICATION items. This document records the key decisions and
their rationale.

## Decision 1: SQLite over PostgreSQL

**Decision**: SQLite with WAL mode via aiosqlite
**Rationale**: Zero-infrastructure deployment — single `uv run uvicorn` starts the entire service. WAL mode enables
concurrent reads during writes. The 3-worker job pool stays within SQLite's single-writer constraint.
**Alternatives rejected**: PostgreSQL (requires separate server, connection pooling — overkill for single-deployment
model), DuckDB (write-optimized analytics, not suited for concurrent OLTP).

## Decision 2: In-Process Job Queue over Celery/Redis

**Decision**: asyncio.Task workers polling the `ingestion_jobs` table
**Rationale**: No external broker needed. The job table IS the queue — atomic claiming via SQL `UPDATE...RETURNING`.
Workers are managed by FastAPI's lifespan handler. Matches SQLite's single-process model.
**Alternatives rejected**: Celery + Redis (heavyweight, requires Redis server), arq (Redis-backed), Dramatiq (still
needs a broker). All add infrastructure complexity for a single-deployment service.

## Decision 3: HMAC-SHA256 over Plain SHA-256 for PII

**Decision**: HMAC-SHA256 with server-side secret key
**Rationale**: Email addresses are low-entropy — `jane@gmail.com` variants are trivially reversible via rainbow tables
with plain SHA-256. HMAC adds a secret key that makes precomputation infeasible while preserving deterministic hashing
for deduplication.
**Alternatives rejected**: Plain SHA-256 (vulnerable to rainbow tables), bcrypt/scrypt (non-deterministic — can't
deduplicate), AES encryption (reversible — violates "irreversible" requirement).

## Decision 4: JSON Columns over Junction Tables

**Decision**: Store `authors` and `subjects` as JSON arrays in TEXT columns
**Rationale**: Simpler schema (no `book_authors`/`book_subjects` junction tables). SQLite's `json_each()` and
`json_extract()` support filtering. Query patterns are substring matches, not relational joins. Can be refactored to
junction tables later if needed.
**Alternatives rejected**: Normalized junction tables (more complex schema, more joins, marginal benefit for the query
patterns used here).

## Decision 5: Tenant ID in Path over Header

**Decision**: `/tenants/{tenant_id}/...` URL prefix
**Rationale**: Self-describing URLs visible in logs and monitoring. Missing tenant = 404, not silent default. No
ambiguity about which tenant is being accessed. Matches RESTful resource modeling.
**Alternatives rejected**: `X-Tenant-ID` header (invisible in URLs, easy to omit silently), JWT claims (adds auth
complexity beyond scope).

## Decision 6: httpx over aiohttp for HTTP Client

**Decision**: httpx AsyncClient
**Rationale**: Modern async HTTP client with requests-compatible API. Built-in timeout, retry, and redirect handling.
First-class `AsyncClient` with connection pooling. Also used for test client (`httpx.AsyncClient` with ASGI transport).
**Alternatives rejected**: aiohttp (different API style, separate test client needed), urllib3 (sync only).

## Decision 7: Open Library Rate Limiting Strategy

**Decision**: Global asyncio.Semaphore at 2 req/sec shared across all workers + User-Agent header
**Rationale**: Open Library allows ~3 req/sec with User-Agent identification. Setting to 2 provides safety margin.
Shared semaphore prevents workers from collectively exceeding the limit. Per-request retry with exponential backoff
handles 429/5xx responses.
**Alternatives rejected**: Per-worker rate limiting (workers collectively exceed limit), no rate limiting (get
blocked/banned by Open Library).

## Decision 8: Fair Scheduling for Multi-Tenant Job Queue

**Decision**: SQL-based fair scheduling — ORDER BY active job count per tenant ASC, then FIFO
**Rationale**: Tenants with fewer active jobs get priority. Combined with per-tenant concurrent job limit (max 2), this
prevents any single tenant from monopolizing the worker pool. No external scheduler needed.
**Alternatives rejected**: Simple FIFO (unfair — first tenant to submit many jobs blocks others), round-robin (more
complex, requires tracking turn state).
