# TitanAI

A multi-tenant library catalog service that aggregates book data from [Open Library](https://openlibrary.org) and makes
it searchable and browsable. Each library tenant has isolated catalog data and patron submissions.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager

## Setup

```bash
# Install dependencies (including dev tools)
uv sync --all-extras

# Set required environment variable (PII hashing key, min 32 bytes)
export TITANAI_PII_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
```

## Run

```bash
# Start the server
make run

# Or directly
uv run uvicorn titanai.main:app --reload
```

The server starts at <http://localhost:8000>. Interactive API docs at <http://localhost:8000/docs>.

## Run Tests

```bash
# All tests (excludes slow live-API tests by default)
make test

# Verbose output
uv run pytest -v

# Specific test file
uv run pytest tests/test_books.py

# Only cross-tenant isolation tests
uv run pytest tests/test_isolation.py

# Include live Open Library API tests (slower, requires internet)
uv run pytest tests/test_ingestion.py -v
```

## Walkthrough

Below is a step-by-step example exercising the main features. All commands assume the server is running locally.

### 1. Create a tenant

```bash
curl -s -X POST http://localhost:8000/tenants \
  -H "Content-Type: application/json" \
  -d '{"name": "Springfield Public Library", "slug": "springfield"}' | python -m json.tool
```

Save the returned `id` — you'll use it in every subsequent call:

```bash
export TID="<tenant-id-from-response>"
```

### 2. Trigger a catalog ingestion

Ingestion runs in the background. The request returns immediately with a job reference:

```bash
curl -s -X POST http://localhost:8000/tenants/$TID/ingestion/jobs \
  -H "Content-Type: application/json" \
  -d '{"query_type": "author", "query_value": "Octavia Butler"}' | python -m json.tool
```

Save the job `id`:

```bash
export JOB="<job-id-from-response>"
```

### 3. Check job progress

Poll until `status` changes from `queued` to `in_progress` to `completed`:

```bash
curl -s http://localhost:8000/tenants/$TID/ingestion/jobs/$JOB | python -m json.tool
```

### 4. Browse the catalog

```bash
# List all books (paginated)
curl -s "http://localhost:8000/tenants/$TID/books" | python -m json.tool

# Search by keyword
curl -s "http://localhost:8000/tenants/$TID/books?q=kindred" | python -m json.tool

# Filter by subject
curl -s "http://localhost:8000/tenants/$TID/books?subject=Science+fiction" | python -m json.tool

# Filter by publish year range
curl -s "http://localhost:8000/tenants/$TID/books?year_min=1970&year_max=1990" | python -m json.tool

# Pagination
curl -s "http://localhost:8000/tenants/$TID/books?limit=5&offset=0" | python -m json.tool
```

### 5. Get a single book's detail

```bash
export BOOK="<book-id-from-list>"
curl -s http://localhost:8000/tenants/$TID/books/$BOOK | python -m json.tool
```

### 6. View ingestion activity log

```bash
curl -s http://localhost:8000/tenants/$TID/ingestion/logs | python -m json.tool
```

### 7. Submit a reading list (PII is hashed before storage)

```bash
curl -s -X POST http://localhost:8000/tenants/$TID/reading-lists \
  -H "Content-Type: application/json" \
  -d '{
    "patron_name": "Jane Doe",
    "patron_email": "jane@example.com",
    "books": [
      {"id": "/works/OL45804W", "id_type": "work_id"},
      {"id": "978-0-807-08305-4", "id_type": "isbn"}
    ]
  }' | python -m json.tool
```

Note: the response does **not** echo back `patron_name` or `patron_email`. Only hashed identifiers are stored.

```bash
# List all reading lists (returns hashed patron identifiers only)
curl -s http://localhost:8000/tenants/$TID/reading-lists | python -m json.tool
```

### 8. Check version history (after re-ingestion detects changes)

```bash
curl -s http://localhost:8000/tenants/$TID/books/$BOOK/versions | python -m json.tool
```

### 9. View tenant metrics

```bash
# Per-tenant metrics
curl -s http://localhost:8000/tenants/$TID/metrics | python -m json.tool

# Aggregate metrics (operator view)
curl -s http://localhost:8000/metrics | python -m json.tool
```

### 10. Multi-tenant isolation demo

Create a second tenant and verify it cannot see the first tenant's data:

```bash
# Create tenant B
curl -s -X POST http://localhost:8000/tenants \
  -H "Content-Type: application/json" \
  -d '{"name": "Shelbyville Library", "slug": "shelbyville"}' | python -m json.tool

export TID_B="<tenant-b-id>"

# Tenant B sees zero books (isolation enforced)
curl -s "http://localhost:8000/tenants/$TID_B/books" | python -m json.tool
# → {"items": [], "total": 0, "offset": 0, "limit": 20}

# Tenant B cannot access Tenant A's book by ID (returns 404, not 403)
curl -s http://localhost:8000/tenants/$TID_B/books/$BOOK | python -m json.tool
# → {"detail": "Book not found"}
```

## Environment Variables

| Variable                                 | Required | Default      | Description                             |
| ---------------------------------------- | -------- | ------------ | --------------------------------------- |
| `TITANAI_PII_SECRET_KEY`                 | Yes      | —            | HMAC key for PII hashing (min 32 bytes) |
| `TITANAI_DB_PATH`                        | No       | `titanai.db` | SQLite database file path               |
| `TITANAI_WORKER_COUNT`                   | No       | `3`          | Background worker tasks                 |
| `TITANAI_OL_RATE_LIMIT_PER_SECOND`       | No       | `2`          | Open Library API rate limit             |
| `TITANAI_MAX_CONCURRENT_JOBS_PER_TENANT` | No       | `2`          | Max queued+active jobs per tenant       |
| `TITANAI_REFRESH_CHECK_INTERVAL_MINUTES` | No       | `15`         | Auto-refresh staleness check interval   |
| `TITANAI_SHUTDOWN_GRACE_SECONDS`         | No       | `30`         | Graceful shutdown window for workers    |

## API Endpoints

| Method | Route                                                        | Description                        |
| ------ | ------------------------------------------------------------ | ---------------------------------- |
| `POST` | `/tenants`                                                   | Create a tenant                    |
| `GET`  | `/tenants`                                                   | List all tenants                   |
| `GET`  | `/tenants/{tenant_id}`                                       | Get tenant details                 |
| `POST` | `/tenants/{tenant_id}/ingestion/jobs`                        | Trigger background ingestion (202) |
| `GET`  | `/tenants/{tenant_id}/ingestion/jobs`                        | List ingestion jobs                |
| `GET`  | `/tenants/{tenant_id}/ingestion/jobs/{job_id}`               | Get job status                     |
| `GET`  | `/tenants/{tenant_id}/ingestion/logs`                        | Activity log                       |
| `GET`  | `/tenants/{tenant_id}/books`                                 | List/search/filter books           |
| `GET`  | `/tenants/{tenant_id}/books/{book_id}`                       | Book detail                        |
| `GET`  | `/tenants/{tenant_id}/books/{book_id}/versions`              | Version history                    |
| `GET`  | `/tenants/{tenant_id}/books/{book_id}/versions/{version_id}` | Version detail                     |
| `POST` | `/tenants/{tenant_id}/reading-lists`                         | Submit reading list (PII hashed)   |
| `GET`  | `/tenants/{tenant_id}/reading-lists`                         | List reading lists                 |
| `GET`  | `/tenants/{tenant_id}/reading-lists/{list_id}`               | Reading list detail                |
| `GET`  | `/tenants/{tenant_id}/metrics`                               | Per-tenant metrics                 |
| `GET`  | `/metrics`                                                   | Aggregate metrics                  |

## Project Layout

```
src/titanai/
├── main.py              # FastAPI app, lifespan handler
├── api/                 # Route handlers
│   ├── tenants.py
│   ├── books.py
│   ├── ingestion.py
│   ├── reading_lists.py
│   ├── metrics.py
│   └── dependencies.py  # Tenant validation + rate limiting
├── db/
│   ├── connection.py    # SQLite (WAL mode, FK enforcement)
│   ├── schema.py        # DDL for 8 tables
│   └── repositories/    # Tenant-scoped data access
├── services/
│   ├── openlibrary.py   # Async Open Library API client
│   ├── ingestion.py     # OL → assemble → dedup → store
│   ├── reading_lists.py # Book resolution + PII handoff
│   └── versions.py      # Field-by-field diff, regression detection
├── models/              # Pydantic request/response schemas
├── core/
│   ├── config.py        # Pydantic Settings (env vars)
│   └── pii.py           # HMAC-SHA256 hashing module
└── workers/
    ├── pool.py          # Async worker lifecycle
    ├── ingestion.py     # Job execution with retries
    └── refresh.py       # Auto-refresh timer
```

## Architecture Overview

```
                         ┌─────────────┐
                         │   Client    │
                         └──────┬──────┘
                                │
                         ┌──────▼──────┐
                         │   FastAPI   │
                         │   Router    │
                         └──────┬──────┘
                                │
                    ┌───────────▼───────────┐
                    │  Tenant Middleware     │
                    │  (validate + rate limit)│
                    └───────────┬───────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                   │
       ┌──────▼──────┐  ┌──────▼──────┐    ┌──────▼──────┐
       │  Services   │  │   Workers   │    │  PII Module │
       │ (ingestion, │  │ (async pool,│    │ (HMAC-SHA256│
       │  versions)  │  │  refresh)   │    │  hashing)   │
       └──────┬──────┘  └──────┬──────┘    └──────┬──────┘
              │                │                   │
              └────────────────┼───────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │    Repositories     │
                    │ (tenant-scoped SQL) │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  SQLite (WAL mode)  │
                    └─────────────────────┘
```

### Request Flow

1. Every tenant-scoped request hits `/tenants/{tenant_id}/...`
2. The `get_current_tenant` middleware validates the tenant exists (404 if not), checks rate limits (429 if exceeded), and injects a `TenantContext`
3. Route handlers delegate to service functions, passing `tenant_id` as a required parameter
4. Repositories construct all SQL with `WHERE tenant_id = ?` — no unscoped queries exist
5. Responses never echo back PII; only hashed identifiers are returned

### Background Job System

The `ingestion_jobs` table **is** the job queue — no Redis or Celery required. On startup, the app launches an async worker pool (3 workers by default) that poll the table for queued jobs.

- **Atomic claiming**: Workers claim jobs via `UPDATE ... RETURNING` with SQLite's single-writer guarantee preventing double-pickup
- **Fair scheduling**: The claim query prioritizes tenants with fewer active jobs, then FIFO — preventing any single tenant from monopolizing workers
- **Graceful lifecycle**: Stale `in_progress` jobs are reset to `queued` on startup (safe because ingestion is idempotent via dedup). Workers get a 30-second grace period on shutdown
- **Auto-refresh**: A periodic timer checks tenant staleness and re-creates ingestion jobs for previously completed queries

## Key Design Decisions

### Four-Layer Tenant Isolation

Tenant isolation is enforced redundantly — a failure at any single layer cannot cause cross-tenant data exposure:

| Layer | Mechanism | What It Prevents |
| ----- | --------- | ---------------- |
| **URL path** | `{tenant_id}` in every tenant-scoped route | Missing tenant context (404 on bad segment) |
| **Middleware** | `get_current_tenant` validates existence, injects context | Requests against non-existent tenants |
| **Repository** | `tenant_id` required on every method, every query has `WHERE tenant_id = ?` | Developer forgets to scope a query |
| **Database** | FK constraints, composite unique indexes leading with `tenant_id` | Orphaned or cross-tenant data at the storage level |

Cross-tenant resource access returns **404** (not 403) to avoid confirming that a resource exists under another tenant.

### PII Protection via HMAC-SHA256

Patron name and email are the only PII fields. They are irreversibly hashed in the service layer before reaching the repository — the database has no plaintext PII columns.

- **HMAC over plain SHA-256** prevents rainbow table attacks on low-entropy emails
- **Normalization before hashing** (lowercase, strip whitespace, collapse spaces for names) ensures deterministic hashes for deduplication
- **Secret key** loaded from `TITANAI_PII_SECRET_KEY` env var, min 32 bytes enforced at startup — app refuses to start without it
- PII never appears in database columns, logs, error messages, API responses, or debug output

### Open Library Integration

The ingestion pipeline assembles complete book records from multiple OL endpoints since no single response contains all fields:

1. Search by author/subject → list of work keys
2. Per work → `/works/{id}.json` → title, subjects
3. Per work → extract author keys → `/authors/{id}.json` → author names
4. Per work → construct cover URL from cover IDs

A global rate limiter (`asyncio.Semaphore` at 2 req/sec) is shared across all workers. Retries use exponential backoff for 429/5xx responses. Individual work failures don't abort the job — partial success is the norm.

### SQLite as the Only Datastore

SQLite with WAL mode provides concurrent reads during writes, which is sufficient for this workload. Key conventions:

- **UUIDs as TEXT** — generated application-side (36-char strings)
- **Timestamps as ISO 8601 TEXT** — lexicographic sorting, compatible with SQLite date functions
- **JSON arrays in TEXT columns** — `authors` and `subjects` stored as JSON, queryable via `LIKE` for keyword search
- **`PRAGMA foreign_keys=ON`** enforced on every connection to maintain referential integrity

### Database-Backed Job Queue

The `ingestion_jobs` table doubles as the job queue rather than adding Redis or Celery. This keeps the deployment to a single process with zero external infrastructure. SQLite's single-writer guarantee makes atomic job claiming trivial, and WAL mode ensures API reads aren't blocked during job processing.
