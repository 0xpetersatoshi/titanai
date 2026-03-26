# TitanAI — PII Handling Strategy

PII protection is a **non-negotiable** principle (Constitution §II). This document defines how personally identifiable
information — patron names and email addresses submitted via reading lists — is handled at every stage, from API
ingestion through storage and retrieval.

---

## Scope of PII

The only PII fields in the system are:

| Field          | Source                               | Used For                                       |
| -------------- | ------------------------------------ | ---------------------------------------------- |
| `patron_name`  | Reading list submission request body | Display/identification — hashed before storage |
| `patron_email` | Reading list submission request body | Deduplication — hashed before storage          |

No other fields in the system contain PII. Book metadata, ingestion logs, job records, and tenant configuration are not
PII.

---

## Core Approach: HMAC-SHA256 with Server-Side Secret

PII is irreversibly hashed using **HMAC-SHA256** before any persistence occurs. The choice of HMAC over plain SHA-256 is
deliberate:

| Property                                 | Plain SHA-256                               | HMAC-SHA256                                          |
| ---------------------------------------- | ------------------------------------------- | ---------------------------------------------------- |
| Deterministic (same input → same output) | Yes                                         | Yes (with same key)                                  |
| Irreversible                             | Yes                                         | Yes                                                  |
| Resistant to rainbow table attacks       | No — common emails are trivially reversible | Yes — the secret key makes precomputation infeasible |
| Key rotation possible                    | No                                          | Yes — re-hash with new key                           |

**HMAC-SHA256** provides the deterministic property needed for deduplication (FR-014) while the server-side secret makes
rainbow table attacks infeasible — critical because email addresses are low-entropy (there are only so many
`jane@gmail.com` variants).

---

## The Hashing Module

All PII hashing is centralized in a single module (`pii` or similar). No other code in the system performs hashing of
patron data. This is a constitutional requirement.

### Responsibilities

1. **Hash PII fields** — Accept plaintext name/email, return HMAC-SHA256 hex digests.
2. **Normalize before hashing** — Apply consistent normalization so equivalent inputs produce the same hash.
3. **Load and manage the HMAC key** — Read the secret from the environment; refuse to start if it's missing.

### Normalization Rules

Before hashing, inputs are normalized to prevent near-duplicates from producing different hashes:

| Field   | Normalization                                             | Example                                        |
| ------- | --------------------------------------------------------- | ---------------------------------------------- |
| `email` | Lowercase, strip whitespace                               | `"  Jane@Example.COM "` → `"jane@example.com"` |
| `name`  | Lowercase, strip whitespace, collapse internal whitespace | `"  Jane   DOE "` → `"jane doe"`               |

Normalization happens **inside** the hashing module — callers pass raw input and receive a hash. The normalized
plaintext is never returned or logged.

### Interface

```
hash_email(plaintext_email: str) -> str
hash_name(plaintext_name: str) -> str
```

Both functions:

1. Normalize the input
2. Compute `HMAC-SHA256(key=server_secret, msg=normalized_input)`
3. Return the hex digest
4. Never log, cache, or retain the plaintext

---

## Secret Key Management

The HMAC key is the linchpin of the PII protection scheme. Its compromise would allow an attacker with database access
to attempt hash reversal via brute force.

### Requirements

| Requirement                                          | Implementation                                                            |
| ---------------------------------------------------- | ------------------------------------------------------------------------- |
| Key must not be in code or config files              | Loaded from environment variable `TITANAI_PII_SECRET_KEY`                 |
| Key must not be in the database                      | Stored outside the data path entirely                                     |
| Key must not appear in logs                          | The hashing module never logs the key or any plaintext                    |
| Key must be sufficiently long                        | Minimum 32 bytes (256 bits) — enforced at startup                         |
| Application must refuse to start without a valid key | Startup check raises a fatal error if the env var is missing or too short |

### Key Rotation

If the HMAC key needs to be rotated (e.g., suspected compromise):

1. **Deduplication breaks** — hashes produced with the old key will not match hashes produced with the new key. The same
   patron email will appear as two different patrons.
2. **This is by design** — rotation is a deliberate, destructive operation. It is better to lose deduplication
   continuity than to continue with a compromised key.
3. **Migration path** — If continuity matters, a one-time migration script can re-hash all records. This requires
   temporarily having access to the original plaintext, which the system does not store. Therefore, **key rotation
   without data loss is only possible if an external backup of the mapping exists** (which the system does not maintain
   by default). Accept the deduplication break as the cost of rotation.

---

## Data Flow: Reading List Submission

```
                           PII BOUNDARY
                           ────────────
Client                 │                    │  Service Layer    │  Database
                       │   API Handler      │                   │
POST /tenants/{id}/    │                    │                   │
  reading-lists        │                    │                   │
  {                    │  1. Validate       │                   │
    name: "Jane Doe",  │     request body   │                   │
    email: "jane@...", │                    │                   │
    books: [...]       │  2. Pass raw PII   │  3. Hash PII     │
  }                    │     to service     │     via module    │
                       │     layer          │                   │
                       │                    │  4. Resolve books │
                       │                    │     against OL    │
                       │                    │                   │
                       │                    │  5. Persist:      │  reading_lists:
                       │                    │     hashed name,  │    patron_name_hash
                       │                    │     hashed email, │    patron_email_hash
                       │                    │     book items    │
                       │                    │                   │  reading_list_items:
                       │  6. Return         │                   │    submitted_id
                       │     response       │                   │    status
                       │     (no PII)       │                   │
```

**Key points in the flow:**

- **Step 2 → 3**: Plaintext PII crosses from the API handler into the service layer, where it is immediately hashed. The
  plaintext never reaches the repository layer.
- **Step 5**: Only hashes are passed to the repository for persistence.
- **Step 6**: The response contains the reading list ID, book resolution results, and the submission timestamp. It does
  **not** echo back the patron's name or email.

---

## Where PII Must Never Appear

| Location                          | Enforcement                                                                                                                                                      |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Database (`reading_lists` table)  | Only `patron_name_hash` and `patron_email_hash` columns exist — no plaintext columns                                                                             |
| Application logs                  | The hashing module never logs plaintext. Structured logging uses the hash when referring to a patron.                                                            |
| Error messages / exception traces | Catch exceptions around PII handling and re-raise without the plaintext in the message. Never include raw request body in error logs for reading list endpoints. |
| API responses                     | The reading list submission response does not echo name or email. GET endpoints for reading lists return hashed identifiers only.                                |
| Background job payloads           | Reading list submissions are processed synchronously (not via job queue), so PII never enters a persisted job record.                                            |
| Debug / development output        | Even in debug mode, PII fields are replaced with `[REDACTED]` in any repr/str output of request models.                                                          |

---

## Deduplication via Email Hash

FR-014 requires recognizing that the same patron submitted multiple reading lists without storing their email.

### How It Works

1. Patron submits a reading list with email `jane@example.com`.
2. The hashing module normalizes to `jane@example.com` and computes `HMAC-SHA256(key, "jane@example.com")` →
   `a1b2c3...`.
3. The hash `a1b2c3...` is stored in `reading_lists.patron_email_hash`.
4. Patron submits another reading list later with the same email.
5. The same normalization + HMAC produces the same hash `a1b2c3...`.
6. A query on `(tenant_id, patron_email_hash)` finds both submissions.

### What Deduplication Does NOT Do

- It does not **prevent** duplicate submissions — a patron can submit as many reading lists as they want.
- It does not **merge** submissions — each submission is a separate record.
- It **enables queries** like "show all reading lists from this patron" by matching on the email hash.
- It could support **counting** unique patrons per tenant without knowing who they are.

---

## Testing Strategy

### PII Never Persisted in Plaintext

1. Submit a reading list with known PII (e.g., `name="Test User"`, `email="test@example.com"`).
2. Query the `reading_lists` table directly (bypass the API).
3. Assert that neither `"Test User"` nor `"test@example.com"` appears in any column.
4. Assert that `patron_name_hash` and `patron_email_hash` are valid hex strings of the expected length (64 chars for
   SHA-256).

### Deterministic Hashing

1. Submit two reading lists with the same email.
2. Assert both records have the same `patron_email_hash`.

### Normalization Consistency

1. Submit reading lists with variant emails: `"JANE@example.com"`, `" jane@example.com "`, `"Jane@Example.COM"`.
2. Assert all three produce the same `patron_email_hash`.

### PII Not in Logs

1. Submit a reading list while capturing log output.
2. Assert the plaintext name and email do not appear anywhere in the captured logs.

### PII Not in API Responses

1. Submit a reading list.
2. Assert the response body does not contain the submitted name or email.
3. `GET` the reading list by ID.
4. Assert the response contains hashes, not plaintext.

### Missing Secret Key

1. Unset the `TITANAI_PII_SECRET_KEY` environment variable.
2. Attempt to start the application.
3. Assert it fails with a clear error message (that itself does not contain the key).

---

## Summary of Rules

1. **All PII is hashed via HMAC-SHA256 before persistence.** No plaintext PII enters the repository or database layer.
2. **Hashing is centralized in one module.** No other code hashes patron data.
3. **Inputs are normalized before hashing.** Lowercase, stripped, for consistent deduplication.
4. **The HMAC key is a server-side secret.** Loaded from environment, never logged, minimum 256 bits.
5. **PII never appears in logs, errors, or API responses.** Enforced by module design and tested explicitly.
6. **Key rotation breaks deduplication.** This is an accepted tradeoff — safety over continuity.
7. **Deduplication is query-based, not prevention-based.** Same email → same hash → queryable, but submissions are never
   blocked.
