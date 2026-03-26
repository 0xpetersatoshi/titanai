from fastapi import APIRouter, Depends, HTTPException
import aiosqlite

from titanai.api.dependencies import TenantContext, get_current_tenant
from titanai.db.connection import get_db
from titanai.db.repositories import books as book_repo
from titanai.db.repositories import book_versions as version_repo
from titanai.models.books import BookResponse, BookList, BookVersionResponse, BookVersionList

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["books"])


@router.get("/books", response_model=BookList)
async def list_books(
    q: str | None = None,
    author: str | None = None,
    subject: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    offset: int = 0,
    limit: int = 20,
    tenant: TenantContext = Depends(get_current_tenant),
    db: aiosqlite.Connection = Depends(get_db),
) -> BookList:
    items, total = await book_repo.list_books(
        db, tenant.id, offset, limit,
        author=author, subject=subject, year_min=year_min, year_max=year_max, q=q,
    )
    return BookList(items=items, total=total, offset=offset, limit=limit)


@router.get("/books/{book_id}", response_model=BookResponse)
async def get_book(
    book_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: aiosqlite.Connection = Depends(get_db),
) -> BookResponse:
    book = await book_repo.get_book(db, tenant.id, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


@router.get("/books/{book_id}/versions", response_model=BookVersionList)
async def list_versions(
    book_id: str,
    offset: int = 0,
    limit: int = 20,
    tenant: TenantContext = Depends(get_current_tenant),
    db: aiosqlite.Connection = Depends(get_db),
) -> BookVersionList:
    book = await book_repo.get_book(db, tenant.id, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    items, total = await version_repo.list_versions(db, tenant.id, book_id, offset, limit)
    return BookVersionList(items=items, total=total, offset=offset, limit=limit)


@router.get("/books/{book_id}/versions/{version_id}", response_model=BookVersionResponse)
async def get_version(
    book_id: str,
    version_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: aiosqlite.Connection = Depends(get_db),
) -> BookVersionResponse:
    version = await version_repo.get_version(db, tenant.id, book_id, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return version
