# Tasks: Multi-Tenant Library Catalog Service

**Input**: Design documents from `/specs/001-multi-tenant-catalog/`
**Prerequisites**: plan.md, spec.md, data-model.md, contracts/api.md, research.md, quickstart.md

**Tests**: Included — the constitution and spec require tests for tenant isolation, PII, and all features.

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Exact file paths included in every task description

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, dependencies, and basic structure

- [ ] T001 Add core dependencies to pyproject.toml: fastapi, uvicorn, httpx, pydantic, pydantic-settings, aiosqlite, ruff, pytest, pytest-asyncio
- [ ] T002 Create package directory structure under src/titanai/: api/, db/repositories/, services/, models/, core/, workers/
- [ ] T003 [P] Implement configuration module with Pydantic Settings in src/titanai/core/config.py — load all env vars (TITANAI_PII_SECRET_KEY, TITANAI_DB_PATH, WORKER_COUNT, OL_RATE_LIMIT_PER_SECOND, etc.) with defaults and startup validation (fail if PII key missing or < 32 bytes)
- [ ] T004 [P] Create pagination response model in src/titanai/models/pagination.py — generic PaginatedResponse with items, total, offset, limit fields
- [ ] T005 Implement SQLite connection factory in src/titanai/db/connection.py — async context manager, WAL mode, PRAGMA foreign_keys=ON, configurable DB path
- [ ] T006 Implement database schema DDL in src/titanai/db/schema.py — CREATE TABLE for all 8 tables (tenants, books, book_versions, ingestion_jobs, activity_logs, reading_lists, reading_list_items, tenant_metrics) with constraints, indexes, and unique constraints per data-model.md
- [ ] T007 Create FastAPI app factory with lifespan handler in src/titanai/main.py — startup creates DB tables, shutdown placeholder for workers, include all routers, health check endpoint
- [ ] T008 [P] Create Makefile with `run` target (`uv run uvicorn titanai.main:app --reload`) and `test` target (`uv run pytest`)
- [ ] T009 Setup test infrastructure in tests/conftest.py — fixtures for in-memory SQLite test DB, async httpx test client (ASGI transport), test tenant creation helper, TITANAI_PII_SECRET_KEY env override

---

## Phase 2: Foundational (Tenant Management & Isolation)

**Purpose**: Tenant CRUD and isolation middleware — MUST complete before any user story

**CRITICAL**: No user story work can begin until this phase is complete

- [ ] T010 [P] Create Tenant Pydantic models in src/titanai/models/tenants.py — TenantCreate (name, slug), TenantResponse (all fields), TenantList (paginated)
- [ ] T011 Implement tenant repository in src/titanai/db/repositories/tenants.py — create_tenant(), get_tenant(), list_tenants() with Pydantic model returns
- [ ] T012 Implement get_current_tenant dependency in src/titanai/api/dependencies.py — validate tenant_id exists via repository, return TenantContext (id + config), 404 if not found
- [ ] T013 Implement tenant API routes in src/titanai/api/tenants.py — POST /tenants (201), GET /tenants (paginated), GET /tenants/{tenant_id} (404 if missing)
- [ ] T014 Write tenant tests in tests/test_tenants.py — CRUD operations, invalid tenant returns 404, duplicate name/slug returns 422, middleware injects TenantContext correctly

**Checkpoint**: Tenants can be created and validated. Isolation dependency is ready for all subsequent routes.

---

## Phase 3: User Story 1 — Catalog Ingestion by Author or Subject (Priority: P1) MVP

**Goal**: Ingest books from Open Library by author/subject, scoped to a tenant, with complete records and deduplication.

**Independent Test**: Trigger ingestion for "Octavia Butler" scoped to a test tenant, verify stored records have all required fields, verify dedup on second run, verify cross-tenant isolation.

### Implementation for User Story 1

- [ ] T015 [P] [US1] Create Book Pydantic models in src/titanai/models/books.py — BookResponse (all fields from data-model), BookList (paginated)
- [ ] T016 [P] [US1] Create IngestionJob Pydantic models in src/titanai/models/ingestion.py — IngestionJobCreate (query_type, query_value), IngestionJobResponse (all fields), IngestionJobList (paginated)
- [ ] T017 [US1] Implement Open Library client in src/titanai/services/openlibrary.py — async httpx client with: search_by_author(author), search_by_subject(subject), get_work(work_id), get_author(author_id), construct_cover_url(cover_i). Set User-Agent header. Defensive parsing (every field optional). Global rate limiter (asyncio.Semaphore at OL_RATE_LIMIT_PER_SECOND)
- [ ] T018 [US1] Implement book repository in src/titanai/db/repositories/books.py — create_book(tenant_id, ...), get_book(tenant_id, book_id), book_exists(tenant_id, ol_work_id). All queries include WHERE tenant_id = ?. UNIQUE(tenant_id, ol_work_id) handles dedup.
- [ ] T019 [US1] Implement ingestion service in src/titanai/services/ingestion.py — orchestrates: call OL client → for each work, check dedup via book_exists → assemble complete record (follow-up requests for missing fields) → store via repository → return counts (succeeded, failed). Handles partial failures per-work.
- [ ] T020 [US1] Implement temporary synchronous ingestion route in src/titanai/api/ingestion.py — POST /tenants/{tenant_id}/ingestion (sync, blocking) that calls ingestion service directly and returns results. This is a stepping stone replaced by async job route in US5.
- [ ] T021 [US1] Write ingestion tests in tests/test_ingestion.py — test with live OL API for known author with few works, verify all fields populated (title, authors, first_publish_year, subjects, cover_image_url nullable), verify dedup (ingest twice → no duplicates), verify cross-tenant isolation (tenant B sees nothing from tenant A)

**Checkpoint**: Books can be ingested from Open Library with complete records. Data pipeline works end-to-end. MVP data layer is functional.

---

## Phase 4: User Story 2 — Catalog Retrieval and Search (Priority: P1) MVP

**Goal**: Browse and search a tenant's catalog with pagination, filtering, and keyword search.

**Independent Test**: After ingesting books, query list endpoint with various filters, keyword search, pagination, and single book detail. Verify tenant isolation on all queries.

### Implementation for User Story 2

- [ ] T022 [US2] Extend book repository in src/titanai/db/repositories/books.py — add list_books(tenant_id, offset, limit, filters) with: author filter (JSON LIKE on authors column), subject filter (JSON LIKE on subjects column), year range (BETWEEN on first_publish_year), keyword search (LIKE on title and authors, case-insensitive). Return total count for pagination.
- [ ] T023 [US2] Implement book API routes in src/titanai/api/books.py — GET /tenants/{tenant_id}/books (query params: q, author, subject, year_min, year_max, offset, limit), GET /tenants/{tenant_id}/books/{book_id} (404 if not found or wrong tenant)
- [ ] T024 [US2] Write catalog retrieval tests in tests/test_books.py — list with pagination (verify items, total, offset, limit), filter by each field (author, subject, year range), keyword search, single book detail, cross-tenant isolation (book under tenant A, request under tenant B → 404)

**Checkpoint**: Full catalog browsing and search. Combined with US1, this is the MVP — ingest and retrieve books.

---

## Phase 5: User Story 5 — Background Ingestion with Job Queue (Priority: P2)

**Goal**: Convert synchronous ingestion to async background jobs with progress tracking, retries, and automatic refresh.

**Independent Test**: Submit ingestion request, verify 202 with job ID, poll status until completed, verify books stored. Test retry on simulated OL errors. Test stale job recovery.

**Note**: US5 is implemented before US3/US4 because it replaces the sync ingestion route from US1 and is required infrastructure for activity logging (US3).

### Implementation for User Story 5

- [ ] T025 [US5] Implement ingestion job repository in src/titanai/db/repositories/ingestion_jobs.py — create_job(tenant_id, query_type, query_value), claim_next_job() with atomic SQL UPDATE...RETURNING and fair scheduling (ORDER BY active count per tenant ASC, then created_at), update_progress(job_id, ...), mark_completed(job_id), mark_failed(job_id), list_jobs(tenant_id, status_filter, offset, limit), get_job(tenant_id, job_id)
- [ ] T026 [US5] Implement worker pool in src/titanai/workers/pool.py — start N async worker tasks on app startup (lifespan), worker loop: claim job → execute ingestion → update progress. Graceful shutdown with 30s grace period. Stale job recovery on startup (reset in_progress → queued).
- [ ] T027 [US5] Implement job execution logic in src/titanai/workers/ingestion.py — wraps ingestion service with per-request retry (429 → Retry-After, 5xx → exponential backoff 1s/2s/4s, max 3 retries). Per-work failure isolation. Updates job progress after each work.
- [ ] T028 [US5] Refactor ingestion routes in src/titanai/api/ingestion.py — replace sync POST /tenants/{tenant_id}/ingestion with POST /tenants/{tenant_id}/ingestion/jobs (returns 202 + job), GET /tenants/{tenant_id}/ingestion/jobs (list with status filter), GET /tenants/{tenant_id}/ingestion/jobs/{job_id} (progress/status)
- [ ] T029 [US5] Implement automatic refresh timer in src/titanai/workers/refresh.py — periodic async task (every REFRESH_CHECK_INTERVAL_MINUTES) checks tenant staleness against ingestion_refresh_hours, re-creates jobs for previously completed (query_type, query_value) pairs with is_auto_refresh=1, skip if identical job already queued/in-progress
- [ ] T030 [US5] Integrate worker pool with FastAPI lifespan in src/titanai/main.py — start workers and refresh timer on startup, cancel on shutdown
- [ ] T031 [US5] Write background job tests in tests/test_ingestion.py — submit job verify 202 with job ID, poll status until completed, verify books stored, verify stale job recovery on restart (mock restart), verify auto-refresh creates jobs

**Checkpoint**: Ingestion is fully async. API never blocks. Jobs trackable with progress. Automatic refresh works.

---

## Phase 6: User Story 3 — Ingestion Activity Log (Priority: P2)

**Goal**: Audit log of all ingestion operations with counts, timestamps, and errors, queryable via API.

**Independent Test**: Run ingestion jobs (some with partial failures), query activity log endpoint, verify entries have correct counts and are tenant-scoped.

### Implementation for User Story 3

- [ ] T032 [P] [US3] Create ActivityLogEntry Pydantic models in src/titanai/models/ingestion.py — ActivityLogResponse (all fields), ActivityLogList (paginated)
- [ ] T033 [US3] Implement activity log repository in src/titanai/db/repositories/activity_logs.py — create_log(tenant_id, job_id, query_type, query_value, total_fetched, succeeded, failed, errors), list_logs(tenant_id, offset, limit) ordered by created_at DESC
- [ ] T034 [US3] Integrate activity log writing into worker job completion in src/titanai/workers/ingestion.py — write log entry when job reaches terminal state (completed or failed) with denormalized fields from job
- [ ] T035 [US3] Add activity log API route in src/titanai/api/ingestion.py — GET /tenants/{tenant_id}/ingestion/logs (paginated, most-recent-first)
- [ ] T036 [US3] Write activity log tests in tests/test_activity_logs.py — verify log entry created after ingestion with correct counts (fetched, succeeded, failed), verify reverse-chronological ordering, verify pagination, verify tenant isolation

**Checkpoint**: Full observability into ingestion history. Staff can audit all operations.

---

## Phase 7: User Story 4 — Reading List Submissions with PII Protection (Priority: P2)

**Goal**: Patrons submit reading lists with name/email. PII is HMAC-SHA256 hashed before storage. ISBN resolution via OL.

**Independent Test**: Submit reading list with known PII, query DB directly to verify no plaintext, verify deterministic hashing, verify ISBN resolution, verify cross-tenant isolation.

### Implementation for User Story 4

- [ ] T037 [P] [US4] Implement PII hashing module in src/titanai/core/pii.py — hash_email(plaintext) and hash_name(plaintext) using HMAC-SHA256. Normalize: email → lowercase + strip whitespace, name → lowercase + strip + collapse internal whitespace. Load key from TITANAI_PII_SECRET_KEY. Never log/cache/retain plaintext.
- [ ] T038 [P] [US4] Create ReadingList Pydantic models in src/titanai/models/reading_lists.py — ReadingListCreate (patron_name, patron_email, books: list of {id, id_type}), ReadingListResponse (id, created_at, books with resolution status — NO patron name/email echoed), ReadingListItem models
- [ ] T039 [US4] Implement reading list repository in src/titanai/db/repositories/reading_lists.py — create_reading_list(tenant_id, patron_name_hash, patron_email_hash), create_reading_list_items(reading_list_id, items), list_reading_lists(tenant_id, offset, limit), get_reading_list(tenant_id, list_id) with items
- [ ] T040 [US4] Implement book resolution service in src/titanai/services/reading_lists.py — for each submitted book: if work_id → check local catalog + OL, if isbn → resolve via GET /isbn/{isbn}.json on OL. Return resolution status per book. Hash PII via pii module before passing to repository.
- [ ] T041 [US4] Implement reading list API routes in src/titanai/api/reading_lists.py — POST /tenants/{tenant_id}/reading-lists (201, response omits PII), GET /tenants/{tenant_id}/reading-lists (paginated, hashes only), GET /tenants/{tenant_id}/reading-lists/{list_id}. Validate at least one book in submission (422 if empty).
- [ ] T042 [US4] Write PII tests in tests/test_pii.py — no plaintext in DB (submit list, query DB directly), deterministic hashing (same email → same hash), normalization variants produce same hash ("JANE@example.com" = " jane@example.com "), PII not in logs (capture log output), PII not in API responses, missing secret key fails startup
- [ ] T043 [US4] Write reading list tests in tests/test_reading_lists.py — submit with work IDs and ISBNs, verify resolution status in response, verify not-found books reported, verify cross-tenant isolation

**Checkpoint**: Patrons can submit reading lists. PII is fully protected. ISBN resolution works.

---

## Phase 8: User Story 6 — Work Version Management (Priority: P3)

**Goal**: Track metadata changes on re-ingestion with version history, diffs, and regression handling.

**Independent Test**: Ingest a work, modify stored data to simulate upstream change, re-ingest, verify new version with diff. Test regression handling (field removed → old value preserved).

### Implementation for User Story 6

- [ ] T044 [P] [US6] Create BookVersion Pydantic models in src/titanai/models/books.py — BookVersionResponse (all fields including diff, has_regression, regression_fields), BookVersionList (paginated)
- [ ] T045 [US6] Implement book version repository in src/titanai/db/repositories/book_versions.py — create_version(book_id, version_number, snapshot_fields, diff, has_regression, regression_fields), list_versions(tenant_id, book_id, offset, limit), get_version(tenant_id, book_id, version_id)
- [ ] T046 [US6] Implement version comparison service in src/titanai/services/versions.py — compare fetched metadata against current book record field-by-field, detect changes, identify regressions (field was non-null → now null). Return diff object and regression flags.
- [ ] T047 [US6] Integrate version management into ingestion worker in src/titanai/workers/ingestion.py — when worker encounters an existing book: run version comparison → if changed, create version row with diff, update book row (preserving regressed fields). If unchanged, skip.
- [ ] T048 [US6] Add version history API routes in src/titanai/api/books.py — GET /tenants/{tenant_id}/books/{book_id}/versions (paginated), GET /tenants/{tenant_id}/books/{book_id}/versions/{version_id}
- [ ] T049 [US6] Write version management tests in tests/test_versions.py — ingest work, manually update stored record, re-ingest, verify new version with correct diff. Verify regression handling (field removed → old value preserved, regression flagged). Verify no version created when data unchanged. Verify version history endpoint.

**Checkpoint**: Full version history with regression protection. Data quality is auditable.

---

## Phase 9: User Story 7 — Noisy Neighbor Throttling (Priority: P3)

**Goal**: Per-tenant rate limiting and fair resource allocation with visibility into consumption.

**Independent Test**: Exceed API rate limit, verify 429. Exceed job concurrency limit, verify 429. Verify metrics endpoint returns correct counts.

### Implementation for User Story 7

- [ ] T050 [US7] Implement tenant metrics repository in src/titanai/db/repositories/tenant_metrics.py — increment_request_count(tenant_id), get_metrics(tenant_id), get_all_metrics(), reset window counter when window expires. Create metrics row on first tenant access.
- [ ] T051 [US7] Extend get_current_tenant dependency in src/titanai/api/dependencies.py — after tenant validation, check per-tenant rate limit against tenant_metrics.request_count_minute and tenant.rate_limit_per_minute. Return 429 with Retry-After header if exceeded. Increment request counter.
- [ ] T052 [US7] Add per-tenant job concurrency limit to ingestion job creation in src/titanai/db/repositories/ingestion_jobs.py — check count of queued + in_progress jobs for tenant before insert. Return 429 if MAX_CONCURRENT_JOBS_PER_TENANT exceeded.
- [ ] T053 [US7] Implement metrics API routes in src/titanai/api/metrics.py — GET /tenants/{tenant_id}/metrics (per-tenant), GET /metrics (aggregate operator view with all tenants)
- [ ] T054 [US7] Write throttling tests in tests/test_metrics.py — exceed API rate limit verify 429, exceed job concurrency limit verify 429, verify fair scheduling (tenant with fewer active jobs gets priority), verify metrics endpoint returns correct per-tenant counts

**Checkpoint**: Multi-tenant fairness enforced. Resource consumption visible.

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Cross-tenant isolation validation across all endpoints, final integration

- [ ] T055 Write comprehensive cross-tenant isolation tests in tests/test_isolation.py — for every data-returning endpoint: create tenants A and B, populate A, query as B, assert zero results from A. Cover: books, versions, jobs, logs, reading lists, metrics. Direct ID access: create resource under A, request under B → 404.
- [ ] T056 Run quickstart.md validation — follow quickstart.md steps end-to-end on a fresh environment, verify all commands work and produce expected results
- [ ] T057 Verify all list endpoints support pagination — spot-check offset/limit/total on books, jobs, logs, reading lists, versions, metrics

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user stories
- **Phase 3 (US1 - Ingestion)**: Depends on Phase 2
- **Phase 4 (US2 - Retrieval)**: Depends on Phase 3 (needs ingested data to query)
- **Phase 5 (US5 - Background Jobs)**: Depends on Phase 3 (converts sync ingestion to async)
- **Phase 6 (US3 - Activity Log)**: Depends on Phase 5 (jobs produce log entries)
- **Phase 7 (US4 - Reading Lists)**: Depends on Phase 2 only — **can parallelize with Phases 3-6**
- **Phase 8 (US6 - Versions)**: Depends on Phase 5 (needs re-ingestion via jobs)
- **Phase 9 (US7 - Throttling)**: Depends on Phase 5 (needs job system for concurrency limits)
- **Phase 10 (Polish)**: Depends on all desired user stories being complete

### User Story Dependencies

```
Phase 2 (Tenants)
    ├── US1 (Ingestion) → US2 (Retrieval) ← MVP COMPLETE
    │       └── US5 (Background Jobs)
    │               ├── US3 (Activity Log)
    │               ├── US6 (Versions)
    │               └── US7 (Throttling)
    └── US4 (Reading Lists + PII) [parallel with US1-US3]
```

### Within Each User Story

- Models before repositories
- Repositories before services
- Services before API routes
- Implementation before tests (tests validate the implementation)

### Parallel Opportunities

- **Phase 1**: T003, T004, T008 can run in parallel
- **Phase 2**: T010 can parallelize with T011 prep
- **US1**: T015, T016 (models) can parallelize
- **US4**: T037, T038 (PII module + models) can parallelize
- **US4 can fully parallelize** with US1 → US2 → US5 pipeline (only needs Phase 2)
- **US6**: T044 (models) can parallelize with T045 prep

---

## Parallel Example: User Story 1

```bash
# Launch models in parallel:
Task: "T015 — Create Book Pydantic models in src/titanai/models/books.py"
Task: "T016 — Create IngestionJob Pydantic models in src/titanai/models/ingestion.py"

# Then sequentially:
Task: "T017 — OL client"
Task: "T018 — Book repository"
Task: "T019 — Ingestion service"
Task: "T020 — Sync ingestion route"
Task: "T021 — Tests"
```

## Parallel Example: User Story 4 (Independent Track)

```bash
# US4 can start as soon as Phase 2 completes, in parallel with US1/US2/US5:
Task: "T037 — PII hashing module"  # parallel with T038
Task: "T038 — ReadingList models"  # parallel with T037
Task: "T039 — Reading list repository"
Task: "T040 — Book resolution service"
Task: "T041 — Reading list routes"
Task: "T042 — PII tests"  # parallel with T043
Task: "T043 — Reading list tests"
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (tenant CRUD + isolation)
3. Complete Phase 3: US1 — Catalog Ingestion (sync, blocking)
4. Complete Phase 4: US2 — Catalog Retrieval & Search
5. **STOP and VALIDATE**: End-to-end cycle works — ingest by author, search, retrieve detail
6. Deploy/demo if ready — this is the MVP (SC-001)

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 + US2 → **MVP** (ingest + search)
3. US5 → Production-ready ingestion (async, retries, refresh)
4. US3 → Observability (activity log)
5. US4 → Patron engagement (reading lists + PII) — can parallelize with steps 2-4
6. US6 → Data quality (version management)
7. US7 → Multi-tenant fairness (throttling + metrics)
8. Polish → Cross-cutting validation

### Critical Path

Setup → Tenants → Ingestion → Retrieval → **MVP** → Background Jobs → Activity Log / Versions / Throttling
