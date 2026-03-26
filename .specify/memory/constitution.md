# TitanAI Constitution

## Core Principles

### I. Tenant Isolation (NON-NEGOTIABLE)

Every API operation, database query, and background job is scoped to a single tenant. Tenant data must never leak across boundaries — one library's catalog, reading lists, and activity logs are invisible to another. Isolation is enforced at the data layer, not just the API layer. All queries include tenant context; there are no global/unscoped data access paths.

### II. PII Protection (NON-NEGOTIABLE)

Personally identifiable information (patron name, email) must be irreversibly hashed before persistence. No PII is ever stored in plaintext. Hashing must be deterministic enough to support deduplication (same email → same hash) but irreversible. PII handling logic is centralized in a single module — no ad-hoc hashing scattered across the codebase.

### III. Async-First Ingestion

Catalog ingestion from Open Library never blocks API responses. All ingestion runs as background jobs with progress tracking and status visibility. The system respects Open Library's rate limits and handles API unreliability (timeouts, partial data, missing fields) gracefully. Follow-up requests to resolve incomplete records are expected, not exceptional.

### IV. Live API Integration

The service calls the live Open Library API — no hard-coded or cached sample responses as test fixtures. Open Library data is inconsistent and incomplete by nature; the ingestion pipeline must handle missing fields, varying response shapes, and data regression without failing. Integration tests hit real endpoints.

### V. Observability & Auditability

Every ingestion operation is logged: what was requested, results count, successes, failures, timestamps, and errors. Activity logs are tenant-scoped and API-accessible. Background job status is queryable. The system provides visibility into per-tenant resource consumption.

### VI. Data Integrity & Versioning

When re-ingesting a previously stored work, metadata changes create new versions rather than overwriting. Version history is preserved and API-accessible. The system handles data regression (fields present in older versions but missing in newer fetches) by retaining prior values rather than nullifying them.

### VII. Fair Resource Sharing

No single tenant can monopolize shared resources (API rate limits, job queue capacity, database connections). Throttling is per-tenant. Heavy usage by one tenant must not degrade service for others.

## Technical Constraints

- **Language**: Python 3.13, managed with `uv`
- **Architecture**: Multi-tenant REST API service with background job processing
- **External dependency**: Open Library public API (no API key required, rate-limited)
- **Data assembly**: A single Open Library API response may not contain all required fields — the ingestion pipeline must compose complete records from multiple endpoints (works, authors, covers)
- **Required book fields**: title, author name(s), first publish year, subjects, cover image URL (when available)

## Quality Gates

- All new features must include tests
- Tenant isolation must be verified in tests — cross-tenant data access is a test failure
- PII must never appear in logs, error messages, or API responses
- Background jobs must be idempotent and resumable
- API endpoints must support pagination

## Governance

This constitution governs all development decisions for TitanAI. Principles I (Tenant Isolation) and II (PII Protection) are non-negotiable and override convenience or velocity concerns. All other principles should be followed unless there is a documented, justified reason to deviate. Amendments require updating this document and reviewing downstream impact.

**Version**: 1.0.0 | **Ratified**: 2026-03-25 | **Last Amended**: 2026-03-25
