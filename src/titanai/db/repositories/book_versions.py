import json
import uuid
from datetime import datetime, timezone

import aiosqlite

from titanai.models.books import BookVersionResponse


async def create_version(
    db: aiosqlite.Connection,
    book_id: str,
    version_number: int,
    title: str,
    authors: list[str],
    first_publish_year: int | None,
    subjects: list[str] | None,
    cover_image_url: str | None,
    diff: dict | None,
    has_regression: bool,
    regression_fields: list[str] | None,
) -> BookVersionResponse:
    version_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """INSERT INTO book_versions (id, book_id, version_number, title, authors, first_publish_year, subjects, cover_image_url, diff, has_regression, regression_fields, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            version_id, book_id, version_number, title, json.dumps(authors),
            first_publish_year, json.dumps(subjects) if subjects else None,
            cover_image_url, json.dumps(diff) if diff else None,
            1 if has_regression else 0,
            json.dumps(regression_fields) if regression_fields else None,
            now,
        ),
    )
    await db.commit()
    return BookVersionResponse(
        id=version_id, version_number=version_number, title=title,
        authors=authors, first_publish_year=first_publish_year,
        subjects=subjects, cover_image_url=cover_image_url,
        diff=diff, has_regression=has_regression,
        regression_fields=regression_fields, created_at=now,
    )


async def list_versions(
    db: aiosqlite.Connection,
    tenant_id: str,
    book_id: str,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[BookVersionResponse], int]:
    cursor = await db.execute(
        "SELECT COUNT(*) FROM book_versions bv JOIN books b ON bv.book_id = b.id WHERE bv.book_id = ? AND b.tenant_id = ?",
        (book_id, tenant_id),
    )
    total = (await cursor.fetchone())[0]  # type: ignore[index]

    cursor = await db.execute(
        "SELECT bv.* FROM book_versions bv JOIN books b ON bv.book_id = b.id WHERE bv.book_id = ? AND b.tenant_id = ? ORDER BY bv.version_number DESC LIMIT ? OFFSET ?",
        (book_id, tenant_id, limit, offset),
    )
    rows = await cursor.fetchall()
    items = [_row_to_version(row) for row in rows]
    return items, total


async def get_version(
    db: aiosqlite.Connection,
    tenant_id: str,
    book_id: str,
    version_id: str,
) -> BookVersionResponse | None:
    cursor = await db.execute(
        "SELECT bv.* FROM book_versions bv JOIN books b ON bv.book_id = b.id WHERE bv.id = ? AND bv.book_id = ? AND b.tenant_id = ?",
        (version_id, book_id, tenant_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_version(row)


def _row_to_version(row: aiosqlite.Row) -> BookVersionResponse:
    d = dict(row)
    d["authors"] = json.loads(d["authors"])
    d["subjects"] = json.loads(d["subjects"]) if d.get("subjects") else None
    d["diff"] = json.loads(d["diff"]) if d.get("diff") else None
    d["has_regression"] = bool(d["has_regression"])
    d["regression_fields"] = json.loads(d["regression_fields"]) if d.get("regression_fields") else None
    # Remove book_id from dict since it's not in the response model
    d.pop("book_id", None)
    return BookVersionResponse(**d)
