import json

import aiosqlite
from httpx import AsyncClient


async def test_per_tenant_metrics(client: AsyncClient, tenant_id: str) -> None:
    resp = await client.get(f"/tenants/{tenant_id}/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == tenant_id
    assert "request_count_minute" in data
    assert "total_books" in data
    assert "active_ingestion_jobs" in data
    assert "total_ingestion_jobs" in data


async def test_aggregate_metrics(client: AsyncClient, tenant_id: str) -> None:
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "tenants" in data
    assert len(data["tenants"]) >= 1


async def test_rate_limit_429(client: AsyncClient, db: aiosqlite.Connection) -> None:
    """Exceed per-tenant rate limit and verify 429."""
    # Create tenant with very low rate limit
    import uuid
    from datetime import datetime, timezone

    tenant_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO tenants (id, name, slug, rate_limit_per_minute, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (tenant_id, f"Rate Test {uuid.uuid4().hex[:4]}", f"rate-{uuid.uuid4().hex[:4]}", 3, now, now),
    )
    await db.commit()

    # Make requests up to the limit
    for _ in range(3):
        resp = await client.get(f"/tenants/{tenant_id}/books")
        assert resp.status_code == 200

    # Next request should be rate limited
    resp = await client.get(f"/tenants/{tenant_id}/books")
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


async def test_job_concurrency_limit_429(client: AsyncClient, tenant_id: str) -> None:
    """Exceed max concurrent jobs (default 2) and verify 429."""
    await client.post(f"/tenants/{tenant_id}/ingestion/jobs", json={"query_type": "author", "query_value": "A"})
    await client.post(f"/tenants/{tenant_id}/ingestion/jobs", json={"query_type": "author", "query_value": "B"})
    resp = await client.post(f"/tenants/{tenant_id}/ingestion/jobs", json={"query_type": "author", "query_value": "C"})
    assert resp.status_code == 429


async def test_metrics_reflect_books(client: AsyncClient, tenant_id: str, db: aiosqlite.Connection) -> None:
    """Metrics should show correct book count."""
    import uuid
    from datetime import datetime, timezone

    # Seed some books
    now = datetime.now(timezone.utc).isoformat()
    for i in range(3):
        await db.execute(
            """INSERT INTO books (id, tenant_id, ol_work_id, title, authors, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), tenant_id, f"/works/OLM{i}W", f"Book {i}", json.dumps(["Author"]), now, now),
        )
    await db.commit()

    resp = await client.get(f"/tenants/{tenant_id}/metrics")
    assert resp.json()["total_books"] == 3
