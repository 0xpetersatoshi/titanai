import uuid
from datetime import datetime, timezone

import aiosqlite

from titanai.models.tenants import TenantResponse


async def create_tenant(db: aiosqlite.Connection, name: str, slug: str) -> TenantResponse:
    tenant_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO tenants (id, name, slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (tenant_id, name, slug, now, now),
    )
    await db.commit()
    return TenantResponse(
        id=tenant_id, name=name, slug=slug,
        rate_limit_per_minute=60, ingestion_refresh_hours=24,
        created_at=now, updated_at=now,
    )


async def get_tenant(db: aiosqlite.Connection, tenant_id: str) -> TenantResponse | None:
    cursor = await db.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return TenantResponse(**dict(row))


async def list_tenants(db: aiosqlite.Connection, offset: int = 0, limit: int = 20) -> tuple[list[TenantResponse], int]:
    cursor = await db.execute("SELECT COUNT(*) FROM tenants")
    total = (await cursor.fetchone())[0]  # type: ignore[index]
    cursor = await db.execute("SELECT * FROM tenants ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
    rows = await cursor.fetchall()
    items = [TenantResponse(**dict(row)) for row in rows]
    return items, total
