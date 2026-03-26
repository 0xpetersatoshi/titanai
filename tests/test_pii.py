import aiosqlite
from httpx import AsyncClient

from titanai.core.pii import hash_email, hash_name


async def test_deterministic_hashing() -> None:
    h1 = hash_email("jane@example.com")
    h2 = hash_email("jane@example.com")
    assert h1 == h2


async def test_email_normalization() -> None:
    h1 = hash_email("JANE@example.com")
    h2 = hash_email(" jane@example.com ")
    h3 = hash_email("Jane@Example.COM")
    assert h1 == h2 == h3


async def test_name_normalization() -> None:
    h1 = hash_name("Jane Doe")
    h2 = hash_name("  JANE   DOE  ")
    h3 = hash_name("jane doe")
    assert h1 == h2 == h3


async def test_no_plaintext_in_db(client: AsyncClient, tenant_id: str, db: aiosqlite.Connection) -> None:
    resp = await client.post(
        f"/tenants/{tenant_id}/reading-lists",
        json={
            "patron_name": "Jane Doe",
            "patron_email": "jane@example.com",
            "books": [{"id": "/works/OL12345W", "id_type": "work_id"}],
        },
    )
    assert resp.status_code == 201

    # Check DB directly
    cursor = await db.execute("SELECT patron_name_hash, patron_email_hash FROM reading_lists WHERE tenant_id = ?", (tenant_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert "jane" not in row[0].lower()  # type: ignore[index]
    assert "doe" not in row[0].lower()  # type: ignore[index]
    assert "jane@example.com" not in row[1].lower()  # type: ignore[index]


async def test_pii_not_in_response(client: AsyncClient, tenant_id: str) -> None:
    resp = await client.post(
        f"/tenants/{tenant_id}/reading-lists",
        json={
            "patron_name": "Jane Doe",
            "patron_email": "jane@example.com",
            "books": [{"id": "/works/OL12345W", "id_type": "work_id"}],
        },
    )
    body = resp.text
    assert "Jane Doe" not in body
    assert "jane@example.com" not in body

    # GET list should also not contain PII
    list_resp = await client.get(f"/tenants/{tenant_id}/reading-lists")
    list_body = list_resp.text
    assert "Jane Doe" not in list_body
    assert "jane@example.com" not in list_body
