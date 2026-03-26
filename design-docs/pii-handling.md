# TitanAI — PII Handling Strategy

PII protection is **non-negotiable** (Constitution §II). Only two PII fields exist: `patron_name` and `patron_email`,
both from reading list submissions. All other data (books, jobs, logs, tenants) is not PII.

## Approach: HMAC-SHA256

All PII is irreversibly hashed via **HMAC-SHA256** with a server-side secret before persistence. HMAC over plain SHA-256
prevents rainbow table attacks on low-entropy emails. Hashing is deterministic (same input + key → same hash), enabling
deduplication (FR-014) without storing plaintext.

## Hashing Module

Centralized in a single module. No other code hashes patron data.

```
hash_email(plaintext_email: str) -> str
hash_name(plaintext_name: str) -> str
```

Both functions: normalize input → compute HMAC-SHA256 → return hex digest. Never log, cache, or retain plaintext.

### Normalization (before hashing)

| Field | Rule                                         | Example                                        |
| ----- | -------------------------------------------- | ---------------------------------------------- |
| email | Lowercase, strip whitespace                  | `"  Jane@Example.COM "` → `"jane@example.com"` |
| name  | Lowercase, strip whitespace, collapse spaces | `"  Jane   DOE "` → `"jane doe"`               |

## Secret Key Management

| Requirement             | Implementation                               |
| ----------------------- | -------------------------------------------- |
| Not in code/config/logs | Loaded from env var `TITANAI_PII_SECRET_KEY` |
| Minimum length          | 32 bytes (256 bits), enforced at startup     |
| Missing key             | App refuses to start with fatal error        |

**Key rotation** breaks deduplication by design — old hashes won't match new ones. This is an accepted tradeoff: safety
over continuity. No migration path exists without external plaintext backup (which the system intentionally doesn't
keep).

## Data Flow

```
Client → API Handler → Service Layer (hash PII here) → Repository (hashes only) → Database
                                                      ↓
                                              Response (no PII)
```

Plaintext crosses from API handler into service layer, where it's immediately hashed. The repository layer **never**
receives plaintext. Responses never echo back name or email.

## Where PII Must Never Appear

| Location       | Enforcement                                                       |
| -------------- | ----------------------------------------------------------------- |
| Database       | Only `_hash` columns exist — no plaintext columns                 |
| Logs           | Hashing module never logs plaintext; structured logs use hashes   |
| Error messages | Catch and re-raise without plaintext; no raw request body in logs |
| API responses  | Submission response omits name/email; GET returns hashes only     |
| Job payloads   | Reading lists processed synchronously, PII never in job records   |
| Debug output   | PII fields replaced with `[REDACTED]` in repr/str                 |

## Deduplication via Email Hash

Same email → same normalization → same HMAC → same hash. Query `(tenant_id, patron_email_hash)` to find all submissions
from one patron. Does **not** prevent duplicate submissions — it **enables queries** across them.

## Testing Strategy

1. **No plaintext persisted**: Submit reading list, query DB directly, assert no plaintext in any column
2. **Deterministic**: Two submissions with same email → same `patron_email_hash`
3. **Normalization**: `"JANE@example.com"`, `" jane@example.com "`, `"Jane@Example.COM"` → same hash
4. **Not in logs**: Capture log output during submission, assert no plaintext
5. **Not in responses**: POST and GET responses contain hashes, never plaintext
6. **Missing key**: Unset env var, assert app fails to start with clear error
