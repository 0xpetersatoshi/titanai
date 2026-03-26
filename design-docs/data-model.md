# TitanAI — Data Model (SQLite)

## ER Overview

```
Tenant 1──* Book 1──* BookVersion
  │                 │
  │                 └──* ReadingListItem
  │
  ├──* IngestionJob ──1 ActivityLog
  │
  └──* ReadingList 1──* ReadingListItem
```

---

## Tables

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

**Indexes**:

- `idx_books_tenant` on `(tenant_id)` — tenant scoping
- `idx_books_tenant_author` on `(tenant_id, authors)` — author filter (FR-007)
- `idx_books_tenant_year` on `(tenant_id, first_publish_year)` — year range filter (FR-007)

> **SQLite note on JSON columns**: `authors` and `subjects` are stored as JSON text. SQLite's built-in `json_each()`
> function supports querying into these arrays for filtering. For keyword search (FR-008), we use `LIKE` against `title`
> and `authors` columns.

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

**Unique constraint**: `(book_id, version_number)`

**Index**: `idx_book_versions_book` on `(book_id)` — version history queries

> **Version creation logic**: On re-ingestion, compare fetched data to current book row. If any field differs, insert a
> new `book_versions` row with the _new_ data, compute the diff, and update the `books` row. If a field was non-null
> before but null now (regression), preserve the old value in the `books` row and flag the regression in the version
> record.

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

**Index**: `idx_jobs_tenant_status` on `(tenant_id, status)` — job listing and status queries

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

**Index**: `idx_activity_logs_tenant_created` on `(tenant_id, created_at DESC)` — paginated reverse-chronological
queries (FR-011)

> **Why denormalize from jobs?** Activity logs are a read-heavy, append-only audit trail. Denormalizing avoids joins on
> every log query. The `job_id` FK preserves traceability.

### reading_lists

Patron reading list submissions with hashed PII (FR-012, FR-013, FR-014).

| Column              | Type | Constraints               | Notes                                        |
| ------------------- | ---- | ------------------------- | -------------------------------------------- |
| `id`                | TEXT | PK                        | UUID                                         |
| `tenant_id`         | TEXT | FK → tenants.id, NOT NULL | Tenant scope                                 |
| `patron_name_hash`  | TEXT | NOT NULL                  | HMAC-SHA256 of patron name (FR-013)          |
| `patron_email_hash` | TEXT | NOT NULL                  | HMAC-SHA256 of patron email (FR-013, FR-014) |
| `created_at`        | TEXT | NOT NULL                  | Submission timestamp                         |

**Index**: `idx_reading_lists_tenant` on `(tenant_id)` — tenant-scoped queries **Index**: `idx_reading_lists_patron` on
`(tenant_id, patron_email_hash)` — deduplication lookups (FR-014)

> **PII handling**: Only hashes are stored. The HMAC key is a server-side secret stored outside the database
> (environment variable or secrets manager). Same email + same key = same hash, enabling deduplication without storing
> plaintext.

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

**Index**: `idx_reading_list_items_list` on `(reading_list_id)` — fetch items for a list

### tenant_metrics

Rolling counters for noisy neighbor throttling (FR-024, FR-025). Updated in-process; queryable via API.

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

---

## SQLite-Specific Design Decisions

1. **UUIDs as TEXT** — SQLite has no native UUID type. UUIDs are generated application-side and stored as 36-character
   text. This avoids integer PK collisions in a multi-tenant context and makes IDs opaque.

2. **Timestamps as TEXT (ISO 8601)** — SQLite has no native datetime type. Storing as ISO 8601 strings
   (`2026-03-25T14:30:00Z`) allows lexicographic sorting and is compatible with SQLite's built-in `datetime()`
   functions.

3. **JSON in TEXT columns** — `authors`, `subjects`, `errors`, `diff`, and `regression_fields` are stored as JSON text.
   SQLite's `json_each()` and `json_extract()` functions enable querying into these arrays without needing junction
   tables. This simplifies the schema while supporting the filtering requirements (FR-007).

4. **No junction tables for authors/subjects** — A normalized design would use `book_authors` and `book_subjects`
   junction tables. The JSON approach is simpler and sufficient for the query patterns here (filtering by substring
   match, not relational joins). If query performance becomes an issue, these can be extracted into junction tables
   later.

5. **Boolean as INTEGER** — SQLite convention. 0 = false, 1 = true.

6. **WAL mode recommended** — Enable `PRAGMA journal_mode=WAL` for concurrent read/write access. This is important for
   background ingestion jobs writing while API requests read.

7. **Foreign key enforcement** — Must explicitly enable with `PRAGMA foreign_keys=ON` per connection.

---

## Relationship Summary

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
