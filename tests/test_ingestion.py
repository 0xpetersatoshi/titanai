import pytest
from httpx import AsyncClient


@pytest.mark.slow
async def test_ingest_by_author(client: AsyncClient, tenant_id: str) -> None:
    """Ingest a known author with few works from live OL API."""
    resp = await client.post(
        f"/tenants/{tenant_id}/ingestion",
        json={"query_type": "author", "query_value": "Octavia Butler"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_works"] > 0
    assert data["succeeded"] > 0

    # Verify books are stored
    books_resp = await client.get(f"/tenants/{tenant_id}/books")
    assert books_resp.status_code == 200
    books = books_resp.json()
    assert books["total"] > 0

    # Verify fields populated
    book = books["items"][0]
    assert book["title"]
    assert book["authors"]
    assert book["ol_work_id"]


@pytest.mark.slow
async def test_ingest_deduplication(client: AsyncClient, tenant_id: str) -> None:
    """Ingesting same author twice should not create duplicates."""
    await client.post(
        f"/tenants/{tenant_id}/ingestion",
        json={"query_type": "author", "query_value": "Octavia Butler"},
    )
    books_resp1 = await client.get(f"/tenants/{tenant_id}/books")
    count1 = books_resp1.json()["total"]

    await client.post(
        f"/tenants/{tenant_id}/ingestion",
        json={"query_type": "author", "query_value": "Octavia Butler"},
    )
    books_resp2 = await client.get(f"/tenants/{tenant_id}/books")
    count2 = books_resp2.json()["total"]

    assert count1 == count2


@pytest.mark.slow
async def test_ingest_cross_tenant_isolation(client: AsyncClient, tenant_id: str) -> None:
    """Books ingested for tenant A should not be visible to tenant B."""
    await client.post(
        f"/tenants/{tenant_id}/ingestion",
        json={"query_type": "author", "query_value": "Octavia Butler"},
    )

    # Create tenant B
    resp = await client.post("/tenants", json={"name": "Other Library", "slug": "other-lib"})
    tenant_b_id = resp.json()["id"]

    # Tenant B should see zero books
    books_resp = await client.get(f"/tenants/{tenant_b_id}/books")
    assert books_resp.json()["total"] == 0


async def test_ingest_invalid_query_type(client: AsyncClient, tenant_id: str) -> None:
    resp = await client.post(
        f"/tenants/{tenant_id}/ingestion",
        json={"query_type": "invalid", "query_value": "test"},
    )
    assert resp.status_code == 422
