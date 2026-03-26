import logging

import aiosqlite

from titanai.core.pii import hash_email, hash_name
from titanai.db.repositories import books as book_repo
from titanai.db.repositories import reading_lists as reading_list_repo
from titanai.models.reading_lists import ReadingListBookItem, ReadingListItemResponse, ReadingListResponse
from titanai.services.openlibrary import OpenLibraryClient

logger = logging.getLogger(__name__)


async def submit_reading_list(
    db: aiosqlite.Connection,
    ol_client: OpenLibraryClient,
    tenant_id: str,
    patron_name: str,
    patron_email: str,
    books: list[ReadingListBookItem],
) -> ReadingListResponse:
    name_hash = hash_name(patron_name)
    email_hash = hash_email(patron_email)

    list_id = await reading_list_repo.create_reading_list(db, tenant_id, name_hash, email_hash)

    result_items: list[ReadingListItemResponse] = []
    for book_item in books:
        resolved_book_id = None
        status = "not_found"

        if book_item.id_type == "work_id":
            existing = await book_repo.get_book_by_ol_work_id(db, tenant_id, book_item.id)
            if existing:
                resolved_book_id = existing.id
                status = "resolved"
        elif book_item.id_type == "isbn":
            work_data = await ol_client._request(f"https://openlibrary.org/isbn/{book_item.id}.json")
            if work_data and work_data.get("works"):
                work_key = work_data["works"][0].get("key", "")
                if work_key:
                    existing = await book_repo.get_book_by_ol_work_id(db, tenant_id, work_key)
                    if existing:
                        resolved_book_id = existing.id
                        status = "resolved"

        await reading_list_repo.create_reading_list_item(
            db, list_id, book_item.id, book_item.id_type,
            resolved_ol_work_id=None, book_id=resolved_book_id, status=status,
        )
        result_items.append(ReadingListItemResponse(
            submitted_id=book_item.id, submitted_id_type=book_item.id_type,
            status=status, book_id=resolved_book_id,
        ))

    cursor = await db.execute("SELECT created_at FROM reading_lists WHERE id = ?", (list_id,))
    row = await cursor.fetchone()
    created_at = row[0]  # type: ignore[index]

    return ReadingListResponse(id=list_id, created_at=created_at, books=result_items)
