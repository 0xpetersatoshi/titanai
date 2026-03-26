import json

import aiosqlite
from httpx import AsyncClient


async def _seed_books(db: aiosqlite.Connection, tenant_id: str, count: int = 3) -> list[str]:
    """Insert test books directly into DB, return book IDs."""
    import uuid
    from datetime import datetime, timezone

    book_ids = []
    now = datetime.now(timezone.utc).isoformat()
    for i in range(count):
        book_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO books (id, tenant_id, ol_work_id, title, authors, first_publish_year, subjects, cover_image_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                book_id, tenant_id, f"/works/OL{i}W", f"Book {i}",
                json.dumps([f"Author {i}"]), 2000 + i,
                json.dumps([f"Subject {i}", "Fiction"]),
                f"https://covers.openlibrary.org/b/id/{i}-M.jpg", now, now,
            ),
        )
        book_ids.append(book_id)
    await db.commit()
    return book_ids


async def test_list_books_pagination(client: AsyncClient, tenant_id: str, db: aiosqlite.Connection) -> None:
    await _seed_books(db, tenant_id, count=5)
    resp = await client.get(f"/tenants/{tenant_id}/books?limit=2&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["offset"] == 0
    assert data["limit"] == 2

    resp2 = await client.get(f"/tenants/{tenant_id}/books?limit=2&offset=2")
    assert len(resp2.json()["items"]) == 2


async def test_filter_by_author(client: AsyncClient, tenant_id: str, db: aiosqlite.Connection) -> None:
    await _seed_books(db, tenant_id)
    resp = await client.get(f"/tenants/{tenant_id}/books?author=Author 1")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


async def test_filter_by_subject(client: AsyncClient, tenant_id: str, db: aiosqlite.Connection) -> None:
    await _seed_books(db, tenant_id)
    resp = await client.get(f"/tenants/{tenant_id}/books?subject=Fiction")
    assert resp.json()["total"] == 3


async def test_filter_by_year_range(client: AsyncClient, tenant_id: str, db: aiosqlite.Connection) -> None:
    await _seed_books(db, tenant_id)
    resp = await client.get(f"/tenants/{tenant_id}/books?year_min=2001&year_max=2002")
    assert resp.json()["total"] == 2


async def test_keyword_search(client: AsyncClient, tenant_id: str, db: aiosqlite.Connection) -> None:
    await _seed_books(db, tenant_id)
    resp = await client.get(f"/tenants/{tenant_id}/books?q=Book 0")
    assert resp.json()["total"] >= 1


async def test_get_book_detail(client: AsyncClient, tenant_id: str, db: aiosqlite.Connection) -> None:
    book_ids = await _seed_books(db, tenant_id)
    resp = await client.get(f"/tenants/{tenant_id}/books/{book_ids[0]}")
    assert resp.status_code == 200
    assert resp.json()["id"] == book_ids[0]


async def test_get_book_not_found(client: AsyncClient, tenant_id: str) -> None:
    resp = await client.get(f"/tenants/{tenant_id}/books/nonexistent")
    assert resp.status_code == 404


async def test_cross_tenant_book_isolation(client: AsyncClient, tenant_id: str, db: aiosqlite.Connection) -> None:
    book_ids = await _seed_books(db, tenant_id)

    # Create tenant B
    resp = await client.post("/tenants", json={"name": "Isolated Lib", "slug": "isolated"})
    tenant_b = resp.json()["id"]

    # Tenant B should see zero books
    resp = await client.get(f"/tenants/{tenant_b}/books")
    assert resp.json()["total"] == 0

    # Tenant B cannot access Tenant A's book by ID
    resp = await client.get(f"/tenants/{tenant_b}/books/{book_ids[0]}")
    assert resp.status_code == 404
