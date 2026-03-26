# TitanAI — Background Job System

Catalog ingestion must never block API responses (Constitution §III). This document defines how background job
processing works, including the job lifecycle, worker architecture, retry strategy, automatic refresh, and per-tenant
fairness.

---

## Why Not Celery/Redis/RQ?

This project uses SQLite and targets a single-deployment model. Introducing a message broker (Redis, RabbitMQ) and a
framework like Celery would add significant infrastructure complexity for a problem that can be solved with simpler
tools:

- The `ingestion_jobs` table already exists in the data model — it **is** the job queue.
- Python's `asyncio` with background tasks provides in-process concurrency.
- SQLite with WAL mode supports concurrent reads and writes.

The design uses a **database-backed job queue** with in-process async workers. This can be migrated to a dedicated
broker later if the system outgrows a single deployment.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                    FastAPI Process                    │
│                                                      │
│  ┌──────────┐    ┌───────────────┐    ┌───────────┐ │
│  │ API      │    │ Job Scheduler │    │ Worker    │ │
│  │ Handlers │───▶│ (enqueue)     │    │ Pool      │ │
│  └──────────┘    └───────┬───────┘    └─────┬─────┘ │
│                          │                  │        │
│                          ▼                  │        │
│                  ┌───────────────┐          │        │
│                  │ ingestion_jobs│◀─────────┘        │
│                  │ table (queue) │                    │
│                  └───────────────┘                    │
│                          │                           │
│                          ▼                           │
│                  ┌───────────────┐                    │
│                  │ Refresh Timer │                    │
│                  │ (periodic)    │                    │
│                  └───────────────┘                    │
└─────────────────────────────────────────────────────┘
                           │
                           ▼
                   Open Library API
```

**Components:**

1. **API Handlers** — Accept ingestion requests, insert a job row, return immediately.
2. **Worker Pool** — Async background tasks that poll for queued jobs and execute them.
3. **Refresh Timer** — Periodic task that creates auto-refresh jobs for tenants whose catalogs are stale.
4. **ingestion_jobs table** — The durable job queue. State is persisted, not in-memory.

---

## Job Lifecycle

```
            POST /tenants/{id}/ingestion/jobs
                        │
                        ▼
                    ┌────────┐
                    │ queued │  ← Job row inserted, API returns 202
                    └───┬────┘
                        │  Worker picks up job
                        ▼
                  ┌─────────────┐
                  │ in_progress │  ← started_at set, progress tracked
                  └──────┬──────┘
                         │
                    ┌────┴────┐
                    ▼         ▼
              ┌───────────┐ ┌────────┐
              │ completed │ │ failed │  ← completed_at set, activity log written
              └───────────┘ └────────┘
```

### State Transitions

| From          | To            | Trigger                                                                   |
| ------------- | ------------- | ------------------------------------------------------------------------- |
| —             | `queued`      | API handler inserts job row                                               |
| `queued`      | `in_progress` | Worker claims the job                                                     |
| `in_progress` | `completed`   | All works processed (some may have failed individually)                   |
| `in_progress` | `failed`      | Unrecoverable error (e.g., Open Library down after all retries exhausted) |

A job is `completed` even if some individual works failed — the job itself succeeded in running to completion. The
`succeeded` and `failed` counters on the job record distinguish partial success from full success. A job is `failed`
only if the entire operation could not proceed (e.g., network unreachable after all retries).

---

## Worker Pool

### Implementation: asyncio Background Tasks

Workers run as `asyncio.Task` instances within the FastAPI process, started on application startup and cancelled on
shutdown.

```
on_startup:
    start N worker tasks
    start 1 refresh timer task

on_shutdown:
    cancel all worker tasks (allow graceful completion of current work)
    cancel refresh timer
```

### Worker Loop

Each worker runs an infinite loop:

```
while True:
    job = claim_next_job()      # Atomic: UPDATE ... SET status='in_progress' WHERE status='queued'
    if job is None:
        await sleep(poll_interval)  # No work available, back off
        continue
    try:
        await execute_ingestion(job)
        mark_completed(job)
    except UnrecoverableError:
        mark_failed(job)
    finally:
        write_activity_log(job)
```

### Job Claiming (Atomic)

To prevent two workers from picking up the same job, claiming uses an atomic UPDATE:

```sql
UPDATE ingestion_jobs
SET status = 'in_progress', started_at = ?
WHERE id = (
    SELECT id FROM ingestion_jobs
    WHERE status = 'queued'
    ORDER BY created_at ASC
    LIMIT 1
)
RETURNING *
```

SQLite's single-writer guarantee means this is inherently serialized — no explicit locking needed. Only one worker will
successfully claim each job.

### Worker Count

The default worker count is **3**. This is tunable via configuration. The limit is driven by Open Library's rate limits
(1-3 req/sec), not CPU — more workers would just compete for the same rate limit budget.

### Poll Interval

Workers poll every **2 seconds** when idle. This is a tradeoff between responsiveness (how quickly a queued job starts)
and unnecessary database queries. Two seconds is imperceptible to a user who just submitted an ingestion request.

---

## Ingestion Execution

When a worker executes an ingestion job, it follows this flow:

```
execute_ingestion(job):
    1. Fetch initial results from Open Library
       - Author query:  GET /search.json?author={value}&limit=100
       - Subject query:  GET /subjects/{value}.json?limit=100

    2. Update job: total_works = len(results)

    3. For each work in results:
       a. Check if work already exists in tenant's catalog
          - If exists and version management enabled: compare and version
          - If exists and no changes: skip

       b. Assemble complete record:
          - Extract title, first_publish_year, subjects from search result
          - If author names missing: GET /authors/{key}.json
          - If cover needed: construct cover URL from cover_i field

       c. Store book (or create new version)

       d. Update job progress:
          UPDATE ingestion_jobs
          SET processed_works = processed_works + 1,
              succeeded = succeeded + 1  -- or failed + 1
          WHERE id = ?

       e. Rate limit: await sleep between Open Library requests

    4. Mark job completed
    5. Write activity log entry
```

### Rate Limiting Open Library Requests

Open Library allows ~1 req/sec unidentified, ~3 req/sec with a User-Agent header. The ingestion worker enforces a global
rate limiter shared across all workers:

```
Global rate limiter:
    max_requests_per_second = 2  (conservative, with User-Agent)
    implemented as asyncio.Semaphore + minimum delay between releases
```

This is **global**, not per-tenant — Open Library rate limits apply to the entire service, regardless of which tenant
triggered the request. All workers share the same limiter to avoid exceeding the global budget.

### User-Agent Header

All requests to Open Library include a `User-Agent` header identifying the service and providing a contact email, as
recommended by their API docs:

```
User-Agent: TitanAI/0.1.0 (contact@example.com)
```

---

## Retry Strategy

Retries operate at two levels: **per-request** (individual Open Library API calls) and **per-work** (assembling a
complete book record).

### Per-Request Retries (HTTP Level)

| Condition                        | Action                                                                          |
| -------------------------------- | ------------------------------------------------------------------------------- |
| HTTP 429 (rate limited)          | Wait for `Retry-After` header value (or 5s default), then retry. Max 3 retries. |
| HTTP 5xx (server error)          | Exponential backoff: 1s → 2s → 4s. Max 3 retries.                               |
| Connection timeout               | Treat as 5xx — same backoff. Timeout set to 10s per request.                    |
| HTTP 4xx (client error, not 429) | Do not retry — log the error and mark this work as failed.                      |

### Per-Work Retries

If assembling a complete record fails (e.g., follow-up author request fails after HTTP retries exhausted), the
individual work is marked as failed in the job's error list. The job continues processing remaining works — one bad
record does not abort the entire job.

### Job-Level Failure

A job is marked `failed` only if:

- The initial search request fails after all retries (no results to process at all).
- An unrecoverable error occurs (e.g., invalid tenant, database write failure).

Partial success (some works stored, some failed) results in `completed` status with `failed > 0`.

---

## Automatic Refresh (FR-020)

A periodic background task creates re-ingestion jobs for tenants whose catalogs are stale.

### Refresh Timer

```
refresh_timer():
    while True:
        await sleep(check_interval)  # e.g., every 15 minutes

        for tenant in get_all_tenants():
            last_ingestion = get_latest_completed_job(tenant.id)

            if last_ingestion is None:
                continue  # Never ingested — nothing to refresh

            hours_since = now - last_ingestion.completed_at

            if hours_since >= tenant.ingestion_refresh_hours:
                # Re-create the same ingestion job
                create_job(
                    tenant_id = tenant.id,
                    query_type = last_ingestion.query_type,
                    query_value = last_ingestion.query_value,
                    is_auto_refresh = True
                )
```

### Refresh Behavior

- Only tenants with at least one completed ingestion are refreshed — the system does not invent queries.
- The refresh re-runs the **most recent completed job** for each tenant. If a tenant has ingested multiple
  authors/subjects, each unique (query_type, query_value) pair is refreshed.
- Auto-refresh jobs are marked with `is_auto_refresh = 1` to distinguish them from manual ingestion in the activity log.
- The refresh interval is per-tenant (`tenants.ingestion_refresh_hours`), defaulting to 24 hours.
- If a refresh job is already queued or in-progress for the same tenant and query, a duplicate is not created.

### Deduplication of Refresh Jobs

Before creating a refresh job, check:

```sql
SELECT 1 FROM ingestion_jobs
WHERE tenant_id = ?
  AND query_type = ?
  AND query_value = ?
  AND status IN ('queued', 'in_progress')
LIMIT 1
```

If a matching job exists, skip — no duplicate.

---

## Per-Tenant Fairness (Noisy Neighbor Prevention)

Without fairness controls, a tenant that submits 50 ingestion jobs would monopolize all workers while other tenants
wait.

### Concurrent Job Limit Per Tenant

Each tenant is limited to **N concurrent jobs** (default: 2). This is enforced at two points:

1. **At submission time** — When `POST .../ingestion/jobs` is called, check how many jobs for this tenant are in
   `queued` or `in_progress` status. If the limit is reached, respond with **429 Too Many Requests** and a message
   indicating the tenant's job queue is full.

2. **At worker claim time** — The job claiming query favors tenants with fewer active jobs:

```sql
UPDATE ingestion_jobs
SET status = 'in_progress', started_at = ?
WHERE id = (
    SELECT j.id FROM ingestion_jobs j
    WHERE j.status = 'queued'
    ORDER BY
        (SELECT COUNT(*) FROM ingestion_jobs j2
         WHERE j2.tenant_id = j.tenant_id
           AND j2.status = 'in_progress') ASC,  -- Fewest active jobs first
        j.created_at ASC                          -- Then FIFO
    LIMIT 1
)
RETURNING *
```

This ensures a tenant with zero active jobs gets priority over a tenant that already has one running — even if the
second tenant's job was queued first.

### Open Library Rate Limit Budget

The global rate limiter (2 req/sec to Open Library) is shared across all workers and tenants. No single tenant's job can
monopolize the rate budget because:

- Workers interleave work item processing — a worker picks up a job, processes one work (1-3 API calls), then yields to
  the rate limiter before the next work.
- The rate limiter is a shared async semaphore — all workers compete equally for request slots.

---

## Progress Tracking

Job progress is updated in the database after each work is processed:

```sql
UPDATE ingestion_jobs
SET processed_works = processed_works + 1,
    succeeded = succeeded + 1  -- or failed = failed + 1
WHERE id = ?
```

The status endpoint (`GET .../ingestion/jobs/{job_id}`) returns:

```json
{
  "id": "...",
  "status": "in_progress",
  "query_type": "author",
  "query_value": "Octavia Butler",
  "total_works": 25,
  "processed_works": 12,
  "succeeded": 11,
  "failed": 1,
  "errors": [{ "work_id": "/works/OL123W", "error": "Author endpoint returned 500" }],
  "created_at": "2026-03-25T14:30:00Z",
  "started_at": "2026-03-25T14:30:02Z",
  "completed_at": null
}
```

Clients can poll this endpoint to track progress. A simple progress percentage is `processed_works / total_works`.

---

## Activity Log Creation

When a job reaches a terminal state (`completed` or `failed`), the worker writes an activity log entry:

```sql
INSERT INTO activity_logs (id, tenant_id, job_id, query_type, query_value,
                           total_fetched, succeeded, failed, errors, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

This is the final step in the job lifecycle. The activity log is append-only and immutable — once written, it is never
modified.

---

## Graceful Shutdown

On application shutdown (SIGTERM/SIGINT):

1. **Stop accepting new jobs** — The refresh timer stops creating new jobs.
2. **Let in-progress work complete** — Workers are given a grace period (e.g., 30 seconds) to finish their current work
   item (not the entire job — just the current API call and database write).
3. **Re-queue interrupted jobs** — Any job in `in_progress` that was not completed is reset to `queued` so it will be
   picked up on the next startup:

```sql
UPDATE ingestion_jobs
SET status = 'queued', started_at = NULL
WHERE status = 'in_progress'
```

This runs on startup, not shutdown — it's a recovery mechanism that handles both graceful shutdown and crashes.

---

## Stale Job Recovery

On application startup, before workers begin polling:

```sql
-- Reset any jobs that were in-progress when the process last stopped
UPDATE ingestion_jobs
SET status = 'queued', started_at = NULL
WHERE status = 'in_progress'
```

This handles:

- Graceful shutdown where the grace period expired before a job finished.
- Process crashes or OOM kills.
- Server restarts.

The job will be re-processed from the beginning. Since book ingestion is idempotent (duplicate works are detected by the
`UNIQUE(tenant_id, ol_work_id)` constraint), re-processing a partially completed job is safe — already-stored books will
be skipped or versioned.

---

## Configuration Summary

| Setting                          | Default | Source           | Notes                                                 |
| -------------------------------- | ------- | ---------------- | ----------------------------------------------------- |
| `WORKER_COUNT`                   | 3       | Env var / config | Number of concurrent worker tasks                     |
| `POLL_INTERVAL_SECONDS`          | 2       | Config           | How often idle workers check for jobs                 |
| `OL_RATE_LIMIT_PER_SECOND`       | 2       | Config           | Global Open Library request rate                      |
| `OL_REQUEST_TIMEOUT_SECONDS`     | 10      | Config           | Per-request timeout to Open Library                   |
| `MAX_RETRIES_PER_REQUEST`        | 3       | Config           | HTTP-level retries                                    |
| `MAX_CONCURRENT_JOBS_PER_TENANT` | 2       | Config           | Noisy neighbor limit                                  |
| `REFRESH_CHECK_INTERVAL_MINUTES` | 15      | Config           | How often the refresh timer checks for stale catalogs |
| `SHUTDOWN_GRACE_SECONDS`         | 30      | Config           | Time to wait for in-progress work on shutdown         |

---

## Summary of Design Decisions

1. **Database-backed queue, not a message broker.** The `ingestion_jobs` table is the queue. Avoids Redis/Celery
   complexity for a single-deployment SQLite system.
2. **In-process async workers.** `asyncio.Task` instances within the FastAPI process. No separate worker processes.
3. **Atomic job claiming via SQL.** SQLite's single-writer guarantee prevents double-pickup without explicit locking.
4. **Global Open Library rate limiter.** Shared across all workers and tenants — the limit is on the external API, not
   per-tenant.
5. **Per-tenant concurrent job limit.** Prevents noisy neighbors from monopolizing workers. Fair scheduling prioritizes
   tenants with fewer active jobs.
6. **Partial success is success.** A job that processes 23/25 works is `completed` with `failed=2`, not `failed`.
7. **Idempotent re-processing.** Stale jobs are reset to `queued` on startup. Deduplication and versioning make
   re-ingestion safe.
8. **Auto-refresh via periodic timer.** Re-runs the most recent completed query per tenant. No duplicate refresh jobs
   created.
