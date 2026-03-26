import json

import aiosqlite
from httpx import AsyncClient


async def test_submit_reading_list(client: AsyncClient, tenant_id: str) -> None:
    resp = await client.post(
        f"/tenants/{tenant_id}/reading-lists",
        json={
            "patron_name": "Test Patron",
            "patron_email": "test@example.com",
            "books": [{"id": "/works/OL12345W", "id_type": "work_id"}],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert len(data["books"]) == 1
    assert data["books"][0]["submitted_id"] == "/works/OL12345W"
    assert data["books"][0]["status"] in ("resolved", "not_found")


async def test_reading_list_empty_books(client: AsyncClient, tenant_id: str) -> None:
    resp = await client.post(
        f"/tenants/{tenant_id}/reading-lists",
        json={
            "patron_name": "Test",
            "patron_email": "test@example.com",
            "books": [],
        },
    )
    assert resp.status_code == 422


async def test_reading_list_resolved_book(client: AsyncClient, tenant_id: str, db: aiosqlite.Connection) -> None:
    """Submit a reading list with a work_id that exists in the catalog."""
    import uuid
    from datetime import datetime, timezone

    book_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """INSERT INTO books (id, tenant_id, ol_work_id, title, authors, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (book_id, tenant_id, "/works/OL999W", "Known Book", json.dumps(["Author"]), now, now),
    )
    await db.commit()

    resp = await client.post(
        f"/tenants/{tenant_id}/reading-lists",
        json={
            "patron_name": "Patron",
            "patron_email": "patron@example.com",
            "books": [{"id": "/works/OL999W", "id_type": "work_id"}],
        },
    )
    assert resp.status_code == 201
    assert resp.json()["books"][0]["status"] == "resolved"
    assert resp.json()["books"][0]["book_id"] == book_id


async def test_list_reading_lists(client: AsyncClient, tenant_id: str) -> None:
    await client.post(
        f"/tenants/{tenant_id}/reading-lists",
        json={
            "patron_name": "P1", "patron_email": "p1@ex.com",
            "books": [{"id": "/works/OL1W", "id_type": "work_id"}],
        },
    )
    await client.post(
        f"/tenants/{tenant_id}/reading-lists",
        json={
            "patron_name": "P2", "patron_email": "p2@ex.com",
            "books": [{"id": "/works/OL2W", "id_type": "work_id"}],
        },
    )

    resp = await client.get(f"/tenants/{tenant_id}/reading-lists")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


async def test_get_reading_list(client: AsyncClient, tenant_id: str) -> None:
    create_resp = await client.post(
        f"/tenants/{tenant_id}/reading-lists",
        json={
            "patron_name": "P", "patron_email": "p@ex.com",
            "books": [{"id": "/works/OL1W", "id_type": "work_id"}],
        },
    )
    list_id = create_resp.json()["id"]

    resp = await client.get(f"/tenants/{tenant_id}/reading-lists/{list_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == list_id


async def test_reading_list_cross_tenant_isolation(client: AsyncClient, tenant_id: str) -> None:
    create_resp = await client.post(
        f"/tenants/{tenant_id}/reading-lists",
        json={
            "patron_name": "P", "patron_email": "p@ex.com",
            "books": [{"id": "/works/OL1W", "id_type": "work_id"}],
        },
    )
    list_id = create_resp.json()["id"]

    # Create tenant B
    resp = await client.post("/tenants", json={"name": "Other RL Lib", "slug": "other-rl"})
    tenant_b = resp.json()["id"]

    resp = await client.get(f"/tenants/{tenant_b}/reading-lists/{list_id}")
    assert resp.status_code == 404

    resp = await client.get(f"/tenants/{tenant_b}/reading-lists")
    assert resp.json()["total"] == 0
