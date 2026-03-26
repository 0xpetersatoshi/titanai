# Data Model: Multi-Tenant Library Catalog Service

**Phase 1 Output** | **Date**: 2026-03-25

## Entities

### Tenant

The isolation boundary. Every other entity belongs to exactly one tenant.

| Field                   | Type    | Constraints          | Notes                               |
| ----------------------- | ------- | -------------------- | ----------------------------------- |
| id                      | UUID    | PK                   | TEXT in SQLite                       |
| name                    | string  | NOT NULL, UNIQUE     | Library branch display name         |
| slug                    | string  | NOT NULL, UNIQUE     | URL-safe identifier                 |
| rate_limit_per_minute   | integer | NOT NULL, DEFAULT 60 | Per-tenant API rate limit (FR-024)  |
| ingestion_refresh_hours | integer | NOT NULL, DEFAULT 24 | Auto re-ingestion interval (FR-020) |
| created_at              | datetime| NOT NULL             | ISO 8601                            |
| updated_at              | datetime| NOT NULL             | ISO 8601                            |

### Book

A catalog entry sourced from Open Library, belonging to one tenant.

| Field              | Type     | Constraints                         | Notes                                     |
| ------------------ | -------- | ----------------------------------- | ----------------------------------------- |
| id                 | UUID     | PK                                  |                                           |
| tenant_id          | UUID     | FK → Tenant, NOT NULL               | Tenant scope                              |
| ol_work_id         | string   | NOT NULL                            | e.g., `/works/OL45804W`                   |
| title              | string   | NOT NULL                            |                                           |
| authors            | string[] | NOT NULL                            | JSON array in SQLite                      |
| first_publish_year | integer  | nullable                            | Some works lack this                      |
| subjects           | string[] | nullable                            | JSON array in SQLite                      |
| cover_image_url    | string   | nullable                            | Nullable per FR-003                       |
| current_version    | integer  | NOT NULL, DEFAULT 1                 | Latest version number                     |
| created_at         | datetime | NOT NULL                            |                                           |
| updated_at         | datetime | NOT NULL                            |                                           |

**Unique**: `(tenant_id, ol_work_id)` — FR-004 deduplication.

### BookVersion

Immutable snapshot created on re-ingestion when metadata changes.

| Field              | Type     | Constraints               | Notes                              |
| ------------------ | -------- | ------------------------- | ---------------------------------- |
| id                 | UUID     | PK                        |                                    |
| book_id            | UUID     | FK → Book, NOT NULL       |                                    |
| version_number     | integer  | NOT NULL                  | Sequential per book, starting at 1 |
| title              | string   | NOT NULL                  | Snapshot                           |
| authors            | string[] | NOT NULL                  | Snapshot                           |
| first_publish_year | integer  | nullable                  | Snapshot                           |
| subjects           | string[] | nullable                  | Snapshot                           |
| cover_image_url    | string   | nullable                  | Snapshot                           |
| diff               | object   | nullable                  | Field-level changes JSON           |
| has_regression     | boolean  | NOT NULL, DEFAULT false   | FR-022                             |
| regression_fields  | string[] | nullable                  | Field names that regressed         |
| created_at         | datetime | NOT NULL                  |                                    |

**Unique**: `(book_id, version_number)`.

### IngestionJob

Background job representing an ingestion operation for a tenant.

| Field           | Type     | Constraints                                         | Notes                    |
| --------------- | -------- | --------------------------------------------------- | ------------------------ |
| id              | UUID     | PK                                                  |                          |
| tenant_id       | UUID     | FK → Tenant, NOT NULL                               |                          |
| query_type      | enum     | NOT NULL, CHECK IN ('author', 'subject')            |                          |
| query_value     | string   | NOT NULL                                            |                          |
| status          | enum     | NOT NULL, DEFAULT 'queued'                          | queued → in_progress → completed/failed |
| total_works     | integer  | DEFAULT 0                                           |                          |
| processed_works | integer  | DEFAULT 0                                           |                          |
| succeeded       | integer  | DEFAULT 0                                           |                          |
| failed          | integer  | DEFAULT 0                                           |                          |
| errors          | object[] | nullable                                            | JSON array               |
| is_auto_refresh | boolean  | NOT NULL, DEFAULT false                             | FR-020                   |
| created_at      | datetime | NOT NULL                                            |                          |
| started_at      | datetime | nullable                                            |                          |
| completed_at    | datetime | nullable                                            |                          |

### ActivityLogEntry

Immutable audit record of an ingestion operation's outcome. One per completed job.

| Field         | Type     | Constraints                            | Notes                    |
| ------------- | -------- | -------------------------------------- | ------------------------ |
| id            | UUID     | PK                                     |                          |
| tenant_id     | UUID     | FK → Tenant, NOT NULL                  |                          |
| job_id        | UUID     | FK → IngestionJob, NOT NULL, UNIQUE    | 1:1 with job             |
| query_type    | string   | NOT NULL                               | Denormalized from job    |
| query_value   | string   | NOT NULL                               | Denormalized from job    |
| total_fetched | integer  | NOT NULL                               |                          |
| succeeded     | integer  | NOT NULL                               |                          |
| failed        | integer  | NOT NULL                               |                          |
| errors        | object[] | nullable                               | JSON array               |
| created_at    | datetime | NOT NULL                               |                          |

### ReadingList

Patron reading list submission with hashed PII.

| Field             | Type     | Constraints               | Notes                    |
| ----------------- | -------- | ------------------------- | ------------------------ |
| id                | UUID     | PK                        |                          |
| tenant_id         | UUID     | FK → Tenant, NOT NULL     |                          |
| patron_name_hash  | string   | NOT NULL                  | HMAC-SHA256 hex digest   |
| patron_email_hash | string   | NOT NULL                  | HMAC-SHA256 hex digest   |
| created_at        | datetime | NOT NULL                  |                          |

### ReadingListItem

Individual book entry within a reading list.

| Field              | Type   | Constraints                              | Notes                    |
| ------------------ | ------ | ---------------------------------------- | ------------------------ |
| id                 | UUID   | PK                                       |                          |
| reading_list_id    | UUID   | FK → ReadingList, NOT NULL               |                          |
| submitted_id       | string | NOT NULL                                 | Work ID or ISBN          |
| submitted_id_type  | enum   | NOT NULL, CHECK IN ('work_id', 'isbn')   |                          |
| resolved_ol_work_id| string | nullable                                 | Null if not found        |
| book_id            | UUID   | FK → Book, nullable                      | Local catalog link       |
| status             | enum   | NOT NULL, CHECK IN ('resolved', 'not_found') |                     |

### TenantMetrics

Rolling counters for rate limiting and resource visibility.

| Field                 | Type     | Constraints                     | Notes                    |
| --------------------- | -------- | ------------------------------- | ------------------------ |
| id                    | UUID     | PK                              |                          |
| tenant_id             | UUID     | FK → Tenant, NOT NULL, UNIQUE   | One per tenant           |
| request_count_minute  | integer  | NOT NULL, DEFAULT 0             |                          |
| active_ingestion_jobs | integer  | NOT NULL, DEFAULT 0             |                          |
| total_books           | integer  | NOT NULL, DEFAULT 0             |                          |
| total_ingestion_jobs  | integer  | NOT NULL, DEFAULT 0             |                          |
| window_start          | datetime | NOT NULL                        |                          |
| updated_at            | datetime | NOT NULL                        |                          |

## Relationships

```
Tenant 1──* Book 1──* BookVersion
  │                 │
  │                 └──* ReadingListItem
  │
  ├──* IngestionJob ──1 ActivityLogEntry
  │
  ├──* ReadingList 1──* ReadingListItem
  │
  └──1 TenantMetrics
```

| Parent         | Child            | Cardinality | FK                             |
| -------------- | ---------------- | ----------- | ------------------------------ |
| Tenant         | Book             | 1:N         | Book.tenant_id                 |
| Tenant         | IngestionJob     | 1:N         | IngestionJob.tenant_id         |
| Tenant         | ActivityLogEntry | 1:N         | ActivityLogEntry.tenant_id     |
| Tenant         | ReadingList      | 1:N         | ReadingList.tenant_id          |
| Tenant         | TenantMetrics    | 1:1         | TenantMetrics.tenant_id        |
| Book           | BookVersion      | 1:N         | BookVersion.book_id            |
| IngestionJob   | ActivityLogEntry | 1:1         | ActivityLogEntry.job_id        |
| ReadingList    | ReadingListItem  | 1:N         | ReadingListItem.reading_list_id|
| Book           | ReadingListItem  | 1:N (opt)   | ReadingListItem.book_id        |

## State Transitions

### IngestionJob.status

```
queued → in_progress → completed
                     → failed
```

- `queued`: Created by API handler or auto-refresh timer
- `in_progress`: Claimed by worker via atomic SQL UPDATE
- `completed`: All works processed (partial success counted via succeeded/failed)
- `failed`: Entire operation couldn't proceed (e.g., OL unreachable after retries)
- On startup: all `in_progress` reset to `queued` (crash recovery)

### ReadingListItem.status

```
(on creation) → resolved
             → not_found
```

Set once during submission processing. Immutable after creation.

## Validation Rules

- Tenant `name` and `slug`: non-empty, unique
- Book `ol_work_id`: must match Open Library work key format
- IngestionJob `query_type`: must be 'author' or 'subject'
- IngestionJob `query_value`: non-empty
- ReadingList: must contain at least one book reference
- ReadingListItem `submitted_id_type`: must be 'work_id' or 'isbn'
- PII secret key: minimum 32 bytes (256 bits), checked at startup
