import uuid

import aiosqlite
import pytest
from httpx import AsyncClient

from titanai.db.repositories import activity_logs as activity_log_repo
from titanai.db.repositories import ingestion_jobs as job_repo


@pytest.mark.slow
async def test_activity_log_created_after_sync_ingestion(
    client: AsyncClient, tenant_id: str,
) -> None:
    """Sync ingestion should create an activity log entry."""
    resp = await client.post(
        f"/tenants/{tenant_id}/ingestion",
        json={"query_type": "author", "query_value": "Octavia Butler"},
    )
    assert resp.status_code == 200
    data = resp.json()

    logs_resp = await client.get(f"/tenants/{tenant_id}/ingestion/logs")
    assert logs_resp.status_code == 200
    logs = logs_resp.json()

    assert logs["total"] >= 1
    log = logs["items"][0]
    assert log["tenant_id"] == tenant_id
    assert log["query_type"] == "author"
    assert log["query_value"] == "Octavia Butler"
    assert log["total_fetched"] == data["total_works"]
    assert log["succeeded"] == data["succeeded"]
    assert log["failed"] == data["failed"]


async def test_activity_log_tenant_isolation(
    client: AsyncClient, tenant_id: str, db: aiosqlite.Connection,
) -> None:
    """Logs for tenant A should not be visible to tenant B."""
    # Create a job + log for tenant A
    job_a = await job_repo.create_job(db, tenant_id, "author", "Test Author")
    await job_repo.mark_completed(db, job_a.id)
    await activity_log_repo.create_log(
        db, tenant_id, job_a.id, "author", "Test Author",
        total_fetched=5, succeeded=5, failed=0,
    )

    # Create tenant B
    resp = await client.post(
        "/tenants",
        json={"name": f"Tenant B {uuid.uuid4().hex[:6]}", "slug": f"tenant-b-{uuid.uuid4().hex[:6]}"},
    )
    assert resp.status_code == 201
    tenant_b_id = resp.json()["id"]

    # Tenant B should see no logs
    logs_resp = await client.get(f"/tenants/{tenant_b_id}/ingestion/logs")
    assert logs_resp.status_code == 200
    assert logs_resp.json()["total"] == 0
    assert logs_resp.json()["items"] == []

    # Tenant A should see its log
    logs_resp_a = await client.get(f"/tenants/{tenant_id}/ingestion/logs")
    assert logs_resp_a.status_code == 200
    assert logs_resp_a.json()["total"] == 1


async def test_activity_log_ordering(
    client: AsyncClient, tenant_id: str, db: aiosqlite.Connection,
) -> None:
    """Logs should be returned most-recent-first."""
    for i in range(3):
        job = await job_repo.create_job(db, tenant_id, "author", f"Author {i}")
        await job_repo.mark_completed(db, job.id)
        await activity_log_repo.create_log(
            db, tenant_id, job.id, "author", f"Author {i}",
            total_fetched=i + 1, succeeded=i + 1, failed=0,
        )

    logs_resp = await client.get(f"/tenants/{tenant_id}/ingestion/logs")
    assert logs_resp.status_code == 200
    items = logs_resp.json()["items"]
    assert len(items) == 3

    # Most recent first: Author 2, Author 1, Author 0
    assert items[0]["query_value"] == "Author 2"
    assert items[1]["query_value"] == "Author 1"
    assert items[2]["query_value"] == "Author 0"


async def test_activity_log_pagination(
    client: AsyncClient, tenant_id: str, db: aiosqlite.Connection,
) -> None:
    """Verify offset and limit work correctly."""
    for i in range(5):
        job = await job_repo.create_job(db, tenant_id, "author", f"Author {i}")
        await job_repo.mark_completed(db, job.id)
        await activity_log_repo.create_log(
            db, tenant_id, job.id, "author", f"Author {i}",
            total_fetched=i, succeeded=i, failed=0,
        )

    # Get first page of 2
    resp = await client.get(f"/tenants/{tenant_id}/ingestion/logs?limit=2&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["offset"] == 0
    assert data["limit"] == 2

    # Get second page of 2
    resp2 = await client.get(f"/tenants/{tenant_id}/ingestion/logs?limit=2&offset=2")
    data2 = resp2.json()
    assert len(data2["items"]) == 2
    assert data2["total"] == 5

    # Ensure no overlap
    ids_page1 = {item["id"] for item in data["items"]}
    ids_page2 = {item["id"] for item in data2["items"]}
    assert ids_page1.isdisjoint(ids_page2)

    # Get last page
    resp3 = await client.get(f"/tenants/{tenant_id}/ingestion/logs?limit=2&offset=4")
    data3 = resp3.json()
    assert len(data3["items"]) == 1
