# Quickstart: Multi-Tenant Library Catalog Service

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

## Setup

```bash
# Clone and enter the project
cd titanai

# Install dependencies
uv sync

# Set required environment variable (PII hashing key, min 32 bytes)
export TITANAI_PII_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
```

## Run

```bash
# Start the server
uv run uvicorn titanai.main:app --reload

# Or via Makefile (when available)
make run
```

The server starts at `http://localhost:8000`. OpenAPI docs at `http://localhost:8000/docs`.

## Quick Test

```bash
# 1. Create a tenant
curl -X POST http://localhost:8000/tenants \
  -H "Content-Type: application/json" \
  -d '{"name": "Springfield Public Library", "slug": "springfield"}'

# 2. Trigger an ingestion (replace TENANT_ID)
curl -X POST http://localhost:8000/tenants/TENANT_ID/ingestion/jobs \
  -H "Content-Type: application/json" \
  -d '{"query_type": "author", "query_value": "Octavia Butler"}'

# 3. Check job status (replace TENANT_ID and JOB_ID)
curl http://localhost:8000/tenants/TENANT_ID/ingestion/jobs/JOB_ID

# 4. Browse the catalog
curl http://localhost:8000/tenants/TENANT_ID/books

# 5. Search by keyword
curl "http://localhost:8000/tenants/TENANT_ID/books?q=kindred"
```

## Run Tests

```bash
# All tests
uv run pytest

# Single test file
uv run pytest tests/test_books.py

# With verbose output
uv run pytest -v

# Only isolation tests
uv run pytest tests/test_isolation.py
```

## Environment Variables

| Variable                | Required | Default | Description                       |
| ----------------------- | -------- | ------- | --------------------------------- |
| `TITANAI_PII_SECRET_KEY`| Yes      | —       | HMAC key for PII hashing (min 32 bytes) |
| `TITANAI_DB_PATH`       | No       | `titanai.db` | SQLite database file path    |
| `WORKER_COUNT`          | No       | 3       | Background worker tasks           |
| `OL_RATE_LIMIT_PER_SECOND` | No   | 2       | Open Library rate limit           |

## Project Layout

```
src/titanai/
├── api/          # FastAPI routers
├── db/           # SQLite connection, schema, repositories
├── services/     # Business logic (ingestion, PII, versions)
├── models/       # Pydantic request/response schemas
├── core/         # Config, PII hashing module
└── workers/      # Background job system
```
