from fastapi import APIRouter, Depends, HTTPException
import aiosqlite

from titanai.api.dependencies import TenantContext, get_current_tenant
from titanai.core.config import get_settings
from titanai.db.connection import get_db
from titanai.db.repositories import reading_lists as reading_list_repo
from titanai.models.reading_lists import (
    ReadingListCreate,
    ReadingListResponse,
    ReadingListSummaryList,
)
from titanai.services.openlibrary import OpenLibraryClient
from titanai.services.reading_lists import submit_reading_list

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["reading-lists"])


@router.post("/reading-lists", response_model=ReadingListResponse, status_code=201)
async def create_reading_list(
    body: ReadingListCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    db: aiosqlite.Connection = Depends(get_db),
) -> ReadingListResponse:
    if not body.books:
        raise HTTPException(status_code=422, detail="At least one book is required")
    if not body.patron_name.strip() or not body.patron_email.strip():
        raise HTTPException(status_code=422, detail="Patron name and email are required")

    for book in body.books:
        if book.id_type not in ("work_id", "isbn"):
            raise HTTPException(status_code=422, detail="id_type must be 'work_id' or 'isbn'")

    settings = get_settings()
    ol_client = OpenLibraryClient(settings)
    try:
        return await submit_reading_list(
            db, ol_client, tenant.id,
            body.patron_name, body.patron_email, body.books,
        )
    finally:
        await ol_client.close()


@router.get("/reading-lists", response_model=ReadingListSummaryList)
async def list_reading_lists(
    offset: int = 0,
    limit: int = 20,
    tenant: TenantContext = Depends(get_current_tenant),
    db: aiosqlite.Connection = Depends(get_db),
) -> ReadingListSummaryList:
    items, total = await reading_list_repo.list_reading_lists(db, tenant.id, offset, limit)
    return ReadingListSummaryList(items=items, total=total, offset=offset, limit=limit)


@router.get("/reading-lists/{list_id}", response_model=ReadingListResponse)
async def get_reading_list(
    list_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: aiosqlite.Connection = Depends(get_db),
) -> ReadingListResponse:
    result = await reading_list_repo.get_reading_list(db, tenant.id, list_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Reading list not found")
    return result
