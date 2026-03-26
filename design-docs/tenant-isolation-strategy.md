# TitanAI — Tenant Isolation Strategy

Tenant isolation is a **non-negotiable** principle (Constitution §I). This document defines the enforcement mechanisms
at every layer of the stack to ensure one library's data never leaks into another's API responses, logs, or background
jobs.

---

## Layers of Enforcement

Isolation is not a single mechanism — it is enforced redundantly across four layers. A failure at any one layer should
not result in cross-tenant data exposure.

```
┌─────────────────────────────────────────────┐
│  Layer 1: API Route — tenant_id in URL path │
├─────────────────────────────────────────────┤
│  Layer 2: Middleware — tenant validation     │
│           and context injection              │
├─────────────────────────────────────────────┤
│  Layer 3: Repository — all queries scoped   │
│           by tenant_id, no bypass possible   │
├─────────────────────────────────────────────┤
│  Layer 4: Database — FK constraints and     │
│           composite unique indexes           │
└─────────────────────────────────────────────┘
```

---

## Layer 1: API Route Design

Every tenant-scoped endpoint lives under `/tenants/{tenant_id}/...`. The tenant ID is a **path parameter**, not a header
or query param.

**Why path, not header?**

- URLs are self-describing — you can see the tenant scope in logs, error messages, and monitoring dashboards without
  parsing headers.
- Prevents accidental omission — a missing path segment is a 404, not a silent default.
- No ambiguity about which tenant is being accessed.

**The only routes without a tenant prefix** are:

- `POST /tenants` — create a new tenant
- `GET /tenants` — list tenants (admin)
- `GET /metrics` — aggregate operator metrics

These are administrative endpoints that do not return tenant-scoped data.

---

## Layer 2: Middleware — Tenant Validation & Context

A FastAPI dependency (`get_current_tenant`) runs on every tenant-scoped route. It is responsible for:

### 2a. Tenant Existence Validation

Before any business logic executes, the middleware verifies the `tenant_id` from the path exists in the `tenants` table.
If not, the request is rejected with **404 Not Found** immediately. No downstream code ever runs with an invalid tenant.

```
Request → Extract tenant_id from path
        → Query tenants table
        → Not found? → 404 response, stop
        → Found? → Inject tenant context, continue
```

### 2b. Tenant Context Object

The middleware produces a `TenantContext` object containing the validated tenant's ID and configuration (rate limits,
refresh interval). This object is injected into route handlers via FastAPI's dependency injection. Route handlers and
service-layer functions receive the tenant context — they never extract tenant_id from the path themselves.

**Key rule**: All service-layer and repository-layer functions accept a `tenant_id` parameter. There is no way to call
these functions without specifying a tenant.

### 2c. Rate Limit Check

After validating the tenant, the middleware checks per-tenant rate limits (FR-024) against the `tenant_metrics` table.
If the tenant has exceeded their `rate_limit_per_minute`, respond with **429 Too Many Requests** before any business
logic runs.

---

## Layer 3: Repository Pattern — Query Scoping

The repository layer is the **only** code that constructs SQL queries. All repository methods enforce tenant scoping as
a structural guarantee, not a convention.

### 3a. Mandatory tenant_id Parameter

Every repository method that reads or writes tenant-scoped data requires `tenant_id` as a **non-optional parameter**.
There is no "get all books across tenants" method. If such a method is ever needed (e.g., for admin analytics), it is
placed in a separate, clearly-named admin repository — not in the tenant-scoped repository.

```
# Correct — tenant_id is required
def get_books(tenant_id: str, offset: int, limit: int) -> list[Book]: ...

# FORBIDDEN — no tenant scope
def get_all_books(offset: int, limit: int) -> list[Book]: ...
```

### 3b. Every Query Includes WHERE tenant_id = ?

All SELECT, UPDATE, and DELETE queries include `WHERE tenant_id = ?` as a mandatory clause. This is not optional or
conditional — it is part of every query template.

For composite lookups (e.g., fetching a specific book by ID), the query uses **both** the resource ID and the tenant ID:

```sql
-- Correct: scoped to tenant
SELECT * FROM books WHERE id = ? AND tenant_id = ?

-- FORBIDDEN: unscoped lookup
SELECT * FROM books WHERE id = ?
```

This prevents a tenant from accessing another tenant's book by guessing a UUID.

### 3c. Cross-Resource Queries

When querying across related tables (e.g., reading list items joined with books), tenant scoping is applied to the
**root table**, and foreign key relationships guarantee child records belong to the same tenant:

```sql
SELECT rl.*, rli.*
FROM reading_lists rl
JOIN reading_list_items rli ON rli.reading_list_id = rl.id
WHERE rl.tenant_id = ?
```

The `reading_list_items` table does not have its own `tenant_id` column — isolation is enforced through the parent
`reading_lists.tenant_id`. This avoids redundant data while maintaining isolation via the FK chain.

### 3d. Background Jobs

Ingestion jobs carry a `tenant_id` and operate exclusively on that tenant's data. When a background worker picks up a
job, it extracts the `tenant_id` from the job record and passes it through to all repository calls. There is no shared
state between jobs for different tenants.

---

## Layer 4: Database Constraints

The schema provides a final safety net through structural constraints.

### 4a. Foreign Key Chains

Every tenant-scoped table has a direct or indirect FK relationship to `tenants.id`:

| Table                | FK to tenants                                            |
| -------------------- | -------------------------------------------------------- |
| `books`              | Direct: `books.tenant_id → tenants.id`                   |
| `book_versions`      | Indirect: via `books.id` (book is tenant-scoped)         |
| `ingestion_jobs`     | Direct: `ingestion_jobs.tenant_id → tenants.id`          |
| `activity_logs`      | Direct: `activity_logs.tenant_id → tenants.id`           |
| `reading_lists`      | Direct: `reading_lists.tenant_id → tenants.id`           |
| `reading_list_items` | Indirect: via `reading_lists.id` (list is tenant-scoped) |
| `tenant_metrics`     | Direct: `tenant_metrics.tenant_id → tenants.id`          |

`PRAGMA foreign_keys=ON` is required on every SQLite connection.

### 4b. Composite Unique Constraints

The `UNIQUE(tenant_id, ol_work_id)` constraint on `books` ensures that deduplication (FR-004) is tenant-scoped — two
tenants can ingest the same Open Library work independently.

### 4c. Indexes Lead with tenant_id

All multi-column indexes start with `tenant_id` as the leading column:

- `idx_books_tenant` on `(tenant_id)`
- `idx_books_tenant_author` on `(tenant_id, authors)`
- `idx_books_tenant_year` on `(tenant_id, first_publish_year)`
- `idx_jobs_tenant_status` on `(tenant_id, status)`
- `idx_activity_logs_tenant_created` on `(tenant_id, created_at DESC)`
- `idx_reading_lists_patron` on `(tenant_id, patron_email_hash)`

Leading with `tenant_id` means the database naturally partitions index scans by tenant, and a query that accidentally
omits the tenant filter will result in a full table scan — making it obvious in performance monitoring.

---

## Testing Strategy

Tenant isolation must be verified in tests, not just assumed from code review.

### Cross-Tenant Leakage Tests

For every data-returning endpoint, write a test that:

1. Creates two tenants (A and B)
2. Populates data for tenant A
3. Queries as tenant B
4. Asserts the response contains **zero** results from tenant A

These tests cover: books, book versions, ingestion jobs, activity logs, reading lists, and metrics.

### Direct ID Access Tests

For every single-resource endpoint (`GET .../books/{book_id}`), write a test that:

1. Creates a book under tenant A
2. Requests that book's UUID under tenant B's URL path
3. Asserts **404 Not Found** (not 403 — do not confirm the resource exists)

**Why 404, not 403?** Returning 403 ("you don't have access") reveals that the resource exists under another tenant.
Returning 404 ("not found") gives no information about other tenants' data.

### Background Job Isolation Tests

For ingestion jobs, write a test that:

1. Triggers ingestion for tenant A
2. Verifies the resulting books are stored only under tenant A
3. Verifies the activity log entry is only visible to tenant A

---

## Failure Modes and Mitigations

| Failure Mode                                    | Mitigation                                                                                                              |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Developer forgets `WHERE tenant_id = ?`         | Repository pattern makes tenant_id a required parameter — code won't compile/run without it                             |
| Request sent with wrong tenant_id               | Middleware validates tenant exists; composite queries prevent accessing another tenant's resources by UUID              |
| Background job processes wrong tenant's data    | Job carries tenant_id; all repository calls within the job use that tenant_id                                           |
| SQL injection bypasses tenant filter            | Parameterized queries only — no string interpolation in SQL. SQLite driver handles escaping                             |
| New table added without tenant scoping          | Code review checklist: every new table with user data must have a `tenant_id` FK or be a child of a tenant-scoped table |
| Admin endpoint accidentally exposes tenant data | Admin endpoints (`GET /tenants`, `GET /metrics`) return only aggregate/metadata, never catalog or patron data           |

---

## Summary of Rules

1. **Every tenant-scoped URL includes `{tenant_id}` in the path.** No exceptions.
2. **Middleware validates tenant existence before any business logic.** Invalid tenant = 404, full stop.
3. **Every repository method requires `tenant_id`.** There are no unscoped query methods.
4. **Every SQL query includes `WHERE tenant_id = ?`.** Composite lookups use both resource ID and tenant ID.
5. **Cross-tenant resource access returns 404, not 403.** Never confirm a resource exists under another tenant.
6. **Background jobs inherit tenant scope from the job record.** No shared state across tenants.
7. **Tests verify isolation explicitly.** Every endpoint has a cross-tenant leakage test.
