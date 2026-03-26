"""Comprehensive cross-tenant isolation tests for all data-returning endpoints."""
import json
import uuid
from datetime import datetime, timezone

import aiosqlite
from httpx import AsyncClient


async def _create_tenant(client: AsyncClient, name: str) -> str:
    slug = f"iso-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/tenants", json={"name": name, "slug": slug})
    assert resp.status_code == 201
    return resp.json()["id"]


async def _seed_data(client: AsyncClient, db: aiosqlite.Connection, tenant_id: str) -> dict:
    """Seed all types of data for a tenant, return IDs."""
    now = datetime.now(timezone.utc).isoformat()

    # Book
    book_id = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO books (id, tenant_id, ol_work_id, title, authors, subjects, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (book_id, tenant_id, "/works/OLisoW", "Isolation Test Book", json.dumps(["Author"]), json.dumps(["Subject"]), now, now),
    )

    # Book version
    version_id = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO book_versions (id, book_id, version_number, title, authors, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (version_id, book_id, 1, "Isolation Test Book", json.dumps(["Author"]), now),
    )

    # Ingestion job
    job_id = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO ingestion_jobs (id, tenant_id, query_type, query_value, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (job_id, tenant_id, "author", "Test", "completed", now),
    )

    # Activity log
    log_id = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO activity_logs (id, tenant_id, job_id, query_type, query_value, total_fetched, succeeded, failed, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (log_id, tenant_id, job_id, "author", "Test", 10, 8, 2, now),
    )

    # Reading list
    list_id = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO reading_lists (id, tenant_id, patron_name_hash, patron_email_hash, created_at)
        VALUES (?, ?, ?, ?, ?)""",
        (list_id, tenant_id, "hash_name", "hash_email", now),
    )

    await db.commit()
    return {"book_id": book_id, "version_id": version_id, "job_id": job_id, "list_id": list_id}


async def test_books_cross_tenant(client: AsyncClient, db: aiosqlite.Connection) -> None:
    tenant_a = await _create_tenant(client, "Iso Books A")
    tenant_b = await _create_tenant(client, "Iso Books B")
    ids = await _seed_data(client, db, tenant_a)

    # List: tenant B sees nothing
    resp = await client.get(f"/tenants/{tenant_b}/books")
    assert resp.json()["total"] == 0

    # Direct access: tenant B cannot see tenant A's book
    resp = await client.get(f"/tenants/{tenant_b}/books/{ids['book_id']}")
    assert resp.status_code == 404


async def test_versions_cross_tenant(client: AsyncClient, db: aiosqlite.Connection) -> None:
    tenant_a = await _create_tenant(client, "Iso Versions A")
    tenant_b = await _create_tenant(client, "Iso Versions B")
    ids = await _seed_data(client, db, tenant_a)

    resp = await client.get(f"/tenants/{tenant_b}/books/{ids['book_id']}/versions")
    assert resp.status_code == 404

    resp = await client.get(f"/tenants/{tenant_b}/books/{ids['book_id']}/versions/{ids['version_id']}")
    assert resp.status_code == 404


async def test_jobs_cross_tenant(client: AsyncClient, db: aiosqlite.Connection) -> None:
    tenant_a = await _create_tenant(client, "Iso Jobs A")
    tenant_b = await _create_tenant(client, "Iso Jobs B")
    ids = await _seed_data(client, db, tenant_a)

    resp = await client.get(f"/tenants/{tenant_b}/ingestion/jobs")
    assert resp.json()["total"] == 0

    resp = await client.get(f"/tenants/{tenant_b}/ingestion/jobs/{ids['job_id']}")
    assert resp.status_code == 404


async def test_activity_logs_cross_tenant(client: AsyncClient, db: aiosqlite.Connection) -> None:
    tenant_a = await _create_tenant(client, "Iso Logs A")
    tenant_b = await _create_tenant(client, "Iso Logs B")
    await _seed_data(client, db, tenant_a)

    resp = await client.get(f"/tenants/{tenant_b}/ingestion/logs")
    assert resp.json()["total"] == 0


async def test_reading_lists_cross_tenant(client: AsyncClient, db: aiosqlite.Connection) -> None:
    tenant_a = await _create_tenant(client, "Iso RL A")
    tenant_b = await _create_tenant(client, "Iso RL B")
    ids = await _seed_data(client, db, tenant_a)

    resp = await client.get(f"/tenants/{tenant_b}/reading-lists")
    assert resp.json()["total"] == 0

    resp = await client.get(f"/tenants/{tenant_b}/reading-lists/{ids['list_id']}")
    assert resp.status_code == 404


async def test_metrics_cross_tenant(client: AsyncClient, db: aiosqlite.Connection) -> None:
    tenant_a = await _create_tenant(client, "Iso Metrics A")
    tenant_b = await _create_tenant(client, "Iso Metrics B")
    await _seed_data(client, db, tenant_a)

    resp = await client.get(f"/tenants/{tenant_b}/metrics")
    assert resp.status_code == 200
    assert resp.json()["total_books"] == 0
    assert resp.json()["total_ingestion_jobs"] == 0
