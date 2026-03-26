from fastapi import APIRouter, Depends
import aiosqlite

from titanai.api.dependencies import TenantContext, get_current_tenant
from titanai.db.connection import get_db
from titanai.db.repositories import tenant_metrics as metrics_repo

router = APIRouter(tags=["metrics"])


@router.get("/tenants/{tenant_id}/metrics")
async def get_tenant_metrics(
    tenant: TenantContext = Depends(get_current_tenant),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    return await metrics_repo.get_metrics(db, tenant.id)


@router.get("/metrics")
async def get_aggregate_metrics(
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    tenants = await metrics_repo.get_all_metrics(db)
    return {"tenants": tenants}
