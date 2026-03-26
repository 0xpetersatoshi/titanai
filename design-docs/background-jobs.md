# TitanAI — Background Job System

Catalog ingestion must never block API responses (Constitution §III). The `ingestion_jobs` table **is** the job queue —
no Celery/Redis needed. In-process `asyncio.Task` workers poll the table and execute jobs. SQLite WAL mode enables
concurrent reads during writes.

## Job Lifecycle

`queued` → `in_progress` → `completed` | `failed`

- **queued**: API handler inserts row, returns 202 with job ID immediately.
- **in_progress**: Worker claims job via atomic SQL UPDATE. Progress tracked per-work.
- **completed**: All works processed (even if some individually failed). `succeeded`/`failed` counters distinguish
  partial success.
- **failed**: Only if the entire operation couldn't proceed (e.g., OL unreachable after all retries).

## Worker Pool

- **3 async workers** (configurable) as `asyncio.Task` instances, started on app startup, cancelled on shutdown.
- Workers poll every **2 seconds** when idle.
- **Atomic job claiming** — SQLite's single-writer guarantee prevents double-pickup:

```sql
UPDATE ingestion_jobs SET status = 'in_progress', started_at = ?
WHERE id = (SELECT id FROM ingestion_jobs WHERE status = 'queued'
            ORDER BY created_at ASC LIMIT 1)
RETURNING *
```

## Ingestion Flow

1. Fetch results from Open Library (author search or subject endpoint)
2. For each work: check dedup → assemble record (follow-up requests for missing fields) → store → update progress
3. Mark job completed, write activity log entry

## Rate Limiting & Retries

**Global OL rate limiter**: 2 req/sec shared across all workers via `asyncio.Semaphore`. All requests include
`User-Agent: TitanAI/0.1.0 (contact@example.com)`.

| Condition          | Action                                            |
| ------------------ | ------------------------------------------------- |
| HTTP 429           | Wait `Retry-After` (or 5s default), max 3 retries |
| HTTP 5xx / timeout | Exponential backoff: 1s → 2s → 4s, max 3 retries  |
| HTTP 4xx (not 429) | No retry — mark work as failed, continue to next  |

Individual work failures don't abort the job. A job is `failed` only if the initial search itself fails or an
unrecoverable error occurs.

## Automatic Refresh (FR-020)

A periodic timer (every 15 min) checks each tenant's staleness against `tenants.ingestion_refresh_hours` (default 24h).
For stale tenants, it re-creates jobs for each previously completed (query_type, query_value) pair, marked
`is_auto_refresh = 1`. Duplicate jobs (same tenant + query already queued/in-progress) are skipped.

## Per-Tenant Fairness

- **Concurrent job limit**: Max 2 jobs per tenant (queued + in-progress). Exceeding returns 429.
- **Fair scheduling**: Workers claim jobs prioritizing tenants with fewer active jobs, then FIFO:

```sql
ORDER BY (SELECT COUNT(*) FROM ingestion_jobs j2
          WHERE j2.tenant_id = j.tenant_id AND j2.status = 'in_progress') ASC,
         j.created_at ASC
```

## Recovery & Shutdown

- **Startup**: Reset all `in_progress` jobs to `queued` (handles crashes, restarts). Safe because ingestion is
  idempotent (dedup constraint).
- **Shutdown**: 30s grace period for current work item, then cancel. Incomplete jobs recovered on next startup.

## Configuration

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
