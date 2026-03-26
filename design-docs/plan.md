# TitanAI — Technical Plan

## Technical Context

- Language: Python 3.12+
- Package manager: uv
- Web framework: FastAPI (async, auto-generated OpenAPI docs)
- Database: SQLite via aiosqlite + SQLAlchemy async (zero-infrastructure single-command startup)
- Background tasks: In-process async job runner backed by SQLite job table (no Redis/Celery overhead for a 3-hour
  window)
- HTTP client: httpx (async, for Open Library API calls)
- Data validation: Pydantic v2
- PII hashing: HMAC-SHA256 with a configurable secret key
- Testing: pytest + pytest-asyncio + httpx (AsyncClient for API tests)
- Linting: ruff
- Startup: `make run` → `uv run uvicorn`
- External API: Open Library (<https://openlibrary.org/developers/api>)

---

## Architecture

Tenant scoping is done via a path prefix `/tenants/{tenant_id}` to make isolation explicit and consistent.

### Tenant Management (Admin)

| Method | Route                  | Description        | FR  |
| ------ | ---------------------- | ------------------ | --- |
| `POST` | `/tenants`             | Create a tenant    | —   |
| `GET`  | `/tenants`             | List all tenants   | —   |
| `GET`  | `/tenants/{tenant_id}` | Get tenant details | —   |

### Catalog — Ingestion (US-1, US-5)

| Method | Route                                          | Description                                                        | FR             |
| ------ | ---------------------------------------------- | ------------------------------------------------------------------ | -------------- |
| `POST` | `/tenants/{tenant_id}/ingestion/jobs`          | Trigger ingestion (author or subject). Returns job ID immediately. | FR-001, FR-017 |
| `GET`  | `/tenants/{tenant_id}/ingestion/jobs`          | List ingestion jobs (with status filter)                           | FR-018         |
| `GET`  | `/tenants/{tenant_id}/ingestion/jobs/{job_id}` | Get job status/progress                                            | FR-018         |

Request body for `POST .../ingestion/jobs`:

```json
{
  "query_type": "author" | "subject",
  "query_value": "Octavia Butler"
}
```

### Catalog — Retrieval & Search (US-2)

| Method | Route                                  | Description                                           | FR                     |
| ------ | -------------------------------------- | ----------------------------------------------------- | ---------------------- |
| `GET`  | `/tenants/{tenant_id}/books`           | List books with pagination, filtering, keyword search | FR-006, FR-007, FR-008 |
| `GET`  | `/tenants/{tenant_id}/books/{book_id}` | Get single book detail                                | FR-009                 |

Query params for `GET .../books`:

- `offset`, `limit` — pagination
- `author` — filter by author name
- `subject` — filter by subject
- `year_min`, `year_max` — publish year range
- `q` — keyword search (title or author)

### Catalog — Version History (US-6)

| Method | Route                                                        | Description                     | FR             |
| ------ | ------------------------------------------------------------ | ------------------------------- | -------------- |
| `GET`  | `/tenants/{tenant_id}/books/{book_id}/versions`              | List version history for a book | FR-021, FR-023 |
| `GET`  | `/tenants/{tenant_id}/books/{book_id}/versions/{version_id}` | Get a specific version snapshot | FR-023         |

### Activity Log (US-3)

| Method | Route                                 | Description                                              | FR             |
| ------ | ------------------------------------- | -------------------------------------------------------- | -------------- |
| `GET`  | `/tenants/{tenant_id}/ingestion/logs` | List activity log entries (paginated, most-recent-first) | FR-010, FR-011 |

### Reading Lists (US-4)

| Method | Route                                          | Description                                       | FR                     |
| ------ | ---------------------------------------------- | ------------------------------------------------- | ---------------------- |
| `POST` | `/tenants/{tenant_id}/reading-lists`           | Submit a reading list (PII hashed before storage) | FR-012, FR-013, FR-014 |
| `GET`  | `/tenants/{tenant_id}/reading-lists`           | List reading list submissions (paginated)         | —                      |
| `GET`  | `/tenants/{tenant_id}/reading-lists/{list_id}` | Get a specific reading list                       | —                      |

Request body for `POST .../reading-lists`:

```json
{
  "patron_name": "Jane Doe",
  "patron_email": "jane@example.com",
  "books": [
    { "id": "/works/OL45804W", "id_type": "work_id" },
    { "id": "978-0-06-112008-4", "id_type": "isbn" }
  ]
}
```

### Tenant Metrics (US-7)

| Method | Route                          | Description                                      | FR     |
| ------ | ------------------------------ | ------------------------------------------------ | ------ |
| `GET`  | `/tenants/{tenant_id}/metrics` | Get resource consumption for a tenant            | FR-025 |
| `GET`  | `/metrics`                     | Get aggregate per-tenant metrics (operator view) | FR-025 |

### Design Decisions

1. **Tenant in path, not header** — Makes isolation explicit, URLs are self-describing, easier to test and log.
2. **Ingestion as a job resource** — `POST .../ingestion/jobs` returns a job reference (FR-017). Separate from the books
   it produces.
3. **Search and filter on the list endpoint** — `GET .../books` handles both listing and searching via query params.
4. **Versions as a sub-resource of books** — `GET .../books/{book_id}/versions` is the natural REST path.
5. **Reading list books as an array in the body** — Supports mixed ID types (work IDs and ISBNs) in a single submission.

---

## Database Schema (SQLite)

### ER Overview

```
Tenant 1──* Book 1──* BookVersion
  │                 │
  │                 └──* ReadingListItem
  │
  ├──* IngestionJob ──1 ActivityLog
  │
  └──* ReadingList 1──* ReadingListItem
```

### tenants

The isolation boundary. Every other table references `tenant_id`.

| Column                    | Type    | Constraints          | Notes                                    |
| ------------------------- | ------- | -------------------- | ---------------------------------------- |
| `id`                      | TEXT    | PK                   | UUID as text (SQLite has no native UUID) |
| `name`                    | TEXT    | NOT NULL, UNIQUE     | Library branch display name              |
| `slug`                    | TEXT    | NOT NULL, UNIQUE     | URL-safe identifier                      |
| `rate_limit_per_minute`   | INTEGER | NOT NULL, DEFAULT 60 | Per-tenant API rate limit (FR-024)       |
| `ingestion_refresh_hours` | INTEGER | NOT NULL, DEFAULT 24 | Auto re-ingestion interval (FR-020)      |
| `created_at`              | TEXT    | NOT NULL             | ISO 8601 timestamp                       |
| `updated_at`              | TEXT    | NOT NULL             | ISO 8601 timestamp                       |

### books

The current state of each catalog entry. One row per (tenant, Open Library work).

| Column               | Type    | Constraints               | Notes                                                   |
| -------------------- | ------- | ------------------------- | ------------------------------------------------------- |
| `id`                 | TEXT    | PK                        | UUID                                                    |
| `tenant_id`          | TEXT    | FK → tenants.id, NOT NULL | Tenant scope                                            |
| `ol_work_id`         | TEXT    | NOT NULL                  | Open Library work key (e.g., `/works/OL45804W`)         |
| `title`              | TEXT    | NOT NULL                  | FR-003                                                  |
| `authors`            | TEXT    | NOT NULL                  | JSON array of author names (e.g., `["Octavia Butler"]`) |
| `first_publish_year` | INTEGER |                           | Nullable — some works lack this                         |
| `subjects`           | TEXT    |                           | JSON array of subject strings                           |
| `cover_image_url`    | TEXT    |                           | Nullable per FR-003                                     |
| `current_version`    | INTEGER | NOT NULL, DEFAULT 1       | Tracks latest version number                            |
| `created_at`         | TEXT    | NOT NULL                  | First ingestion timestamp                               |
| `updated_at`         | TEXT    | NOT NULL                  | Last ingestion timestamp                                |

**Unique constraint**: `(tenant_id, ol_work_id)` — enforces FR-004 deduplication.

**Indexes**: `idx_books_tenant` on `(tenant_id)`, `idx_books_tenant_author` on `(tenant_id, authors)`,
`idx_books_tenant_year` on `(tenant_id, first_publish_year)`.

> **SQLite note on JSON columns**: `authors` and `subjects` are stored as JSON text. SQLite's `json_each()` supports
> querying into these arrays. For keyword search (FR-008), we use `LIKE` against `title` and `authors`.

### book_versions

Immutable snapshots created on re-ingestion when metadata changes (FR-021, FR-022).

| Column               | Type    | Constraints             | Notes                                                         |
| -------------------- | ------- | ----------------------- | ------------------------------------------------------------- |
| `id`                 | TEXT    | PK                      | UUID                                                          |
| `book_id`            | TEXT    | FK → books.id, NOT NULL | Parent book                                                   |
| `version_number`     | INTEGER | NOT NULL                | Sequential per book, starting at 1                            |
| `title`              | TEXT    | NOT NULL                | Snapshot of title at this version                             |
| `authors`            | TEXT    | NOT NULL                | JSON array snapshot                                           |
| `first_publish_year` | INTEGER |                         | Snapshot                                                      |
| `subjects`           | TEXT    |                         | JSON array snapshot                                           |
| `cover_image_url`    | TEXT    |                         | Snapshot                                                      |
| `diff`               | TEXT    |                         | JSON object describing field-level changes from prior version |
| `has_regression`     | INTEGER | NOT NULL, DEFAULT 0     | Boolean flag — 1 if any field regressed (FR-022)              |
| `regression_fields`  | TEXT    |                         | JSON array of field names that regressed                      |
| `created_at`         | TEXT    | NOT NULL                | When this version was recorded                                |

**Unique constraint**: `(book_id, version_number)`. **Index**: `idx_book_versions_book` on `(book_id)`.

> **Version creation logic**: On re-ingestion, compare fetched data to current book row. If any field differs, insert a
> new version row, compute the diff, and update the books row. If a field was non-null before but null now (regression),
> preserve the old value and flag the regression.

### ingestion_jobs

Background job tracking for async ingestion (FR-017, FR-018).

| Column            | Type    | Constraints                                                                                   | Notes                                                              |
| ----------------- | ------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `id`              | TEXT    | PK                                                                                            | UUID                                                               |
| `tenant_id`       | TEXT    | FK → tenants.id, NOT NULL                                                                     | Tenant scope                                                       |
| `query_type`      | TEXT    | NOT NULL, CHECK(query_type IN ('author', 'subject'))                                          | FR-001                                                             |
| `query_value`     | TEXT    | NOT NULL                                                                                      | The author name or subject searched                                |
| `status`          | TEXT    | NOT NULL, DEFAULT 'queued', CHECK(status IN ('queued', 'in_progress', 'completed', 'failed')) | FR-018                                                             |
| `total_works`     | INTEGER | DEFAULT 0                                                                                     | Total works found from Open Library                                |
| `processed_works` | INTEGER | DEFAULT 0                                                                                     | Works processed so far (success + failure)                         |
| `succeeded`       | INTEGER | DEFAULT 0                                                                                     | FR-010                                                             |
| `failed`          | INTEGER | DEFAULT 0                                                                                     | FR-010                                                             |
| `errors`          | TEXT    |                                                                                               | JSON array of error objects `[{"work_id": "...", "error": "..."}]` |
| `is_auto_refresh` | INTEGER | NOT NULL, DEFAULT 0                                                                           | Boolean — 1 if triggered by periodic refresh (FR-020)              |
| `created_at`      | TEXT    | NOT NULL                                                                                      | Job creation time                                                  |
| `started_at`      | TEXT    |                                                                                               | When processing began                                              |
| `completed_at`    | TEXT    |                                                                                               | When processing finished (success or failure)                      |

**Index**: `idx_jobs_tenant_status` on `(tenant_id, status)`.

### activity_logs

Immutable audit records of completed ingestion operations (FR-010, FR-011). One row per completed job.

| Column          | Type    | Constraints                              | Notes                                   |
| --------------- | ------- | ---------------------------------------- | --------------------------------------- |
| `id`            | TEXT    | PK                                       | UUID                                    |
| `tenant_id`     | TEXT    | FK → tenants.id, NOT NULL                | Tenant scope                            |
| `job_id`        | TEXT    | FK → ingestion_jobs.id, NOT NULL, UNIQUE | Links to the job that produced this log |
| `query_type`    | TEXT    | NOT NULL                                 | Denormalized from job for fast queries  |
| `query_value`   | TEXT    | NOT NULL                                 | Denormalized from job                   |
| `total_fetched` | INTEGER | NOT NULL                                 | Total works found                       |
| `succeeded`     | INTEGER | NOT NULL                                 | Works stored successfully               |
| `failed`        | INTEGER | NOT NULL                                 | Works that failed processing            |
| `errors`        | TEXT    |                                          | JSON array of error details             |
| `created_at`    | TEXT    | NOT NULL                                 | When the ingestion completed            |

**Index**: `idx_activity_logs_tenant_created` on `(tenant_id, created_at DESC)`.

### reading_lists

Patron reading list submissions with hashed PII (FR-012, FR-013, FR-014).

| Column              | Type | Constraints               | Notes                                        |
| ------------------- | ---- | ------------------------- | -------------------------------------------- |
| `id`                | TEXT | PK                        | UUID                                         |
| `tenant_id`         | TEXT | FK → tenants.id, NOT NULL | Tenant scope                                 |
| `patron_name_hash`  | TEXT | NOT NULL                  | HMAC-SHA256 of patron name (FR-013)          |
| `patron_email_hash` | TEXT | NOT NULL                  | HMAC-SHA256 of patron email (FR-013, FR-014) |
| `created_at`        | TEXT | NOT NULL                  | Submission timestamp                         |

**Indexes**: `idx_reading_lists_tenant` on `(tenant_id)`, `idx_reading_lists_patron` on
`(tenant_id, patron_email_hash)`.

### reading_list_items

Individual book entries within a reading list, with resolution status (FR-015, FR-016).

| Column                | Type | Constraints                                               | Notes                                                     |
| --------------------- | ---- | --------------------------------------------------------- | --------------------------------------------------------- |
| `id`                  | TEXT | PK                                                        | UUID                                                      |
| `reading_list_id`     | TEXT | FK → reading_lists.id, NOT NULL                           | Parent list                                               |
| `submitted_id`        | TEXT | NOT NULL                                                  | The ID the patron submitted (work ID or ISBN)             |
| `submitted_id_type`   | TEXT | NOT NULL, CHECK(submitted_id_type IN ('work_id', 'isbn')) | What type of ID was submitted                             |
| `resolved_ol_work_id` | TEXT |                                                           | Open Library work ID after resolution (null if not found) |
| `book_id`             | TEXT | FK → books.id                                             | Links to local catalog entry if it exists (nullable)      |
| `status`              | TEXT | NOT NULL, CHECK(status IN ('resolved', 'not_found'))      | Resolution outcome (FR-016)                               |

**Index**: `idx_reading_list_items_list` on `(reading_list_id)`.

### tenant_metrics

Rolling counters for noisy neighbor throttling (FR-024, FR-025).

| Column                  | Type    | Constraints                       | Notes                              |
| ----------------------- | ------- | --------------------------------- | ---------------------------------- |
| `id`                    | TEXT    | PK                                | UUID                               |
| `tenant_id`             | TEXT    | FK → tenants.id, NOT NULL, UNIQUE | One row per tenant                 |
| `request_count_minute`  | INTEGER | NOT NULL, DEFAULT 0               | Requests in current sliding window |
| `active_ingestion_jobs` | INTEGER | NOT NULL, DEFAULT 0               | Currently running jobs             |
| `total_books`           | INTEGER | NOT NULL, DEFAULT 0               | Total books in catalog             |
| `total_ingestion_jobs`  | INTEGER | NOT NULL, DEFAULT 0               | Lifetime job count                 |
| `window_start`          | TEXT    | NOT NULL                          | Start of current rate-limit window |
| `updated_at`            | TEXT    | NOT NULL                          | Last update time                   |

### SQLite-Specific Decisions

1. **UUIDs as TEXT** — No native UUID type; generated application-side as 36-char text.
2. **Timestamps as TEXT (ISO 8601)** — Lexicographic sorting, compatible with `datetime()` functions.
3. **JSON in TEXT columns** — `authors`, `subjects`, `errors`, `diff`, `regression_fields`; queryable via
   `json_each()`/`json_extract()`.
4. **No junction tables for authors/subjects** — JSON approach is simpler and sufficient for substring-match filtering.
5. **Boolean as INTEGER** — SQLite convention (0/1).
6. **WAL mode** — `PRAGMA journal_mode=WAL` for concurrent read/write.
7. **Foreign key enforcement** — `PRAGMA foreign_keys=ON` per connection.

### Relationship Summary

| Parent         | Child              | Cardinality    | FK Column                          |
| -------------- | ------------------ | -------------- | ---------------------------------- |
| tenants        | books              | 1:N            | books.tenant_id                    |
| tenants        | ingestion_jobs     | 1:N            | ingestion_jobs.tenant_id           |
| tenants        | activity_logs      | 1:N            | activity_logs.tenant_id            |
| tenants        | reading_lists      | 1:N            | reading_lists.tenant_id            |
| tenants        | tenant_metrics     | 1:1            | tenant_metrics.tenant_id           |
| books          | book_versions      | 1:N            | book_versions.book_id              |
| ingestion_jobs | activity_logs      | 1:1            | activity_logs.job_id               |
| reading_lists  | reading_list_items | 1:N            | reading_list_items.reading_list_id |
| books          | reading_list_items | 1:N (optional) | reading_list_items.book_id         |

---

## Tenant Isolation Strategy

Tenant isolation is **non-negotiable** (Constitution §I). Isolation is enforced redundantly across four layers — a
failure at any one layer should not result in cross-tenant data exposure.

### Layer 1: API Route Design

Every tenant-scoped endpoint lives under `/tenants/{tenant_id}/...`. Tenant ID is a **path parameter**, not a header —
URLs are self-describing in logs/monitoring, and a missing segment is a 404, not a silent default.

**Routes without tenant prefix** (admin only): `POST /tenants`, `GET /tenants`, `GET /metrics`.

### Layer 2: Middleware — Validation & Context

FastAPI dependency `get_current_tenant` runs on every tenant-scoped route:

1. **Validate** tenant exists in DB → 404 if not found (no downstream code runs)
2. **Inject** `TenantContext` (ID + config) via dependency injection — handlers never extract tenant_id from path
3. **Rate limit** check against `tenant_metrics` → 429 if exceeded

**Key rule**: All service/repository functions require `tenant_id` as a non-optional parameter.

### Layer 3: Repository — Query Scoping

The repository layer is the **only** code that constructs SQL. Tenant scoping is a structural guarantee:

- **Mandatory `tenant_id` parameter** on every method. No "get all across tenants" methods exist.
- **Every query includes `WHERE tenant_id = ?`** — SELECT, UPDATE, DELETE. Not optional.
- **Composite lookups** use both resource ID and tenant ID: `WHERE id = ? AND tenant_id = ?`
- **Cross-resource queries** scope the root table; FK relationships guarantee child records belong to the same tenant.
- **Background jobs** carry `tenant_id` from the job record through to all repository calls. No shared state.

### Layer 4: Database Constraints

| Table              | FK to tenants                    |
| ------------------ | -------------------------------- |
| books              | Direct: `tenant_id → tenants.id` |
| book_versions      | Indirect: via `books.id`         |
| ingestion_jobs     | Direct: `tenant_id → tenants.id` |
| activity_logs      | Direct: `tenant_id → tenants.id` |
| reading_lists      | Direct: `tenant_id → tenants.id` |
| reading_list_items | Indirect: via `reading_lists.id` |
| tenant_metrics     | Direct: `tenant_id → tenants.id` |

- `PRAGMA foreign_keys=ON` required on every connection
- `UNIQUE(tenant_id, ol_work_id)` on books — deduplication is tenant-scoped
- All multi-column indexes lead with `tenant_id` (natural partition, missing filter → obvious full scan)

### Testing Strategy

**Cross-tenant leakage**: For every data-returning endpoint — create tenants A and B, populate A, query as B, assert
zero results from A. Covers: books, versions, jobs, logs, reading lists, metrics.

**Direct ID access**: For every single-resource endpoint — create resource under tenant A, request it under tenant B's
path, assert **404** (not 403 — never confirm a resource exists under another tenant).

**Background job isolation**: Trigger ingestion for tenant A, verify books and activity logs are only visible to A.

### Failure Modes

| Failure                                | Mitigation                                                                   |
| -------------------------------------- | ---------------------------------------------------------------------------- |
| Developer forgets `WHERE tenant_id`    | Repository pattern makes tenant_id required — code won't run without it      |
| Request with wrong tenant_id           | Middleware validates existence; composite queries prevent UUID cross-access  |
| Job processes wrong tenant's data      | Job carries tenant_id; all repository calls use it                           |
| SQL injection bypasses tenant filter   | Parameterized queries only — no string interpolation                         |
| New table added without tenant scoping | Review checklist: every user-data table needs tenant_id FK or scoped parent  |
| Admin endpoint exposes tenant data     | Admin endpoints return only aggregate/metadata, never catalog or patron data |

### Rules

1. Every tenant-scoped URL includes `{tenant_id}` in the path
2. Middleware validates tenant existence before any business logic — invalid tenant = 404
3. Every repository method requires `tenant_id` — no unscoped query methods
4. Every SQL query includes `WHERE tenant_id = ?` — composite lookups use both resource ID and tenant ID
5. Cross-tenant resource access returns 404, not 403
6. Background jobs inherit tenant scope from the job record
7. Every endpoint has a cross-tenant leakage test

---

## PII Handling

PII protection is **non-negotiable** (Constitution §II). Only two PII fields exist: `patron_name` and `patron_email`,
both from reading list submissions. All other data (books, jobs, logs, tenants) is not PII.

### Approach: HMAC-SHA256

All PII is irreversibly hashed via **HMAC-SHA256** with a server-side secret before persistence. HMAC over plain SHA-256
prevents rainbow table attacks on low-entropy emails. Hashing is deterministic (same input + key → same hash), enabling
deduplication (FR-014) without storing plaintext.

### Hashing Module

Centralized in a single module. No other code hashes patron data.

```
hash_email(plaintext_email: str) -> str
hash_name(plaintext_name: str) -> str
```

Both functions: normalize input → compute HMAC-SHA256 → return hex digest. Never log, cache, or retain plaintext.

#### Normalization (before hashing)

| Field | Rule                                         | Example                                        |
| ----- | -------------------------------------------- | ---------------------------------------------- |
| email | Lowercase, strip whitespace                  | `"  Jane@Example.COM "` → `"jane@example.com"` |
| name  | Lowercase, strip whitespace, collapse spaces | `"  Jane   DOE "` → `"jane doe"`               |

### Secret Key Management

| Requirement             | Implementation                               |
| ----------------------- | -------------------------------------------- |
| Not in code/config/logs | Loaded from env var `TITANAI_PII_SECRET_KEY` |
| Minimum length          | 32 bytes (256 bits), enforced at startup     |
| Missing key             | App refuses to start with fatal error        |

**Key rotation** breaks deduplication by design — old hashes won't match new ones. This is an accepted tradeoff: safety
over continuity.

### Data Flow

```
Client → API Handler → Service Layer (hash PII here) → Repository (hashes only) → Database
                                                      ↓
                                              Response (no PII)
```

Plaintext crosses from API handler into service layer, where it's immediately hashed. The repository layer **never**
receives plaintext. Responses never echo back name or email.

### Where PII Must Never Appear

| Location       | Enforcement                                                       |
| -------------- | ----------------------------------------------------------------- |
| Database       | Only `_hash` columns exist — no plaintext columns                 |
| Logs           | Hashing module never logs plaintext; structured logs use hashes   |
| Error messages | Catch and re-raise without plaintext; no raw request body in logs |
| API responses  | Submission response omits name/email; GET returns hashes only     |
| Job payloads   | Reading lists processed synchronously, PII never in job records   |
| Debug output   | PII fields replaced with `[REDACTED]` in repr/str                 |

### Deduplication via Email Hash

Same email → same normalization → same HMAC → same hash. Query `(tenant_id, patron_email_hash)` to find all submissions
from one patron. Does **not** prevent duplicate submissions — it **enables queries** across them.

### Testing Strategy

1. **No plaintext persisted**: Submit reading list, query DB directly, assert no plaintext in any column
2. **Deterministic**: Two submissions with same email → same `patron_email_hash`
3. **Normalization**: `"JANE@example.com"`, `" jane@example.com "`, `"Jane@Example.COM"` → same hash
4. **Not in logs**: Capture log output during submission, assert no plaintext
5. **Not in responses**: POST and GET responses contain hashes, never plaintext
6. **Missing key**: Unset env var, assert app fails to start with clear error

---

## Open Library Data Assembly Strategy

A single search result often lacks author details, cover URLs, or complete subject lists. The ingestion pipeline follows
this resolution chain:

1. Search by author/subject → GET /search.json → list of work keys
2. For each work key → GET /works/{id}.json → title, subjects, description
3. From work → extract author keys → GET /authors/{id}.json → author names
4. From work → construct cover URL → covers.openlibrary.org/b/olid/{id}-M.jpg
5. Assemble complete Book record from steps 2-4
6. If any step fails, record partial data + log the failure

Rate limit handling: 1-second delay between requests, retry with exponential backoff on 429/5xx, configurable
concurrency limit per ingestion job.

---

## Background Job System

Catalog ingestion must never block API responses (Constitution §III). The `ingestion_jobs` table **is** the job queue —
no Celery/Redis needed. In-process `asyncio.Task` workers poll the table and execute jobs. SQLite WAL mode enables
concurrent reads during writes.

### Job Lifecycle

`queued` → `in_progress` → `completed` | `failed`

- **queued**: API handler inserts row, returns 202 with job ID immediately.
- **in_progress**: Worker claims job via atomic SQL UPDATE. Progress tracked per-work.
- **completed**: All works processed (even if some individually failed). `succeeded`/`failed` counters distinguish
  partial success.
- **failed**: Only if the entire operation couldn't proceed (e.g., OL unreachable after all retries).

### Worker Pool

- **3 async workers** (configurable) as `asyncio.Task` instances, started on app startup, cancelled on shutdown.
- Workers poll every **2 seconds** when idle.
- **Atomic job claiming** — SQLite's single-writer guarantee prevents double-pickup:

```sql
UPDATE ingestion_jobs SET status = 'in_progress', started_at = ?
WHERE id = (SELECT id FROM ingestion_jobs WHERE status = 'queued'
            ORDER BY created_at ASC LIMIT 1)
RETURNING *
```

### Ingestion Flow

1. Fetch results from Open Library (author search or subject endpoint)
2. For each work: check dedup → assemble record (follow-up requests for missing fields) → store → update progress
3. Mark job completed, write activity log entry

### Rate Limiting & Retries

**Global OL rate limiter**: 2 req/sec shared across all workers via `asyncio.Semaphore`. All requests include
`User-Agent: TitanAI/0.1.0 (contact@example.com)`.

| Condition          | Action                                            |
| ------------------ | ------------------------------------------------- |
| HTTP 429           | Wait `Retry-After` (or 5s default), max 3 retries |
| HTTP 5xx / timeout | Exponential backoff: 1s → 2s → 4s, max 3 retries  |
| HTTP 4xx (not 429) | No retry — mark work as failed, continue to next  |

Individual work failures don't abort the job. A job is `failed` only if the initial search itself fails or an
unrecoverable error occurs.

### Automatic Refresh (FR-020)

A periodic timer (every 15 min) checks each tenant's staleness against `tenants.ingestion_refresh_hours` (default 24h).
For stale tenants, it re-creates jobs for each previously completed (query_type, query_value) pair, marked
`is_auto_refresh = 1`. Duplicate jobs (same tenant + query already queued/in-progress) are skipped.

### Per-Tenant Fairness

- **Concurrent job limit**: Max 2 jobs per tenant (queued + in-progress). Exceeding returns 429.
- **Fair scheduling**: Workers claim jobs prioritizing tenants with fewer active jobs, then FIFO:

```sql
ORDER BY (SELECT COUNT(*) FROM ingestion_jobs j2
          WHERE j2.tenant_id = j.tenant_id AND j2.status = 'in_progress') ASC,
         j.created_at ASC
```

### Recovery & Shutdown

- **Startup**: Reset all `in_progress` jobs to `queued` (handles crashes, restarts). Safe because ingestion is
  idempotent (dedup constraint).
- **Shutdown**: 30s grace period for current work item, then cancel. Incomplete jobs recovered on next startup.

### Configuration

| Setting                          | Default | Notes                     |
| -------------------------------- | ------- | ------------------------- |
| `WORKER_COUNT`                   | 3       | Async worker tasks        |
| `POLL_INTERVAL_SECONDS`          | 2       | Idle poll frequency       |
| `OL_RATE_LIMIT_PER_SECOND`       | 2       | Global OL rate limit      |
| `OL_REQUEST_TIMEOUT_SECONDS`     | 10      | Per-request timeout       |
| `MAX_RETRIES_PER_REQUEST`        | 3       | HTTP-level retries        |
| `MAX_CONCURRENT_JOBS_PER_TENANT` | 2       | Noisy neighbor limit      |
| `REFRESH_CHECK_INTERVAL_MINUTES` | 15      | Staleness check frequency |
| `SHUTDOWN_GRACE_SECONDS`         | 30      | Graceful shutdown window  |

---

## Implementation Phases

Each phase is independently deployable and testable. Critical path: 0 → 1 → 2 → 3 (MVP) → 4 → 5/7/8.

### Dependency Graph

```
Phase 0 (Foundation)
    → Phase 1 (Tenants + Isolation)
        → Phase 2 (Sync Ingestion)  |  Phase 6 (Reading Lists + PII) [parallel]
            → Phase 3 (Retrieval + Search) ← MVP
                → Phase 4 (Background Jobs)
                    → Phase 5 (Activity Log)  |  Phase 7 (Auto-Refresh)  |  Phase 8 (Version Mgmt) [parallel]
                        → Phase 9 (Noisy Neighbor Throttling)
```

### Phase 0 — Project Foundation

- Add dependencies: FastAPI, uvicorn, httpx, pydantic, pydantic-settings, aiosqlite
- Create package layout: `api/`, `db/`, `services/`, `models/`, `core/`, `workers/`
- Configuration module (Pydantic Settings, env vars, fail-fast validation)
- Database setup (SQLite + WAL mode, `PRAGMA foreign_keys=ON`, all 8 tables)
- FastAPI app scaffold with lifespan handler
- Test infrastructure (pytest, in-memory SQLite, async test client, tenant helper)

### Phase 1 — Tenant Management & Isolation (FR-026)

- Tenant repository: `create_tenant()`, `get_tenant()`, `list_tenants()`
- API routes: `POST /tenants`, `GET /tenants`, `GET /tenants/{tenant_id}`
- `get_current_tenant` dependency (validates existence, injects TenantContext, returns 404)
- Tests: CRUD, invalid tenant 404, middleware injection

### Phase 2 — Synchronous Catalog Ingestion (FR-001–005)

- Open Library client: search by author/subject, get work/author details, cover URLs, User-Agent header
- Record assembly service (follow-up requests for missing fields)
- Book repository with tenant-scoped queries
- Ingestion service: OL → assemble → deduplicate → store
- Temporary sync route (`POST .../ingestion`) — replaced in Phase 4
- Tests: live OL integration, field completeness, deduplication, cross-tenant isolation

### Phase 3 — Catalog Retrieval & Search (FR-006–009) — MVP

- Book repository extensions: list/filter/search with pagination
- Filtering: author (JSON LIKE), subject (JSON LIKE), year range (BETWEEN), keyword search
- API routes: `GET .../books` (query params), `GET .../books/{book_id}`
- Tests: pagination, each filter type, keyword search, single detail, cross-tenant 404

### Phase 4 — Background Job System (FR-017–019)

- Job repository with atomic claiming (SQL UPDATE...RETURNING)
- Async worker pool (3 tasks on app lifespan), global OL rate limiter (asyncio semaphore)
- Retry logic: 429 → Retry-After, 5xx → exponential backoff, per-work failure isolation
- Replace sync route with `POST .../ingestion/jobs` → 202 + job ID
- Job status routes: `GET .../ingestion/jobs`, `GET .../ingestion/jobs/{job_id}`
- Stale job recovery on startup, graceful shutdown with grace period
- Tests: submit/poll/verify, retry on 429/500, stale recovery

### Phase 5 — Activity Log (FR-010–011)

- Activity log repository: `create_log()`, `list_logs()` (reverse chronological)
- Worker integration: write log entry on job completion
- API route: `GET .../ingestion/logs`
- Tests: log entry counts, tenant isolation, ordering, pagination

### Phase 6 — Reading Lists + PII (FR-012–016) — parallel after Phase 1

- PII hashing module: HMAC-SHA256, normalization, secret key validation at startup
- Reading list repository: create, list, get (tenant-scoped)
- Book resolution service: work IDs against local catalog/OL, ISBNs via `/isbn/{isbn}.json`
- API routes: `POST .../reading-lists`, `GET .../reading-lists`, `GET .../reading-lists/{list_id}`
- Tests: no plaintext in DB, deterministic hashing, normalization, ISBN resolution, PII not in logs/responses

### Phase 7 — Automatic Refresh (FR-020)

- Periodic async task checking tenant staleness against `ingestion_refresh_hours`
- Re-create jobs for previously completed (query_type, query_value) pairs
- Deduplication: skip if identical job already queued/in-progress
- Tests: auto-refresh job creation, `is_auto_refresh` flag, no duplicates, skip tenants with no history

### Phase 8 — Version Management (FR-021–023)

- Version comparison service: field-by-field diff, regression detection (non-null → null)
- Book version repository: create, list, get versions
- Ingestion integration: on existing book → compare → create version if changed, preserve regressed fields
- API routes: `GET .../books/{book_id}/versions`, `GET .../books/{book_id}/versions/{version_id}`
- Tests: version creation on change, regression handling, no version on unchanged, version history endpoint

### Phase 9 — Noisy Neighbor Throttling (FR-024–025)

- Per-tenant API rate limiting via middleware (fixed-window counter, 429 + Retry-After)
- Per-tenant job concurrency limit at submission + fair-scheduling in claim query
- Metrics repository: increment, get per-tenant, get aggregate
- API routes: `GET .../metrics`, `GET /metrics`
- Tests: rate limit 429, job limit 429, fair scheduling priority, metrics accuracy

### Phase Summary

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

---

## Risk Mitigations

### External Dependency: Open Library API

| Risk                                                                   | Impact                                 | Mitigation                                                                                                                               |
| ---------------------------------------------------------------------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| API goes down for extended period                                      | Ingestion stalls, catalogs go stale    | Exponential backoff with bounded retries. Jobs fail gracefully with clear activity log entries. Existing catalog data remains queryable. |
| Rate limits tightened or enforced more aggressively                    | Ingestion slows significantly          | Global rate limiter is configurable (`OL_RATE_LIMIT_PER_SECOND`). User-Agent header identifies the service for higher limits.            |
| Response schema changes without notice                                 | Record assembly breaks, missing fields | Defensive parsing — treat every field as optional. Log warnings for unexpected shapes rather than crashing.                              |
| Data quality degresses (fields removed, inconsistent across endpoints) | Stored records lose data               | Version management preserves prior values on regression (FR-022). Never nullify a field that previously had a value.                     |

### Data & Security

| Risk                       | Impact                                                | Mitigation                                                                                                                                                             |
| -------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PII secret key leaked      | Patron email hashes become reversible via brute force | Key stored only in env var, never in code/config/logs. Minimum 256-bit key enforced at startup. Key rotation procedure documented (accepts deduplication break).       |
| Cross-tenant data leakage  | Privacy violation, trust destruction                  | Four-layer enforcement (route, middleware, repository, database). Every endpoint has a cross-tenant leakage test. Resource access across tenants returns 404, not 403. |
| SQLite database corruption | Data loss                                             | WAL mode reduces corruption risk. Regular backups recommended. Application-level writes are idempotent (re-ingestion is safe).                                         |

### Performance & Scalability

| Risk                                                     | Impact                              | Mitigation                                                                                                                                               |
| -------------------------------------------------------- | ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SQLite write contention under load                       | Slow ingestion, API timeouts        | WAL mode enables concurrent reads during writes. Worker count capped at 3 (writes are sequential anyway). Background jobs never block API reads.         |
| Single-tenant monopolizes resources                      | Other tenants degraded              | Per-tenant job concurrency limit. Fair scheduling prioritizes tenants with fewer active jobs. Per-tenant API rate limiting.                              |
| Large ingestion (popular author with thousands of works) | Job runs for hours, progress stalls | Progress tracked per-work. Partial success model — completed works are available immediately. Job can be resumed after crash (idempotent re-processing). |

### Operational

| Risk                                       | Impact                                      | Mitigation                                                                                                            |
| ------------------------------------------ | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Process crash mid-ingestion                | Jobs stuck in `in_progress` forever         | Stale job recovery on startup resets `in_progress` → `queued`. Idempotent re-processing via deduplication constraint. |
| Auto-refresh creates unbounded job backlog | Queue grows faster than workers can process | Refresh deduplication prevents duplicate jobs. Only re-runs previously completed queries, not new ones.               |
| Missing or misconfigured env vars          | App fails at runtime in unexpected ways     | Pydantic Settings validates all required config at startup. App refuses to start without `TITANAI_PII_SECRET_KEY`.    |
