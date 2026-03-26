# Implementation Plan: Multi-Tenant Library Catalog Service

**Branch**: `001-multi-tenant-catalog` | **Date**: 2026-03-25 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-multi-tenant-catalog/spec.md`

## Summary

A multi-tenant catalog service for a consortium of public libraries that aggregates book data from Open Library and makes
it searchable and browsable. The system uses FastAPI with async SQLite for zero-infrastructure deployment, HMAC-SHA256
for PII protection, and an in-process asyncio job runner backed by the SQLite job table for background ingestion.

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: FastAPI, uvicorn, httpx (async HTTP), pydantic v2, pydantic-settings, aiosqlite
**Storage**: SQLite via aiosqlite (WAL mode, `PRAGMA foreign_keys=ON`)
**Testing**: pytest + pytest-asyncio + httpx (AsyncClient for API tests)
**Target Platform**: Linux server (single deployment)
**Project Type**: web-service (REST API, backend only)
**Performance Goals**: Ingestion requests acknowledged within 2 seconds; no single tenant causes >2x latency for others
**Constraints**: Single-process deployment, SQLite single-writer, Open Library rate limit ~2 req/sec with User-Agent
**Scale/Scope**: Multiple library tenants, thousands of books per tenant, 8 database tables

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How Addressed |
|-----------|--------|---------------|
| I. Tenant Isolation (NON-NEGOTIABLE) | PASS | 4-layer enforcement: path params, middleware validation + TenantContext injection, mandatory tenant_id on all repository methods, FK constraints + composite indexes. Cross-tenant returns 404 not 403. |
| II. PII Protection (NON-NEGOTIABLE) | PASS | HMAC-SHA256 with server-side secret (`TITANAI_PII_SECRET_KEY`, min 256 bits). Centralized hashing module. PII never reaches repository layer. No plaintext in DB, logs, errors, or responses. |
| III. Async-First Ingestion | PASS | In-process asyncio worker pool (3 tasks). `POST .../ingestion/jobs` returns 202 immediately. DB-backed job queue with atomic claiming. |
| IV. Live API Integration | PASS | httpx AsyncClient calls live Open Library API. User-Agent header set. No hardcoded fixtures. Defensive parsing for inconsistent responses. |
| V. Observability & Auditability | PASS | Activity logs (denormalized from jobs), job status endpoint with progress, per-tenant metrics endpoint. |
| VI. Data Integrity & Versioning | PASS | book_versions table with immutable snapshots, field-level diffs, regression detection and preservation. |
| VII. Fair Resource Sharing | PASS | Per-tenant API rate limiting (fixed-window), per-tenant job concurrency limit (max 2), fair scheduling SQL. |

**Quality Gates**:
- All features include tests (cross-tenant leakage, PII, integration) — PASS
- Tenant isolation verified in tests — PASS
- PII never in logs/errors/responses — PASS
- Background jobs idempotent (dedup constraint) and resumable (stale recovery on startup) — PASS
- All list endpoints support pagination (offset/limit) — PASS

**No violations. No complexity tracking needed.**

## Project Structure

### Documentation (this feature)

```text
specs/001-multi-tenant-catalog/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (API contracts)
├── checklists/          # Quality checklists
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
src/titanai/
├── __init__.py
├── main.py              # FastAPI app factory, lifespan handler
├── api/                 # FastAPI routers
│   ├── tenants.py       # Tenant CRUD
│   ├── books.py         # Catalog retrieval & search
│   ├── ingestion.py     # Ingestion jobs & activity logs
│   ├── reading_lists.py # Reading list submissions
│   ├── metrics.py       # Tenant & aggregate metrics
│   └── dependencies.py  # get_current_tenant, rate limit check
├── db/                  # Database layer
│   ├── connection.py    # SQLite connection factory (WAL, FK)
│   ├── schema.py        # Table creation DDL
│   └── repositories/    # Tenant-scoped data access
│       ├── tenants.py
│       ├── books.py
│       ├── book_versions.py
│       ├── ingestion_jobs.py
│       ├── activity_logs.py
│       ├── reading_lists.py
│       └── tenant_metrics.py
├── services/            # Business logic
│   ├── ingestion.py     # Orchestrates OL → assemble → dedup → store
│   ├── openlibrary.py   # Async HTTP client for Open Library API
│   ├── reading_lists.py # Book resolution, PII handoff
│   └── versions.py      # Field comparison, regression detection
├── models/              # Pydantic schemas (request/response)
│   ├── tenants.py
│   ├── books.py
│   ├── ingestion.py
│   ├── reading_lists.py
│   └── pagination.py
├── core/                # Config, constants, shared utilities
│   ├── config.py        # Pydantic Settings (env vars)
│   └── pii.py           # Centralized HMAC-SHA256 hashing module
└── workers/             # Background job system
    ├── pool.py          # Worker lifecycle, startup/shutdown
    ├── ingestion.py     # Job execution logic
    └── refresh.py       # Automatic refresh timer

tests/
├── conftest.py          # Fixtures: test DB, async client, tenant helper
├── test_tenants.py
├── test_ingestion.py
├── test_books.py
├── test_reading_lists.py
├── test_activity_logs.py
├── test_versions.py
├── test_metrics.py
├── test_pii.py          # PII-specific tests (no plaintext, deterministic, normalization)
└── test_isolation.py    # Cross-tenant leakage tests for all endpoints
```

**Structure Decision**: Single web-service project. All code under `src/titanai/` with layered architecture: API routers
→ services → repositories → SQLite. Background workers are in-process asyncio tasks, not a separate service.
