# TitanAI — Risk Mitigations

---

## External Dependency: Open Library API

| Risk                                                                   | Impact                                 | Mitigation                                                                                                                               |
| ---------------------------------------------------------------------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| API goes down for extended period                                      | Ingestion stalls, catalogs go stale    | Exponential backoff with bounded retries. Jobs fail gracefully with clear activity log entries. Existing catalog data remains queryable. |
| Rate limits tightened or enforced more aggressively                    | Ingestion slows significantly          | Global rate limiter is configurable (`OL_RATE_LIMIT_PER_SECOND`). User-Agent header identifies the service for higher limits.            |
| Response schema changes without notice                                 | Record assembly breaks, missing fields | Defensive parsing — treat every field as optional. Log warnings for unexpected shapes rather than crashing.                              |
| Data quality degresses (fields removed, inconsistent across endpoints) | Stored records lose data               | Version management preserves prior values on regression (FR-022). Never nullify a field that previously had a value.                     |

## Data & Security

| Risk                       | Impact                                                | Mitigation                                                                                                                                                             |
| -------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PII secret key leaked      | Patron email hashes become reversible via brute force | Key stored only in env var, never in code/config/logs. Minimum 256-bit key enforced at startup. Key rotation procedure documented (accepts deduplication break).       |
| Cross-tenant data leakage  | Privacy violation, trust destruction                  | Four-layer enforcement (route, middleware, repository, database). Every endpoint has a cross-tenant leakage test. Resource access across tenants returns 404, not 403. |
| SQLite database corruption | Data loss                                             | WAL mode reduces corruption risk. Regular backups recommended. Application-level writes are idempotent (re-ingestion is safe).                                         |

## Performance & Scalability

| Risk                                                     | Impact                              | Mitigation                                                                                                                                               |
| -------------------------------------------------------- | ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SQLite write contention under load                       | Slow ingestion, API timeouts        | WAL mode enables concurrent reads during writes. Worker count capped at 3 (writes are sequential anyway). Background jobs never block API reads.         |
| Single-tenant monopolizes resources                      | Other tenants degraded              | Per-tenant job concurrency limit. Fair scheduling prioritizes tenants with fewer active jobs. Per-tenant API rate limiting.                              |
| Large ingestion (popular author with thousands of works) | Job runs for hours, progress stalls | Progress tracked per-work. Partial success model — completed works are available immediately. Job can be resumed after crash (idempotent re-processing). |

## Operational

| Risk                                       | Impact                                      | Mitigation                                                                                                            |
| ------------------------------------------ | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Process crash mid-ingestion                | Jobs stuck in `in_progress` forever         | Stale job recovery on startup resets `in_progress` → `queued`. Idempotent re-processing via deduplication constraint. |
| Auto-refresh creates unbounded job backlog | Queue grows faster than workers can process | Refresh deduplication prevents duplicate jobs. Only re-runs previously completed queries, not new ones.               |
| Missing or misconfigured env vars          | App fails at runtime in unexpected ways     | Pydantic Settings validates all required config at startup. App refuses to start without `TITANAI_PII_SECRET_KEY`.    |
