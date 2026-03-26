# Feature Specification: Multi-Tenant Library Catalog Service

**Feature Branch**: `001-multi-tenant-catalog`
**Created**: 2026-03-25
**Status**: Draft
**Input**: User description: "A multi-tenant catalog service for a consortium of public libraries that aggregates book data from Open Library and makes it searchable and browsable for library patrons and staff. Each library tenant has isolated catalog data and patron submissions."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Catalog Ingestion by Author or Subject (Priority: P1)

As a library staff member, I can trigger ingestion of books by author name or subject so that my library's catalog is populated with enriched book data from Open Library. Each stored book includes title, author name(s), first publish year, subjects, and a cover image URL when available. If a single API response is missing fields, the system makes follow-up requests to assemble a complete record.

**Why this priority**: Without ingested data, no other feature (search, browse, reading lists) has anything to operate on. This is the foundational data pipeline that every downstream capability depends on.

**Independent Test**: Can be fully tested by triggering an ingestion for a known author (e.g., "Octavia Butler") scoped to a test tenant, then verifying stored records contain all required fields and are accessible only within that tenant.

**Acceptance Scenarios**:

1. **Given** a valid tenant and an author name, **When** I submit an ingestion request for that author, **Then** the system fetches works from Open Library, resolves author details via follow-up requests if needed, and stores each book with: title, author name(s), first publish year, subjects, and cover image URL (if available).
2. **Given** a valid tenant and a subject (e.g., "science fiction"), **When** I submit an ingestion request for that subject, **Then** the system fetches and stores works matching that subject, scoped to my tenant.
3. **Given** a work returned by Open Library that is missing required fields in the initial response, **When** the system processes that work, **Then** it makes follow-up requests to other endpoints to assemble a complete record.
4. **Given** a work where no cover image exists, **When** the system stores the book, **Then** the cover image URL field is null rather than causing a failure.
5. **Given** a work that already exists in the tenant's catalog (same Open Library work ID), **When** ingestion encounters it again, **Then** the duplicate is detected and not re-inserted.
6. **Given** tenant A ingests books, **When** tenant B queries their catalog, **Then** tenant B sees none of tenant A's books.
7. **Given** the ingestion runs against the live Open Library API, **When** responses are received, **Then** no hardcoded or cached sample responses are used as substitutes.

---

### User Story 2 - Catalog Retrieval and Search (Priority: P1)

As a library patron, I can browse and search my library's catalog through a set of API endpoints that support pagination, filtering, and keyword search so that I can discover books of interest.

**Why this priority**: Ingestion without retrieval delivers no user-facing value. These two stories are co-dependent — together they form the minimum viable product.

**Independent Test**: After ingesting books for a tenant, query each retrieval endpoint and verify correct, paginated, tenant-scoped results including filtering and keyword search.

**Acceptance Scenarios**:

1. **Given** a tenant with ingested books, **When** I request the book list endpoint with no filters, **Then** I receive a paginated list of all books in that tenant's catalog.
2. **Given** a tenant with ingested books, **When** I filter by author name, **Then** only books by that author are returned.
3. **Given** a tenant with ingested books, **When** I filter by subject, **Then** only books with that subject are returned.
4. **Given** a tenant with ingested books, **When** I filter by a publish year range (e.g., 1990–2005), **Then** only books with first_publish_year in that range are returned.
5. **Given** a tenant with ingested books, **When** I search by keyword "octavia", **Then** books whose title or author name contains "octavia" (case-insensitive) are returned.
6. **Given** a valid tenant and a specific book ID, **When** I request that book's detail endpoint, **Then** I receive the full record including all stored fields.
7. **Given** pagination parameters (offset/limit), **When** I request the book list, **Then** results are paginated accordingly and include total count metadata.
8. **Given** tenant A's catalog, **When** tenant B queries books, **Then** tenant B receives zero results from tenant A.

---

### User Story 3 - Ingestion Activity Log (Priority: P2)

As a library staff member, I can view a log of all ingestion operations for my library so that I can audit what was imported, track errors, and understand ingestion history.

**Why this priority**: Provides essential observability for the core ingestion feature. Important for operations but the catalog is usable without it.

**Independent Test**: Trigger several ingestion operations (some successful, some with partial failures), then query the activity log endpoint and verify entries are complete, accurate, and tenant-scoped.

**Acceptance Scenarios**:

1. **Given** I trigger an ingestion that fetches 15 works (12 succeed, 3 fail), **When** I query the activity log, **Then** I see an entry with: query type (author/subject), query value, total fetched (15), succeeded (12), failed (3), timestamp, and error details for failures.
2. **Given** multiple ingestion operations over time, **When** I query the activity log, **Then** entries are returned in reverse chronological order (most recent first) with pagination support.
3. **Given** tenant A's ingestion operations, **When** tenant B queries the activity log, **Then** tenant B sees none of tenant A's log entries.

---

### User Story 4 - Reading List Submissions with PII Protection (Priority: P2)

As a library patron, I can submit a personal reading list containing my name, email, and a list of books I want to read. My personal information is protected — it is irreversibly hashed before storage and never appears in plaintext in any persisted record or log.

**Why this priority**: Core business feature for patron engagement and a key differentiator, but secondary to the catalog being functional first. PII protection is non-negotiable.

**Independent Test**: Submit a reading list with known PII and book references, then inspect persisted records to verify PII is hashed, deduplication works across submissions, and the response correctly reports book resolution status.

**Acceptance Scenarios**:

1. **Given** a patron submits a reading list with name, email, and a list of Open Library work IDs, **When** the submission is processed, **Then** the response confirms which books were resolved successfully and which could not be found.
2. **Given** a submission with valid PII, **When** the record is persisted, **Then** the name and email are irreversibly hashed — no plaintext PII exists in storage.
3. **Given** the same patron (same email) submits a second reading list, **When** the system processes it, **Then** it recognizes the submissions as belonging to the same patron via deterministic hash without revealing the original email.
4. **Given** a submission includes an ISBN instead of a work ID, **When** the system processes it, **Then** it resolves the ISBN to a work via Open Library and includes the book in the reading list.
5. **Given** a submission includes a work ID that does not exist in Open Library, **When** the system processes it, **Then** that book is reported as "not found" in the response but the rest of the submission succeeds.
6. **Given** tenant A's patron submits a reading list, **When** tenant B queries reading lists, **Then** tenant B sees no data from tenant A.
7. **Given** a submission triggers an error, **When** the error is logged, **Then** no PII appears in the log or error message.

---

### User Story 5 - Background Ingestion with Job Queue (Priority: P2)

As a library staff member, I can trigger catalog ingestion and immediately receive a response while the actual work happens in the background. I can check on progress, and the catalog stays fresh without manual re-triggers.

**Why this priority**: Required for production use — the Open Library API is slow and rate-limited, so blocking requests would be unacceptable. Enables the catalog to remain current over time.

**Independent Test**: Submit an ingestion request, verify the API responds immediately with a job reference, then poll the status endpoint until completion. Verify automatic re-ingestion triggers on schedule.

**Acceptance Scenarios**:

1. **Given** I submit an ingestion request, **When** the API responds, **Then** it returns immediately with a job ID and status (e.g., "queued") — the response does not block until ingestion completes.
2. **Given** a running ingestion job, **When** I query the job status endpoint, **Then** I see current progress (works processed vs. total), status, and any errors encountered so far.
3. **Given** Open Library returns a rate limit or timeout error during ingestion, **When** the job encounters this, **Then** it retries with backoff rather than failing the entire job.
4. **Given** a catalog that was previously ingested, **When** a configured refresh interval elapses, **Then** the system automatically triggers re-ingestion to keep the catalog fresh without manual intervention.
5. **Given** tenant A has a heavy ingestion running, **When** tenant B submits an ingestion or API request, **Then** tenant B's request is not blocked or significantly delayed by tenant A's workload.

---

### User Story 6 - Work Version Management (Priority: P3)

As a library staff member, I can see the history of changes to a book's metadata over time when re-ingestion detects updates, so that I can audit data quality and understand when Open Library data changed or regressed.

**Why this priority**: Differentiator feature that adds depth to data management. Valuable for data quality monitoring but not required for core catalog functionality.

**Independent Test**: Ingest a work, then re-ingest when metadata has changed. Query version history and verify diffs, timestamps, and regression handling.

**Acceptance Scenarios**:

1. **Given** a work was previously ingested with subjects ["sci-fi", "dystopia"], **When** re-ingestion fetches the same work now with subjects ["sci-fi"] only, **Then** a new version is created and the previous version's data is preserved in history.
2. **Given** a work with multiple versions, **When** I query the version history endpoint, **Then** I see each version with: timestamp, changed fields (diff), and the full snapshot at that point.
3. **Given** a re-ingestion where no fields have changed, **When** the system compares old and new data, **Then** no new version is created.
4. **Given** a field that previously had a value but is now missing in Open Library's response (data regression), **When** the system creates the new version, **Then** the regression is flagged and the previous value is preserved in the current record rather than being nullified.

---

### User Story 7 - Noisy Neighbor Throttling (Priority: P3)

As a platform operator, I can ensure no single tenant monopolizes shared resources at the expense of others, so that all library tenants receive consistent service quality.

**Why this priority**: Differentiator feature important at scale. Not blocking initial functionality but critical for multi-tenant fairness in production.

**Independent Test**: Simulate heavy concurrent usage from one tenant and verify a second tenant's requests complete within normal latency. Check per-tenant consumption metrics.

**Acceptance Scenarios**:

1. **Given** tenant A is submitting many concurrent ingestion requests, **When** tenant B submits a request, **Then** tenant B's request is processed within normal latency — not queued behind tenant A's backlog.
2. **Given** per-tenant rate limits are configured, **When** a tenant exceeds their limit, **Then** the system responds with a rate limit indication and guidance on when to retry.
3. **Given** the system is running under load, **When** I query the resource consumption endpoint, **Then** I see per-tenant metrics including request counts, active jobs, and quota usage.

---

### Edge Cases

- What happens when Open Library is completely down during ingestion? The job retries with exponential backoff for a bounded number of attempts, then fails with a clear error recorded in the activity log.
- What happens when an ingestion request specifies an author or subject with zero results? The activity log records 0 fetched, 0 succeeded, no error — just an empty result set.
- What happens when two concurrent ingestion jobs for the same tenant ingest overlapping works? Deduplication by Open Library work ID prevents duplicate book records; version management handles any metadata differences.
- What happens when a patron submits a reading list with zero books? The submission is rejected with a validation error — at least one book reference is required.
- What happens when a single Open Library work has inconsistent data across different endpoints? The system assembles the best available record by merging data from multiple endpoints, preferring the most complete source for each field.
- What happens when the system receives a request with an invalid or nonexistent tenant ID? The request is rejected with an appropriate error before any data access occurs.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST ingest works from Open Library by author name or subject, scoped to a specific tenant.
- **FR-002**: System MUST assemble complete book records from multiple Open Library endpoints when a single response lacks required fields (title, author names, first publish year, subjects, cover image URL).
- **FR-003**: System MUST store each ingested book with at minimum: title, author name(s), first publish year, subjects, and cover image URL (nullable when unavailable).
- **FR-004**: System MUST detect and skip duplicate works within a tenant's catalog based on Open Library work ID.
- **FR-005**: System MUST call the live Open Library API for all ingestion — no hardcoded or cached sample responses as test fixtures.
- **FR-006**: System MUST expose a paginated book listing endpoint supporting offset/limit pagination with total count metadata.
- **FR-007**: System MUST support filtering books by author name, subject, and publish year range.
- **FR-008**: System MUST support keyword search across book title and author name (case-insensitive).
- **FR-009**: System MUST expose a single-book detail endpoint returning all stored fields.
- **FR-010**: System MUST log every ingestion operation with: query type (author/subject), query value, works fetched count, success count, failure count, timestamps, and error details.
- **FR-011**: System MUST expose the activity log via an API endpoint, scoped to the requesting tenant, ordered most-recent-first with pagination.
- **FR-012**: System MUST accept reading list submissions containing: patron name, patron email, and a list of Open Library work IDs or ISBNs, scoped to a tenant.
- **FR-013**: System MUST irreversibly hash patron name and email before persistence — no plaintext PII in storage, logs, or error messages.
- **FR-014**: System MUST use deterministic hashing for patron email to enable deduplication of submissions by the same patron across multiple submissions.
- **FR-015**: System MUST resolve ISBNs to Open Library works when ISBNs are submitted in reading lists.
- **FR-016**: System MUST report in the reading list submission response which books were resolved successfully and which could not be found.
- **FR-017**: System MUST process catalog ingestion asynchronously via background jobs, returning a job reference immediately upon request.
- **FR-018**: System MUST expose a job status endpoint showing ingestion progress (pending, in-progress, completed, failed), works processed, and errors.
- **FR-019**: System MUST handle Open Library rate limits and timeouts gracefully with retries and backoff during background ingestion.
- **FR-020**: System MUST support automatic periodic re-ingestion to keep tenant catalogs fresh without manual intervention.
- **FR-021**: System MUST create versioned records when re-ingestion detects metadata changes to a previously ingested work, preserving full version history.
- **FR-022**: System MUST handle data regression by preserving prior field values when Open Library responses are missing fields that were previously present, and flagging the regression.
- **FR-023**: System MUST expose a version history endpoint per work showing diffs between versions and timestamps.
- **FR-024**: System MUST enforce per-tenant rate limiting to prevent any single tenant from monopolizing shared resources.
- **FR-025**: System MUST expose per-tenant resource consumption metrics (request counts, active jobs, quota usage).
- **FR-026**: System MUST enforce tenant isolation across all data access — catalog, reading lists, activity logs, jobs, and version history. No cross-tenant data leakage.

### Key Entities

- **Tenant**: A library branch in the consortium. Represents the isolation boundary. Key attributes: identifier, name, configuration (rate limits, refresh schedule).
- **Book**: A catalog entry sourced from Open Library, belonging to one tenant. Key attributes: Open Library work ID, title, author name(s), first publish year, subjects, cover image URL. Uniquely identified within a tenant by the Open Library work ID.
- **BookVersion**: A point-in-time snapshot of a book's metadata created when re-ingestion detects changes. Key attributes: associated book, version number, timestamp, field-level diff from prior version, regression flags.
- **ReadingList**: A patron's submitted reading list within a tenant. Key attributes: hashed patron name, hashed patron email, list of book references with resolution status, submission timestamp.
- **IngestionJob**: A background job representing an ingestion operation for a tenant. Key attributes: tenant, query type (author/subject), query value, status (queued/in-progress/completed/failed), progress metrics, timestamps.
- **ActivityLogEntry**: An auditable record of an ingestion operation's outcome. Key attributes: tenant, query type and value, counts (fetched/succeeded/failed), timestamps, error details.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A complete ingestion-to-search cycle (ingest by author, search by keyword, retrieve detail) works end-to-end for a tenant with correctly populated fields.
- **SC-002**: Tenant isolation is verified — queries from one tenant return zero results belonging to other tenants across all endpoints (catalog, reading lists, activity log, jobs).
- **SC-003**: No plaintext PII (patron name or email) exists in any persisted record, log entry, or error output.
- **SC-004**: Ingestion requests return a response within 2 seconds (job acknowledged, not completed); actual ingestion proceeds in background.
- **SC-005**: A patron who submits two reading lists with the same email is correctly identified as the same person without the email being recoverable from storage.
- **SC-006**: Re-ingestion of a work with changed metadata produces a queryable version history showing what changed and when.
- **SC-007**: Under concurrent load from multiple tenants, no single tenant causes greater than 2x latency increase for other tenants' requests.
- **SC-008**: Books ingested with incomplete data from Open Library's initial response have all available fields populated via follow-up requests.

## Assumptions

- Open Library's public API remains available without authentication or API key. Rate limits are approximately 1 request/second for unidentified clients and 3 requests/second with a User-Agent header. The service will identify itself.
- The service is a backend API only — no frontend, mobile app, or user interface is in scope.
- Tenant management (creating, updating, deleting tenants) is a simple administrative function, not a full-featured user-facing system.
- PII hashing uses a keyed hash (e.g., HMAC with a server-side secret) to produce deterministic, irreversible digests.
- Open Library data quality is inconsistent — missing fields, varying response shapes, and data regression are expected conditions, not exceptional errors.
- "Freshness" for automatic re-ingestion means the system periodically re-fetches previously ingested queries (author/subject searches), not individual work IDs.
- The service operates as a single deployment (not distributed) for the initial version.
