from fastapi import APIRouter, Depends, HTTPException
import aiosqlite

from titanai.api.dependencies import TenantContext, get_current_tenant
from titanai.core.config import get_settings
from titanai.db.connection import get_db
from titanai.db.repositories import activity_logs as activity_log_repo
from titanai.db.repositories import ingestion_jobs as job_repo
from titanai.models.ingestion import (
    ActivityLogList,
    IngestionJobCreate,
    IngestionJobList,
    IngestionJobResponse,
)
from titanai.services.ingestion import run_ingestion
from titanai.services.openlibrary import OpenLibraryClient

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["ingestion"])


@router.post("/ingestion/jobs", response_model=IngestionJobResponse, status_code=202)
async def create_ingestion_job(
    body: IngestionJobCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    db: aiosqlite.Connection = Depends(get_db),
) -> IngestionJobResponse:
    if body.query_type not in ("author", "subject"):
        raise HTTPException(status_code=422, detail="query_type must be 'author' or 'subject'")
    if not body.query_value.strip():
        raise HTTPException(status_code=422, detail="query_value must be non-empty")

    settings = get_settings()
    active = await job_repo.count_active_jobs(db, tenant.id)
    if active >= settings.max_concurrent_jobs_per_tenant:
        raise HTTPException(status_code=429, detail="Too many active jobs for this tenant")

    return await job_repo.create_job(db, tenant.id, body.query_type, body.query_value.strip())


@router.get("/ingestion/jobs", response_model=IngestionJobList)
async def list_ingestion_jobs(
    status: str | None = None,
    offset: int = 0,
    limit: int = 20,
    tenant: TenantContext = Depends(get_current_tenant),
    db: aiosqlite.Connection = Depends(get_db),
) -> IngestionJobList:
    items, total = await job_repo.list_jobs(db, tenant.id, status=status, offset=offset, limit=limit)
    return IngestionJobList(items=items, total=total, offset=offset, limit=limit)


@router.get("/ingestion/jobs/{job_id}", response_model=IngestionJobResponse)
async def get_ingestion_job(
    job_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: aiosqlite.Connection = Depends(get_db),
) -> IngestionJobResponse:
    job = await job_repo.get_job(db, tenant.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# Keep sync route for testing convenience (will be used by tests that need immediate results)
@router.post("/ingestion")
async def trigger_ingestion_sync(
    body: IngestionJobCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    if body.query_type not in ("author", "subject"):
        raise HTTPException(status_code=422, detail="query_type must be 'author' or 'subject'")
    if not body.query_value.strip():
        raise HTTPException(status_code=422, detail="query_value must be non-empty")

    settings = get_settings()
    ol_client = OpenLibraryClient(settings)
    query_value = body.query_value.strip()

    # Create a job record so we have a job_id for the activity log
    job = await job_repo.create_job(db, tenant.id, body.query_type, query_value)

    try:
        result = await run_ingestion(db, ol_client, tenant.id, body.query_type, query_value)
    finally:
        await ol_client.close()

    await job_repo.mark_completed(db, job.id)

    await activity_log_repo.create_log(
        db, tenant.id, job.id, body.query_type, query_value,
        total_fetched=result.total_works,
        succeeded=result.succeeded,
        failed=result.failed,
        errors=result.errors if result.errors else None,
    )

    return {
        "tenant_id": tenant.id,
        "query_type": body.query_type,
        "query_value": body.query_value,
        "total_works": result.total_works,
        "succeeded": result.succeeded,
        "failed": result.failed,
        "errors": result.errors,
    }


@router.get("/ingestion/logs", response_model=ActivityLogList)
async def list_activity_logs(
    offset: int = 0,
    limit: int = 20,
    tenant: TenantContext = Depends(get_current_tenant),
    db: aiosqlite.Connection = Depends(get_db),
) -> ActivityLogList:
    items, total = await activity_log_repo.list_logs(db, tenant.id, offset=offset, limit=limit)
    return ActivityLogList(items=items, total=total, offset=offset, limit=limit)
