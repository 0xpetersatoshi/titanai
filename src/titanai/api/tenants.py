from fastapi import APIRouter, Depends, HTTPException
import aiosqlite

from titanai.db.connection import get_db
from titanai.db.repositories import tenants as tenant_repo
from titanai.models.tenants import TenantCreate, TenantResponse, TenantList

router = APIRouter(tags=["tenants"])


@router.post("/tenants", response_model=TenantResponse, status_code=201)
async def create_tenant(body: TenantCreate, db: aiosqlite.Connection = Depends(get_db)) -> TenantResponse:
    if not body.name.strip() or not body.slug.strip():
        raise HTTPException(status_code=422, detail="Name and slug must be non-empty")
    try:
        return await tenant_repo.create_tenant(db, body.name.strip(), body.slug.strip())
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=422, detail="Tenant name or slug already exists")


@router.get("/tenants", response_model=TenantList)
async def list_tenants(
    offset: int = 0, limit: int = 20, db: aiosqlite.Connection = Depends(get_db)
) -> TenantList:
    items, total = await tenant_repo.list_tenants(db, offset, limit)
    return TenantList(items=items, total=total, offset=offset, limit=limit)


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: str, db: aiosqlite.Connection = Depends(get_db)) -> TenantResponse:
    tenant = await tenant_repo.get_tenant(db, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant
