from httpx import AsyncClient


async def test_create_tenant(client: AsyncClient) -> None:
    resp = await client.post("/tenants", json={"name": "Springfield Library", "slug": "springfield"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Springfield Library"
    assert data["slug"] == "springfield"
    assert "id" in data
    assert data["rate_limit_per_minute"] == 60
    assert data["ingestion_refresh_hours"] == 24


async def test_create_tenant_duplicate_name(client: AsyncClient) -> None:
    await client.post("/tenants", json={"name": "Dup Library", "slug": "dup-1"})
    resp = await client.post("/tenants", json={"name": "Dup Library", "slug": "dup-2"})
    assert resp.status_code == 422


async def test_create_tenant_duplicate_slug(client: AsyncClient) -> None:
    await client.post("/tenants", json={"name": "Library A", "slug": "same-slug"})
    resp = await client.post("/tenants", json={"name": "Library B", "slug": "same-slug"})
    assert resp.status_code == 422


async def test_get_tenant(client: AsyncClient, tenant_id: str) -> None:
    resp = await client.get(f"/tenants/{tenant_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == tenant_id


async def test_get_tenant_not_found(client: AsyncClient) -> None:
    resp = await client.get("/tenants/nonexistent-id")
    assert resp.status_code == 404


async def test_list_tenants(client: AsyncClient, tenant_id: str) -> None:
    resp = await client.get("/tenants")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1
    assert any(t["id"] == tenant_id for t in data["items"])


async def test_create_tenant_empty_name(client: AsyncClient) -> None:
    resp = await client.post("/tenants", json={"name": "", "slug": "valid"})
    assert resp.status_code == 422
