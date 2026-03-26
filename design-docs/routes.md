# TitanAI — RESTful API Route Design

Tenant scoping is done via a path prefix `/tenants/{tenant_id}` to make isolation explicit and consistent.

---

## Tenant Management (Admin)

| Method | Route                  | Description        | FR  |
| ------ | ---------------------- | ------------------ | --- |
| `POST` | `/tenants`             | Create a tenant    | —   |
| `GET`  | `/tenants`             | List all tenants   | —   |
| `GET`  | `/tenants/{tenant_id}` | Get tenant details | —   |

## Catalog — Ingestion (US-1, US-5)

| Method | Route                                          | Description                                                        | FR             |
| ------ | ---------------------------------------------- | ------------------------------------------------------------------ | -------------- |
| `POST` | `/tenants/{tenant_id}/ingestion/jobs`          | Trigger ingestion (author or subject). Returns job ID immediately. | FR-001, FR-017 |
| `GET`  | `/tenants/{tenant_id}/ingestion/jobs`          | List ingestion jobs (with status filter)                           | FR-018         |
| `GET`  | `/tenants/{tenant_id}/ingestion/jobs/{job_id}` | Get job status/progress                                            | FR-018         |

Request body for `POST .../ingestion/jobs`:

```json
{
  "query_type": "author" | "subject",
  "query_value": "Octavia Butler"
}
```

## Catalog — Retrieval & Search (US-2)

| Method | Route                                  | Description                                           | FR                     |
| ------ | -------------------------------------- | ----------------------------------------------------- | ---------------------- |
| `GET`  | `/tenants/{tenant_id}/books`           | List books with pagination, filtering, keyword search | FR-006, FR-007, FR-008 |
| `GET`  | `/tenants/{tenant_id}/books/{book_id}` | Get single book detail                                | FR-009                 |

Query params for `GET .../books`:

- `offset`, `limit` — pagination
- `author` — filter by author name
- `subject` — filter by subject
- `year_min`, `year_max` — publish year range
- `q` — keyword search (title or author)

## Catalog — Version History (US-6)

| Method | Route                                                        | Description                     | FR             |
| ------ | ------------------------------------------------------------ | ------------------------------- | -------------- |
| `GET`  | `/tenants/{tenant_id}/books/{book_id}/versions`              | List version history for a book | FR-021, FR-023 |
| `GET`  | `/tenants/{tenant_id}/books/{book_id}/versions/{version_id}` | Get a specific version snapshot | FR-023         |

## Activity Log (US-3)

| Method | Route                                 | Description                                              | FR             |
| ------ | ------------------------------------- | -------------------------------------------------------- | -------------- |
| `GET`  | `/tenants/{tenant_id}/ingestion/logs` | List activity log entries (paginated, most-recent-first) | FR-010, FR-011 |

## Reading Lists (US-4)

| Method | Route                                          | Description                                       | FR                     |
| ------ | ---------------------------------------------- | ------------------------------------------------- | ---------------------- |
| `POST` | `/tenants/{tenant_id}/reading-lists`           | Submit a reading list (PII hashed before storage) | FR-012, FR-013, FR-014 |
| `GET`  | `/tenants/{tenant_id}/reading-lists`           | List reading list submissions (paginated)         | —                      |
| `GET`  | `/tenants/{tenant_id}/reading-lists/{list_id}` | Get a specific reading list                       | —                      |

Request body for `POST .../reading-lists`:

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

## Tenant Metrics (US-7)

| Method | Route                          | Description                                      | FR     |
| ------ | ------------------------------ | ------------------------------------------------ | ------ |
| `GET`  | `/tenants/{tenant_id}/metrics` | Get resource consumption for a tenant            | FR-025 |
| `GET`  | `/metrics`                     | Get aggregate per-tenant metrics (operator view) | FR-025 |

---

## Design Decisions

1. **Tenant in path, not header** — Makes isolation explicit, URLs are self-describing, easier to test and log. Every
   data endpoint lives under `/tenants/{tenant_id}/`.

2. **Ingestion as a job resource** — `POST .../ingestion/jobs` returns a job reference (FR-017). Separate from the books
   it produces. Job status is its own resource (FR-018). Activity logs are read-only records of completed operations
   (FR-010, FR-011), separate from active jobs.

3. **Search and filter on the list endpoint** — Rather than a separate `/search` route, the `GET .../books` endpoint
   handles both listing and searching via query params. This keeps the API surface minimal and avoids ambiguity about
   which endpoint to use.

4. **Versions as a sub-resource of books** — `GET .../books/{book_id}/versions` is the natural REST path. Each version
   is addressable.

5. **Reading list books as an array in the body** — Supports mixed ID types (work IDs and ISBNs) in a single submission
   per FR-012 and FR-015.
