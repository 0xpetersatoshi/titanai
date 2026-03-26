from dataclasses import dataclass

from fastapi import Depends, HTTPException, Path
import aiosqlite

from titanai.db.connection import get_db
from titanai.db.repositories import tenants as tenant_repo
from titanai.db.repositories import tenant_metrics as metrics_repo


@dataclass
class TenantContext:
    id: str
    rate_limit_per_minute: int
    ingestion_refresh_hours: int


async def get_current_tenant(
    tenant_id: str = Path(...),
    db: aiosqlite.Connection = Depends(get_db),
) -> TenantContext:
    tenant = await tenant_repo.get_tenant(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Rate limit check
    count = await metrics_repo.increment_request_count(db, tenant.id)
    if count > tenant.rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="Rate limit exceeded", headers={"Retry-After": "60"})

    return TenantContext(
        id=tenant.id,
        rate_limit_per_minute=tenant.rate_limit_per_minute,
        ingestion_refresh_hours=tenant.ingestion_refresh_hours,
    )
