# TitanAI — Implementation Strategy

Each phase is independently deployable and testable. Critical path: 0 → 1 → 2 → 3 (MVP) → 4 → 5/7/8.

## Dependency Graph

```
Phase 0 (Foundation)
    → Phase 1 (Tenants + Isolation)
        → Phase 2 (Sync Ingestion)  |  Phase 6 (Reading Lists + PII) [parallel]
            → Phase 3 (Retrieval + Search) ← MVP
                → Phase 4 (Background Jobs)
                    → Phase 5 (Activity Log)  |  Phase 7 (Auto-Refresh)  |  Phase 8 (Version Mgmt) [parallel]
                        → Phase 9 (Noisy Neighbor Throttling)
```

## Phase 0 — Project Foundation

- Add dependencies: FastAPI, uvicorn, httpx, pydantic, pydantic-settings, aiosqlite
- Create package layout: `api/`, `db/`, `services/`, `models/`, `core/`, `workers/`
- Configuration module (Pydantic Settings, env vars, fail-fast validation)
- Database setup (SQLite + WAL mode, `PRAGMA foreign_keys=ON`, all 8 tables)
- FastAPI app scaffold with lifespan handler
- Test infrastructure (pytest, in-memory SQLite, async test client, tenant helper)

## Phase 1 — Tenant Management & Isolation (FR-026)

- Tenant repository: `create_tenant()`, `get_tenant()`, `list_tenants()`
- API routes: `POST /tenants`, `GET /tenants`, `GET /tenants/{tenant_id}`
- `get_current_tenant` dependency (validates existence, injects TenantContext, returns 404)
- Tests: CRUD, invalid tenant 404, middleware injection

## Phase 2 — Synchronous Catalog Ingestion (FR-001–005)

- Open Library client: search by author/subject, get work/author details, cover URLs, User-Agent header
- Record assembly service (follow-up requests for missing fields)
- Book repository with tenant-scoped queries
- Ingestion service: OL → assemble → deduplicate → store
- Temporary sync route (`POST .../ingestion`) — replaced in Phase 4
- Tests: live OL integration, field completeness, deduplication, cross-tenant isolation

## Phase 3 — Catalog Retrieval & Search (FR-006–009) — MVP

- Book repository extensions: list/filter/search with pagination
- Filtering: author (JSON LIKE), subject (JSON LIKE), year range (BETWEEN), keyword search
- API routes: `GET .../books` (query params), `GET .../books/{book_id}`
- Tests: pagination, each filter type, keyword search, single detail, cross-tenant 404

## Phase 4 — Background Job System (FR-017–019)

- Job repository with atomic claiming (SQL UPDATE...RETURNING)
- Async worker pool (3 tasks on app lifespan), global OL rate limiter (asyncio semaphore)
- Retry logic: 429 → Retry-After, 5xx → exponential backoff, per-work failure isolation
- Replace sync route with `POST .../ingestion/jobs` → 202 + job ID
- Job status routes: `GET .../ingestion/jobs`, `GET .../ingestion/jobs/{job_id}`
- Stale job recovery on startup, graceful shutdown with grace period
- Tests: submit/poll/verify, retry on 429/500, stale recovery

## Phase 5 — Activity Log (FR-010–011)

- Activity log repository: `create_log()`, `list_logs()` (reverse chronological)
- Worker integration: write log entry on job completion
- API route: `GET .../ingestion/logs`
- Tests: log entry counts, tenant isolation, ordering, pagination

## Phase 6 — Reading Lists + PII (FR-012–016) — parallel after Phase 1

- PII hashing module: HMAC-SHA256, normalization, secret key validation at startup
- Reading list repository: create, list, get (tenant-scoped)
- Book resolution service: work IDs against local catalog/OL, ISBNs via `/isbn/{isbn}.json`
- API routes: `POST .../reading-lists`, `GET .../reading-lists`, `GET .../reading-lists/{list_id}`
- Tests: no plaintext in DB, deterministic hashing, normalization, ISBN resolution, PII not in logs/responses

## Phase 7 — Automatic Refresh (FR-020)

- Periodic async task checking tenant staleness against `ingestion_refresh_hours`
- Re-create jobs for previously completed (query_type, query_value) pairs
- Deduplication: skip if identical job already queued/in-progress
- Tests: auto-refresh job creation, `is_auto_refresh` flag, no duplicates, skip tenants with no history

## Phase 8 — Version Management (FR-021–023)

- Version comparison service: field-by-field diff, regression detection (non-null → null)
- Book version repository: create, list, get versions
- Ingestion integration: on existing book → compare → create version if changed, preserve regressed fields
- API routes: `GET .../books/{book_id}/versions`, `GET .../books/{book_id}/versions/{version_id}`
- Tests: version creation on change, regression handling, no version on unchanged, version history endpoint

## Phase 9 — Noisy Neighbor Throttling (FR-024–025)

- Per-tenant API rate limiting via middleware (fixed-window counter, 429 + Retry-After)
- Per-tenant job concurrency limit at submission + fair-scheduling in claim query
- Metrics repository: increment, get per-tenant, get aggregate
- API routes: `GET .../metrics`, `GET /metrics`
- Tests: rate limit 429, job limit 429, fair scheduling priority, metrics accuracy

## Phase Summary

| Phase | Delivers                             | Depends On | FRs        |
| ----- | ------------------------------------ | ---------- | ---------- |
| 0     | Project foundation, DB, test infra   | —          | —          |
| 1     | Tenant CRUD + isolation middleware   | 0          | FR-026     |
| 2     | Sync ingestion from Open Library     | 1          | FR-001–005 |
| 3     | Catalog retrieval & search (**MVP**) | 2          | FR-006–009 |
| 4     | Background job system                | 2          | FR-017–019 |
| 5     | Activity log                         | 4          | FR-010–011 |
| 6     | Reading lists + PII protection       | 1          | FR-012–016 |
| 7     | Automatic catalog refresh            | 4          | FR-020     |
| 8     | Version management                   | 2, 4       | FR-021–023 |
| 9     | Noisy neighbor throttling            | 1, 4       | FR-024–025 |
