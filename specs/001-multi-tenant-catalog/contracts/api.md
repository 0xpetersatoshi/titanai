# API Contract: Multi-Tenant Library Catalog Service

**Base URL**: `http://localhost:8000`
**Content-Type**: `application/json`

## Tenant Management

### POST /tenants

Create a new tenant.

**Request**:
```json
{
  "name": "Springfield Public Library",
  "slug": "springfield-public"
}
```

**Response** `201 Created`:
```json
{
  "id": "uuid",
  "name": "Springfield Public Library",
  "slug": "springfield-public",
  "rate_limit_per_minute": 60,
  "ingestion_refresh_hours": 24,
  "created_at": "2026-03-25T14:30:00Z",
  "updated_at": "2026-03-25T14:30:00Z"
}
```

### GET /tenants

List all tenants.

**Response** `200 OK`:
```json
{
  "items": [{ "id": "uuid", "name": "...", "slug": "...", ... }],
  "total": 5,
  "offset": 0,
  "limit": 20
}
```

### GET /tenants/{tenant_id}

Get tenant details. Returns `404` if tenant does not exist.

**Response** `200 OK`: Same shape as POST response.

---

## Ingestion Jobs

### POST /tenants/{tenant_id}/ingestion/jobs

Trigger an ingestion. Returns immediately with job reference.

**Request**:
```json
{
  "query_type": "author",
  "query_value": "Octavia Butler"
}
```

**Response** `202 Accepted`:
```json
{
  "id": "uuid",
  "tenant_id": "uuid",
  "query_type": "author",
  "query_value": "Octavia Butler",
  "status": "queued",
  "total_works": 0,
  "processed_works": 0,
  "succeeded": 0,
  "failed": 0,
  "is_auto_refresh": false,
  "created_at": "2026-03-25T14:30:00Z",
  "started_at": null,
  "completed_at": null
}
```

**Error** `429 Too Many Requests`: Tenant has reached concurrent job limit.

### GET /tenants/{tenant_id}/ingestion/jobs

List ingestion jobs. Supports `?status=queued|in_progress|completed|failed` filter.

**Response** `200 OK`:
```json
{
  "items": [{ "id": "uuid", "status": "completed", ... }],
  "total": 12,
  "offset": 0,
  "limit": 20
}
```

### GET /tenants/{tenant_id}/ingestion/jobs/{job_id}

Get job status and progress.

**Response** `200 OK`: Same shape as POST response with updated progress fields.
**Error** `404 Not Found`: Job does not exist or belongs to another tenant.

---

## Catalog

### GET /tenants/{tenant_id}/books

List books with pagination, filtering, and keyword search.

**Query params**: `offset` (int), `limit` (int), `author` (string), `subject` (string), `year_min` (int), `year_max` (int), `q` (string — keyword search).

**Response** `200 OK`:
```json
{
  "items": [
    {
      "id": "uuid",
      "ol_work_id": "/works/OL45804W",
      "title": "Kindred",
      "authors": ["Octavia E. Butler"],
      "first_publish_year": 1979,
      "subjects": ["Science fiction", "Time travel"],
      "cover_image_url": "https://covers.openlibrary.org/b/olid/OL45804W-M.jpg",
      "current_version": 1,
      "created_at": "2026-03-25T14:30:00Z",
      "updated_at": "2026-03-25T14:30:00Z"
    }
  ],
  "total": 42,
  "offset": 0,
  "limit": 20
}
```

### GET /tenants/{tenant_id}/books/{book_id}

Get full book detail.

**Response** `200 OK`: Single book object (same shape as list item).
**Error** `404 Not Found`: Book does not exist or belongs to another tenant.

---

## Version History

### GET /tenants/{tenant_id}/books/{book_id}/versions

List version history for a book.

**Response** `200 OK`:
```json
{
  "items": [
    {
      "id": "uuid",
      "version_number": 2,
      "title": "Kindred",
      "authors": ["Octavia E. Butler"],
      "first_publish_year": 1979,
      "subjects": ["Science fiction"],
      "cover_image_url": "...",
      "diff": { "subjects": { "old": ["Science fiction", "Time travel"], "new": ["Science fiction"] } },
      "has_regression": true,
      "regression_fields": ["subjects"],
      "created_at": "2026-03-26T10:00:00Z"
    }
  ],
  "total": 2,
  "offset": 0,
  "limit": 20
}
```

### GET /tenants/{tenant_id}/books/{book_id}/versions/{version_id}

Get a specific version snapshot. Same shape as list item.

---

## Activity Log

### GET /tenants/{tenant_id}/ingestion/logs

List activity log entries (most recent first).

**Response** `200 OK`:
```json
{
  "items": [
    {
      "id": "uuid",
      "job_id": "uuid",
      "query_type": "author",
      "query_value": "Octavia Butler",
      "total_fetched": 15,
      "succeeded": 12,
      "failed": 3,
      "errors": [{ "work_id": "/works/OL123", "error": "HTTP 500 from Open Library" }],
      "created_at": "2026-03-25T14:35:00Z"
    }
  ],
  "total": 8,
  "offset": 0,
  "limit": 20
}
```

---

## Reading Lists

### POST /tenants/{tenant_id}/reading-lists

Submit a reading list. PII is hashed before storage.

**Request**:
```json
{
  "patron_name": "Jane Doe",
  "patron_email": "jane@example.com",
  "books": [
    { "id": "/works/OL45804W", "id_type": "work_id" },
    { "id": "978-0-06-112008-4", "id_type": "isbn" }
  ]
}
```

**Response** `201 Created`:
```json
{
  "id": "uuid",
  "created_at": "2026-03-25T15:00:00Z",
  "books": [
    { "submitted_id": "/works/OL45804W", "submitted_id_type": "work_id", "status": "resolved", "book_id": "uuid" },
    { "submitted_id": "978-0-06-112008-4", "submitted_id_type": "isbn", "status": "not_found", "book_id": null }
  ]
}
```

**Note**: Response does NOT echo patron_name or patron_email.

**Error** `422 Unprocessable Entity`: Empty books list or invalid input.

### GET /tenants/{tenant_id}/reading-lists

List reading list submissions (paginated). Returns hashed patron identifiers only.

### GET /tenants/{tenant_id}/reading-lists/{list_id}

Get a specific reading list with book items and resolution status.

---

## Metrics

### GET /tenants/{tenant_id}/metrics

Per-tenant resource consumption.

**Response** `200 OK`:
```json
{
  "tenant_id": "uuid",
  "request_count_minute": 23,
  "active_ingestion_jobs": 1,
  "total_books": 342,
  "total_ingestion_jobs": 15,
  "updated_at": "2026-03-25T15:00:00Z"
}
```

### GET /metrics

Aggregate per-tenant metrics (operator view).

**Response** `200 OK`:
```json
{
  "tenants": [
    { "tenant_id": "uuid", "tenant_name": "Springfield Public Library", ... }
  ]
}
```

---

## Common Patterns

### Pagination

All list endpoints accept `offset` (default 0) and `limit` (default 20) query params. Responses include:
```json
{ "items": [...], "total": 100, "offset": 0, "limit": 20 }
```

### Error Responses

```json
{ "detail": "Tenant not found" }
```

- `404`: Resource not found or belongs to another tenant (never 403 for cross-tenant)
- `422`: Validation error
- `429`: Rate limit exceeded (includes `Retry-After` header)
- `500`: Internal server error

### Tenant Scoping

All `/tenants/{tenant_id}/...` endpoints validate tenant existence before processing. Invalid tenant ID = `404`.
