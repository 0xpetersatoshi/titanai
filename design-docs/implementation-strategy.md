# TitanAI — Implementation Strategy

This document defines the phased implementation plan for the multi-tenant library catalog service. Each phase is
independently deployable and testable — you get a working system at the end of each phase, not just at the end.

---

## Dependency Graph

```
Phase 0 (Foundation)
    │
    ▼
Phase 1 (Tenants + Isolation)
    │
    ├──────────────────────┐
    ▼                      ▼
Phase 2 (Sync Ingestion)  Phase 6 (Reading Lists + PII)
    │
    ▼
Phase 3 (Retrieval + Search) ← MVP COMPLETE
    │
    ▼
Phase 4 (Background Jobs)
    │
    ├──────────┬───────────┐
    ▼          ▼           ▼
Phase 5    Phase 7     Phase 8
(Activity  (Auto-      (Version
 Log)       Refresh)    Mgmt)
               │
               └──────┐
                      ▼
                   Phase 9 (Noisy Neighbor Throttling)
```

**Critical path**: 0 → 1 → 2 → 3 (MVP) → 4 → 5/7/8

**Parallelizable**: Phase 6 is independent after Phase 1. Phases 5, 7, 8 are independent after Phase 4.

---

## Phase 0 — Project Foundation

_No user-facing functionality. Sets up everything needed to build on._

### Steps

1. **Add core dependencies** — FastAPI, uvicorn, httpx (async HTTP client), pydantic, pydantic-settings, aiosqlite
2. **Project structure** — Create the package layout:

   ```
   src/titanai/
     api/           # FastAPI routers
     db/            # Database connection, migrations, repositories
     services/      # Business logic
     models/        # Pydantic schemas (request/response)
     core/          # Config, constants, shared utilities
     workers/       # Background job system
   ```

3. **Configuration module** — Load settings from env vars (database path, PII secret key, worker count, OL rate limit,
   etc.) with Pydantic Settings. Fail fast on missing required vars.
4. **Database setup** — SQLite connection factory with WAL mode, `PRAGMA foreign_keys=ON`. Schema creation for all 8
   tables (tenants, books, book_versions, ingestion_jobs, activity_logs, reading_lists, reading_list_items,
   tenant_metrics).
5. **FastAPI app scaffold** — App factory with lifespan handler (startup/shutdown), router includes.
6. **Test infrastructure** — pytest setup with fixtures for test database (in-memory SQLite), async test client (httpx
   AsyncClient), and test tenant creation helper.

### Delivers

A running FastAPI app that starts, connects to SQLite, creates tables, and responds to a health check. Tests pass.

### FRs Covered

None directly — this is scaffolding.

---

## Phase 1 — Tenant Management & Isolation

_Foundation for every subsequent phase._

### Steps

1. **Tenant repository** — `create_tenant()`, `get_tenant()`, `list_tenants()`. All return Pydantic models.
2. **Tenant API routes** — `POST /tenants`, `GET /tenants`, `GET /tenants/{tenant_id}`.
3. **Tenant middleware** — `get_current_tenant` FastAPI dependency that validates tenant existence and returns
   `TenantContext`. Returns 404 for unknown tenant IDs.
4. **Tests** — Tenant CRUD works. Invalid tenant ID returns 404. Middleware injects context correctly.

### Delivers

Tenants can be created and looked up. The isolation dependency is ready for all subsequent routes.

### FRs Covered

- **FR-026**: Tenant isolation enforcement begins here.

---

## Phase 2 — Synchronous Catalog Ingestion

_Start with blocking ingestion to get the data pipeline right before adding async._

### Steps

1. **Open Library client** — Async HTTP client module using `httpx.AsyncClient`. Methods:
   - `search_by_author(author)` → list of work stubs
   - `search_by_subject(subject)` → list of work stubs
   - `get_work(work_id)` → full work details
   - `get_author(author_id)` → author name
   - Construct cover URL from `cover_i` field
   - Set `User-Agent` header per OL docs
2. **Record assembly logic** — Service that takes a search result, identifies missing fields, makes follow-up requests,
   and produces a complete book record.
3. **Book repository** — `create_book(tenant_id, ...)`, `get_book(tenant_id, book_id)`,
   `book_exists(tenant_id, ol_work_id)`. All queries include `WHERE tenant_id = ?`.
4. **Ingestion service** — Orchestrates: call OL → assemble records → deduplicate → store. Initially synchronous
   (blocking) — called directly from the route handler.
5. **Temporary sync route** — `POST /tenants/{tenant_id}/ingestion` that runs ingestion inline and returns results. This
   is a stepping stone replaced by the async job route in Phase 4.
6. **Tests** — Integration tests hitting live Open Library API for a known author with few works. Verify all fields
   populated. Verify deduplication (ingest twice, no duplicates). Cross-tenant isolation test.

### Delivers

Books can be ingested for a tenant from Open Library with complete records. The data pipeline works end-to-end.

### FRs Covered

- **FR-001**: Ingest by author or subject, scoped to tenant.
- **FR-002**: Assemble complete records from multiple endpoints.
- **FR-003**: Store with all required fields.
- **FR-004**: Deduplication by (tenant_id, ol_work_id).
- **FR-005**: Live Open Library API calls.

---

## Phase 3 — Catalog Retrieval & Search

_Depends on Phase 2 (needs data to query). Completes the MVP._

### Steps

1. **Book repository extensions** — `list_books(tenant_id, offset, limit, filters)`, `search_books(tenant_id, query)`.
   Filtering by author (JSON `LIKE`), subject (JSON `LIKE`), year range (`BETWEEN`). Keyword search via `LIKE` on title
   and authors.
2. **Pagination model** — Pydantic response model with `items`, `total`, `offset`, `limit`.
3. **API routes** — `GET /tenants/{tenant_id}/books` (query params: `q`, `author`, `subject`, `year_min`, `year_max`,
   `offset`, `limit`), `GET /tenants/{tenant_id}/books/{book_id}`.
4. **Tests** — Ingest known data, then: list with pagination, filter by each field, keyword search, single book detail.
   Cross-tenant isolation on all queries. 404 for book ID under wrong tenant.

### Delivers

Full catalog browsing and search. **Combined with Phase 2, this is the MVP** — ingest and retrieve books.

### FRs Covered

- **FR-006**: Paginated book listing.
- **FR-007**: Filter by author, subject, year range.
- **FR-008**: Keyword search on title and author.
- **FR-009**: Single-book detail endpoint.

---

## Phase 4 — Background Job System

_Converts synchronous ingestion to async. Core production concern._

### Steps

1. **Job repository** — `create_job(tenant_id, query_type, query_value)`, `claim_next_job()` (atomic SQL
   UPDATE...RETURNING), `update_progress(job_id, ...)`, `mark_completed(job_id)`, `mark_failed(job_id)`.
2. **Worker pool** — Async worker tasks started on app lifespan. Worker loop: claim job → execute ingestion → update
   progress. Global OL rate limiter (asyncio semaphore, 2 req/sec).
3. **Retry logic** — Per-request retries with exponential backoff (429 → Retry-After, 5xx → 1s/2s/4s, timeout → same as
   5xx). Per-work failure isolation (one bad record doesn't abort the job).
4. **Refactor ingestion route** — Replace sync `POST .../ingestion` with `POST .../ingestion/jobs` that inserts a job
   row and returns 202 with job ID. Move actual ingestion logic into the worker.
5. **Job status routes** — `GET .../ingestion/jobs`, `GET .../ingestion/jobs/{job_id}`.
6. **Stale job recovery** — On startup, reset `in_progress` → `queued`.
7. **Graceful shutdown** — Cancel workers with grace period on app shutdown.
8. **Tests** — Submit job, verify 202 with job ID. Poll status until completed. Verify books stored. Mock OL returning
   429/500 to test retry. Stale job recovery on restart.

### Delivers

Ingestion is fully async. API never blocks. Jobs are trackable with progress.

### FRs Covered

- **FR-017**: Async ingestion via background jobs.
- **FR-018**: Job status endpoint with progress.
- **FR-019**: Graceful handling of OL rate limits and timeouts.

---

## Phase 5 — Activity Log

_Depends on Phase 4 (jobs produce log entries)._

### Steps

1. **Activity log repository** — `create_log(...)`, `list_logs(tenant_id, offset, limit)`. Ordered by `created_at DESC`.
2. **Worker integration** — Write activity log entry when job reaches terminal state (already scaffolded in Phase 4's
   worker loop).
3. **API route** — `GET /tenants/{tenant_id}/ingestion/logs`.
4. **Tests** — Run ingestion, verify log entry with correct counts (fetched, succeeded, failed). Verify tenant isolation
   on logs. Verify reverse-chronological ordering and pagination.

### Delivers

Full observability into ingestion history.

### FRs Covered

- **FR-010**: Log every ingestion operation with counts, timestamps, errors.
- **FR-011**: Activity log API, tenant-scoped, reverse-chronological, paginated.

---

## Phase 6 — Reading List Submissions with PII Protection

_Independent of ingestion phases. Can be developed in parallel with Phases 2–5 after Phase 1._

### Steps

1. **PII hashing module** — Centralized `hash_email()`, `hash_name()` with HMAC-SHA256, input normalization (lowercase,
   strip whitespace), secret key loading from `TITANAI_PII_SECRET_KEY` env var. Startup validation: key present, minimum
   256 bits.
2. **Reading list repository** — `create_reading_list(...)`, `create_reading_list_items(...)`,
   `list_reading_lists(tenant_id, ...)`, `get_reading_list(tenant_id, list_id)`.
3. **Book resolution service** — Given a list of `{id, id_type}` entries, resolve each: work IDs checked against local
   catalog and/or OL, ISBNs resolved via `GET /isbn/{isbn}.json`. Return resolution status per book.
4. **API routes** — `POST /tenants/{tenant_id}/reading-lists`, `GET .../reading-lists`,
   `GET .../reading-lists/{list_id}`.
5. **Tests**:
   - Submit reading list, verify PII hashed (query DB directly, assert no plaintext).
   - Deterministic hashing (same email → same hash across submissions).
   - Normalization variants produce same hash.
   - ISBN resolution works.
   - Not-found books reported correctly in response.
   - PII absent from logs and API responses.
   - Missing secret key blocks startup.
   - Cross-tenant isolation.

### Delivers

Patrons can submit reading lists. PII is fully protected.

### FRs Covered

- **FR-012**: Accept reading list submissions with name, email, book IDs/ISBNs.
- **FR-013**: Irreversible PII hashing before persistence.
- **FR-014**: Deterministic email hashing for deduplication.
- **FR-015**: ISBN resolution via Open Library.
- **FR-016**: Response reports resolved vs. not-found books.

---

## Phase 7 — Automatic Refresh

_Depends on Phase 4 (job system)._

### Steps

1. **Refresh timer** — Periodic async task (started on app lifespan) that checks each tenant's staleness against
   `ingestion_refresh_hours` and creates auto-refresh jobs.
2. **Refresh deduplication** — Before creating a refresh job, check if an identical (tenant, query_type, query_value)
   job is already queued or in-progress. Skip if so.
3. **Track ingestion queries** — Query distinct (query_type, query_value) pairs from completed jobs per tenant to know
   what to refresh.
4. **Tests** — Set a short refresh interval, verify auto-refresh job is created. Verify `is_auto_refresh = 1` on the
   job. Verify no duplicate refresh jobs. Verify tenants with no prior ingestion are skipped.

### Delivers

Catalogs stay fresh automatically without manual intervention.

### FRs Covered

- **FR-020**: Automatic periodic re-ingestion.

---

## Phase 8 — Version Management

_Depends on Phases 2 and 4 (needs ingestion pipeline and re-ingestion via jobs)._

### Steps

1. **Version comparison logic** — Service that compares fetched metadata against current book record field-by-field.
   Detects changes and identifies regressions (field was non-null before, now null).
2. **Book version repository** — `create_version(book_id, ...)`, `list_versions(tenant_id, book_id)`,
   `get_version(tenant_id, book_id, version_id)`.
3. **Ingestion integration** — When a worker encounters an existing book during ingestion: run comparison → if changed,
   create version row with diff, update book row (preserving regressed fields), flag regressions. If unchanged, skip.
4. **API routes** — `GET .../books/{book_id}/versions`, `GET .../books/{book_id}/versions/{version_id}`.
5. **Tests** — Ingest a work, manually update the stored record to simulate changed upstream data, re-ingest, verify new
   version created with correct diff. Verify regression handling (field removed → old value preserved, regression
   flagged). Verify no version created when data unchanged. Verify version history endpoint returns all versions with
   diffs.

### Delivers

Full version history with regression protection.

### FRs Covered

- **FR-021**: Versioned records on metadata change.
- **FR-022**: Data regression handling — preserve prior values, flag regression.
- **FR-023**: Version history API with diffs.

---

## Phase 9 — Noisy Neighbor Throttling

_Depends on Phases 1 and 4. Best done last as it adds constraints on top of existing functionality._

### Steps

1. **Per-tenant API rate limiting** — Extend tenant middleware to check request count against `rate_limit_per_minute`
   using `tenant_metrics` table. Fixed-window counter. Return 429 with `Retry-After` when exceeded.
2. **Per-tenant job concurrency limit** — Enforce `MAX_CONCURRENT_JOBS_PER_TENANT` at submission time (429 if full) and
   in the fair-scheduling job claim query (tenants with fewer active jobs get priority).
3. **Metrics repository** — `increment_request_count(tenant_id)`, `get_metrics(tenant_id)`, `get_all_metrics()`. Reset
   window counter when window expires.
4. **API routes** — `GET /tenants/{tenant_id}/metrics`, `GET /metrics`.
5. **Tests** — Exceed API rate limit, verify 429. Exceed job concurrency limit, verify 429. Verify fair scheduling
   (tenant with fewer active jobs gets priority over one with more). Verify metrics endpoint returns correct per-tenant
   counts.

### Delivers

Multi-tenant fairness with visibility into resource consumption.

### FRs Covered

- **FR-024**: Per-tenant rate limiting.
- **FR-025**: Per-tenant resource consumption metrics.

---

## Phase Summary

| Phase | Tier | Delivers                             | Depends On | FRs        |
| ----- | ---- | ------------------------------------ | ---------- | ---------- |
| 0     | —    | Project foundation, DB, test infra   | —          | —          |
| 1     | —    | Tenant CRUD + isolation middleware   | 0          | FR-026     |
| 2     | T1   | Sync ingestion from Open Library     | 1          | FR-001–005 |
| 3     | T1   | Catalog retrieval & search (**MVP**) | 2          | FR-006–009 |
| 4     | T2   | Background job system                | 2          | FR-017–019 |
| 5     | T1   | Activity log                         | 4          | FR-010–011 |
| 6     | T2   | Reading lists + PII protection       | 1          | FR-012–016 |
| 7     | T2   | Automatic catalog refresh            | 4          | FR-020     |
| 8     | T3   | Version management                   | 2, 4       | FR-021–023 |
| 9     | T3   | Noisy neighbor throttling            | 1, 4       | FR-024–025 |
