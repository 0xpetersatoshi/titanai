import uuid
from datetime import datetime, timezone

import aiosqlite

from titanai.models.reading_lists import (
    ReadingListItemResponse,
    ReadingListResponse,
    ReadingListSummary,
)


async def create_reading_list(
    db: aiosqlite.Connection,
    tenant_id: str,
    patron_name_hash: str,
    patron_email_hash: str,
) -> str:
    list_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO reading_lists (id, tenant_id, patron_name_hash, patron_email_hash, created_at) VALUES (?, ?, ?, ?, ?)",
        (list_id, tenant_id, patron_name_hash, patron_email_hash, now),
    )
    await db.commit()
    return list_id


async def create_reading_list_item(
    db: aiosqlite.Connection,
    reading_list_id: str,
    submitted_id: str,
    submitted_id_type: str,
    resolved_ol_work_id: str | None,
    book_id: str | None,
    status: str,
) -> None:
    item_id = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO reading_list_items (id, reading_list_id, submitted_id, submitted_id_type, resolved_ol_work_id, book_id, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (item_id, reading_list_id, submitted_id, submitted_id_type, resolved_ol_work_id, book_id, status),
    )
    await db.commit()


async def get_reading_list(
    db: aiosqlite.Connection, tenant_id: str, list_id: str
) -> ReadingListResponse | None:
    cursor = await db.execute(
        "SELECT id, created_at FROM reading_lists WHERE id = ? AND tenant_id = ?",
        (list_id, tenant_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None

    items_cursor = await db.execute(
        "SELECT submitted_id, submitted_id_type, status, book_id FROM reading_list_items WHERE reading_list_id = ?",
        (list_id,),
    )
    items = [
        ReadingListItemResponse(**dict(item_row))
        for item_row in await items_cursor.fetchall()
    ]
    return ReadingListResponse(id=row[0], created_at=row[1], books=items)  # type: ignore[index]


async def list_reading_lists(
    db: aiosqlite.Connection, tenant_id: str, offset: int = 0, limit: int = 20
) -> tuple[list[ReadingListSummary], int]:
    cursor = await db.execute(
        "SELECT COUNT(*) FROM reading_lists WHERE tenant_id = ?", (tenant_id,)
    )
    total = (await cursor.fetchone())[0]  # type: ignore[index]

    cursor = await db.execute(
        "SELECT id, patron_name_hash, patron_email_hash, created_at FROM reading_lists WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (tenant_id, limit, offset),
    )
    rows = await cursor.fetchall()
    items = [ReadingListSummary(**dict(row)) for row in rows]
    return items, total
