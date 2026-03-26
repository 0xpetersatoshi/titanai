import json
import uuid
from datetime import datetime, timezone

import aiosqlite

from titanai.models.books import BookResponse


async def create_book(
    db: aiosqlite.Connection,
    tenant_id: str,
    ol_work_id: str,
    title: str,
    authors: list[str],
    first_publish_year: int | None,
    subjects: list[str] | None,
    cover_image_url: str | None,
) -> BookResponse:
    book_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    authors_json = json.dumps(authors)
    subjects_json = json.dumps(subjects) if subjects else None
    await db.execute(
        """INSERT INTO books (id, tenant_id, ol_work_id, title, authors, first_publish_year, subjects, cover_image_url, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (book_id, tenant_id, ol_work_id, title, authors_json, first_publish_year, subjects_json, cover_image_url, now, now),
    )
    await db.commit()
    return BookResponse(
        id=book_id, ol_work_id=ol_work_id, title=title, authors=authors,
        first_publish_year=first_publish_year, subjects=subjects,
        cover_image_url=cover_image_url, current_version=1,
        created_at=now, updated_at=now,
    )


async def book_exists(db: aiosqlite.Connection, tenant_id: str, ol_work_id: str) -> str | None:
    cursor = await db.execute(
        "SELECT id FROM books WHERE tenant_id = ? AND ol_work_id = ?",
        (tenant_id, ol_work_id),
    )
    row = await cursor.fetchone()
    return row[0] if row else None  # type: ignore[index]


async def get_book(db: aiosqlite.Connection, tenant_id: str, book_id: str) -> BookResponse | None:
    cursor = await db.execute(
        "SELECT * FROM books WHERE id = ? AND tenant_id = ?",
        (book_id, tenant_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_book(row)


async def get_book_by_ol_work_id(db: aiosqlite.Connection, tenant_id: str, ol_work_id: str) -> BookResponse | None:
    cursor = await db.execute(
        "SELECT * FROM books WHERE tenant_id = ? AND ol_work_id = ?",
        (tenant_id, ol_work_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_book(row)


async def list_books(
    db: aiosqlite.Connection,
    tenant_id: str,
    offset: int = 0,
    limit: int = 20,
    author: str | None = None,
    subject: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    q: str | None = None,
) -> tuple[list[BookResponse], int]:
    where = ["tenant_id = ?"]
    params: list = [tenant_id]

    if author:
        where.append("authors LIKE ?")
        params.append(f"%{author}%")
    if subject:
        where.append("subjects LIKE ?")
        params.append(f"%{subject}%")
    if year_min is not None:
        where.append("first_publish_year >= ?")
        params.append(year_min)
    if year_max is not None:
        where.append("first_publish_year <= ?")
        params.append(year_max)
    if q:
        where.append("(title LIKE ? OR authors LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

    where_clause = " AND ".join(where)

    cursor = await db.execute(f"SELECT COUNT(*) FROM books WHERE {where_clause}", params)
    total = (await cursor.fetchone())[0]  # type: ignore[index]

    cursor = await db.execute(
        f"SELECT * FROM books WHERE {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    rows = await cursor.fetchall()
    items = [_row_to_book(row) for row in rows]
    return items, total


async def update_book(
    db: aiosqlite.Connection,
    tenant_id: str,
    book_id: str,
    title: str,
    authors: list[str],
    first_publish_year: int | None,
    subjects: list[str] | None,
    cover_image_url: str | None,
    current_version: int,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """UPDATE books SET title=?, authors=?, first_publish_year=?, subjects=?, cover_image_url=?,
        current_version=?, updated_at=? WHERE id=? AND tenant_id=?""",
        (title, json.dumps(authors), first_publish_year, json.dumps(subjects) if subjects else None,
         cover_image_url, current_version, now, book_id, tenant_id),
    )
    await db.commit()


def _row_to_book(row: aiosqlite.Row) -> BookResponse:
    d = dict(row)
    d["authors"] = json.loads(d["authors"])
    d["subjects"] = json.loads(d["subjects"]) if d.get("subjects") else None
    return BookResponse(**d)
