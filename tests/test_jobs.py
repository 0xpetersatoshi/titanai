import aiosqlite
from httpx import AsyncClient


async def test_create_job_returns_202(client: AsyncClient, tenant_id: str) -> None:
    resp = await client.post(
        f"/tenants/{tenant_id}/ingestion/jobs",
        json={"query_type": "author", "query_value": "Test Author"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "queued"
    assert data["tenant_id"] == tenant_id
    assert data["query_type"] == "author"
    assert data["id"]


async def test_get_job_status(client: AsyncClient, tenant_id: str) -> None:
    create_resp = await client.post(
        f"/tenants/{tenant_id}/ingestion/jobs",
        json={"query_type": "author", "query_value": "Test Author"},
    )
    job_id = create_resp.json()["id"]

    resp = await client.get(f"/tenants/{tenant_id}/ingestion/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


async def test_list_jobs(client: AsyncClient, tenant_id: str) -> None:
    await client.post(
        f"/tenants/{tenant_id}/ingestion/jobs",
        json={"query_type": "author", "query_value": "Author A"},
    )
    await client.post(
        f"/tenants/{tenant_id}/ingestion/jobs",
        json={"query_type": "subject", "query_value": "Science"},
    )

    resp = await client.get(f"/tenants/{tenant_id}/ingestion/jobs")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


async def test_list_jobs_status_filter(client: AsyncClient, tenant_id: str) -> None:
    await client.post(
        f"/tenants/{tenant_id}/ingestion/jobs",
        json={"query_type": "author", "query_value": "Test"},
    )

    resp = await client.get(f"/tenants/{tenant_id}/ingestion/jobs?status=queued")
    assert resp.json()["total"] >= 1

    resp = await client.get(f"/tenants/{tenant_id}/ingestion/jobs?status=completed")
    assert resp.json()["total"] == 0


async def test_job_concurrency_limit(client: AsyncClient, tenant_id: str) -> None:
    """Exceed max concurrent jobs limit (default 2)."""
    await client.post(f"/tenants/{tenant_id}/ingestion/jobs", json={"query_type": "author", "query_value": "A"})
    await client.post(f"/tenants/{tenant_id}/ingestion/jobs", json={"query_type": "author", "query_value": "B"})
    resp = await client.post(f"/tenants/{tenant_id}/ingestion/jobs", json={"query_type": "author", "query_value": "C"})
    assert resp.status_code == 429


async def test_job_cross_tenant_isolation(client: AsyncClient, tenant_id: str) -> None:
    create_resp = await client.post(
        f"/tenants/{tenant_id}/ingestion/jobs",
        json={"query_type": "author", "query_value": "Test"},
    )
    job_id = create_resp.json()["id"]

    # Create tenant B
    resp = await client.post("/tenants", json={"name": "Other Lib Jobs", "slug": "other-jobs"})
    tenant_b = resp.json()["id"]

    # Tenant B should not see tenant A's job
    resp = await client.get(f"/tenants/{tenant_b}/ingestion/jobs/{job_id}")
    assert resp.status_code == 404

    resp = await client.get(f"/tenants/{tenant_b}/ingestion/jobs")
    assert resp.json()["total"] == 0


async def test_stale_job_recovery(db: aiosqlite.Connection) -> None:
    """Stale in_progress jobs should be reset to queued."""
    from titanai.db.repositories import ingestion_jobs as job_repo
    from titanai.db.repositories import tenants as tenant_repo

    tenant = await tenant_repo.create_tenant(db, "Recovery Lib", "recovery")
    job = await job_repo.create_job(db, tenant.id, "author", "Test Author")

    # Simulate claiming the job
    await db.execute(
        "UPDATE ingestion_jobs SET status='in_progress' WHERE id=?", (job.id,)
    )
    await db.commit()

    # Reset stale jobs
    count = await job_repo.reset_stale_jobs(db)
    assert count == 1

    # Verify it's back to queued
    recovered = await job_repo.get_job(db, tenant.id, job.id)
    assert recovered is not None
    assert recovered.status == "queued"
