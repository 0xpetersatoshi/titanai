# TitanAI — Tenant Isolation Strategy

Tenant isolation is **non-negotiable** (Constitution §I). Isolation is enforced redundantly across four layers — a
failure at any one layer should not result in cross-tenant data exposure.

## Layer 1: API Route Design

Every tenant-scoped endpoint lives under `/tenants/{tenant_id}/...`. Tenant ID is a **path parameter**, not a header —
URLs are self-describing in logs/monitoring, and a missing segment is a 404, not a silent default.

**Routes without tenant prefix** (admin only): `POST /tenants`, `GET /tenants`, `GET /metrics`.

## Layer 2: Middleware — Validation & Context

FastAPI dependency `get_current_tenant` runs on every tenant-scoped route:

1. **Validate** tenant exists in DB → 404 if not found (no downstream code runs)
2. **Inject** `TenantContext` (ID + config) via dependency injection — handlers never extract tenant_id from path
3. **Rate limit** check against `tenant_metrics` → 429 if exceeded

**Key rule**: All service/repository functions require `tenant_id` as a non-optional parameter.

## Layer 3: Repository — Query Scoping

The repository layer is the **only** code that constructs SQL. Tenant scoping is a structural guarantee:

- **Mandatory `tenant_id` parameter** on every method. No "get all across tenants" methods exist.
- **Every query includes `WHERE tenant_id = ?`** — SELECT, UPDATE, DELETE. Not optional.
- **Composite lookups** use both resource ID and tenant ID: `WHERE id = ? AND tenant_id = ?`
- **Cross-resource queries** scope the root table; FK relationships guarantee child records belong to the same tenant.
- **Background jobs** carry `tenant_id` from the job record through to all repository calls. No shared state.

## Layer 4: Database Constraints

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

## Testing Strategy

**Cross-tenant leakage**: For every data-returning endpoint — create tenants A and B, populate A, query as B, assert
zero results from A. Covers: books, versions, jobs, logs, reading lists, metrics.

**Direct ID access**: For every single-resource endpoint — create resource under tenant A, request it under tenant B's
path, assert **404** (not 403 — never confirm a resource exists under another tenant).

**Background job isolation**: Trigger ingestion for tenant A, verify books and activity logs are only visible to A.

## Failure Modes

| Failure                                | Mitigation                                                                   |
| -------------------------------------- | ---------------------------------------------------------------------------- |
| Developer forgets `WHERE tenant_id`    | Repository pattern makes tenant_id required — code won't run without it      |
| Request with wrong tenant_id           | Middleware validates existence; composite queries prevent UUID cross-access  |
| Job processes wrong tenant's data      | Job carries tenant_id; all repository calls use it                           |
| SQL injection bypasses tenant filter   | Parameterized queries only — no string interpolation                         |
| New table added without tenant scoping | Review checklist: every user-data table needs tenant_id FK or scoped parent  |
| Admin endpoint exposes tenant data     | Admin endpoints return only aggregate/metadata, never catalog or patron data |

## Rules

1. Every tenant-scoped URL includes `{tenant_id}` in the path
2. Middleware validates tenant existence before any business logic — invalid tenant = 404
3. Every repository method requires `tenant_id` — no unscoped query methods
4. Every SQL query includes `WHERE tenant_id = ?` — composite lookups use both resource ID and tenant ID
5. Cross-tenant resource access returns 404, not 403
6. Background jobs inherit tenant scope from the job record
7. Every endpoint has a cross-tenant leakage test
