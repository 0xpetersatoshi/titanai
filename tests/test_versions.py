import json
import uuid
from datetime import datetime, timezone

import aiosqlite
from httpx import AsyncClient

from titanai.services.versions import compare_and_version


async def _seed_book(db: aiosqlite.Connection, tenant_id: str, **overrides) -> str:
    """Insert a test book directly into DB, return book ID."""
    book_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    defaults = {
        "ol_work_id": f"/works/OL{uuid.uuid4().hex[:6]}W",
        "title": "Original Title",
        "authors": json.dumps(["Author A"]),
        "first_publish_year": 2000,
        "subjects": json.dumps(["Fiction", "Adventure"]),
        "cover_image_url": "https://covers.openlibrary.org/b/id/1-M.jpg",
        "current_version": 1,
    }
    defaults.update(overrides)
    await db.execute(
        """INSERT INTO books (id, tenant_id, ol_work_id, title, authors, first_publish_year, subjects, cover_image_url, current_version, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            book_id, tenant_id, defaults["ol_work_id"], defaults["title"],
            defaults["authors"], defaults["first_publish_year"],
            defaults["subjects"], defaults["cover_image_url"],
            defaults["current_version"], now, now,
        ),
    )
    await db.commit()
    return book_id


async def test_version_created_on_change(db: aiosqlite.Connection, tenant_id: str, client: AsyncClient) -> None:
    book_id = await _seed_book(db, tenant_id)

    created = await compare_and_version(
        db, tenant_id, book_id,
        new_title="Updated Title",
        new_authors=["Author A"],
        new_first_publish_year=2000,
        new_subjects=["Fiction", "Adventure"],
        new_cover_image_url="https://covers.openlibrary.org/b/id/1-M.jpg",
    )
    assert created is True

    # Verify version was created with correct diff
    cursor = await db.execute(
        "SELECT * FROM book_versions WHERE book_id = ?", (book_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    version = dict(row)
    assert version["version_number"] == 2
    assert version["title"] == "Updated Title"
    diff = json.loads(version["diff"])
    assert "title" in diff
    assert diff["title"]["old"] == "Original Title"
    assert diff["title"]["new"] == "Updated Title"

    # Verify book row was updated
    cursor = await db.execute("SELECT current_version, title FROM books WHERE id = ?", (book_id,))
    book_row = dict(await cursor.fetchone())
    assert book_row["current_version"] == 2
    assert book_row["title"] == "Updated Title"


async def test_no_version_on_unchanged(db: aiosqlite.Connection, tenant_id: str, client: AsyncClient) -> None:
    book_id = await _seed_book(db, tenant_id)

    created = await compare_and_version(
        db, tenant_id, book_id,
        new_title="Original Title",
        new_authors=["Author A"],
        new_first_publish_year=2000,
        new_subjects=["Fiction", "Adventure"],
        new_cover_image_url="https://covers.openlibrary.org/b/id/1-M.jpg",
    )
    assert created is False

    # Verify no version was created
    cursor = await db.execute(
        "SELECT COUNT(*) FROM book_versions WHERE book_id = ?", (book_id,)
    )
    count = (await cursor.fetchone())[0]
    assert count == 0


async def test_regression_handling(db: aiosqlite.Connection, tenant_id: str, client: AsyncClient) -> None:
    book_id = await _seed_book(db, tenant_id)

    created = await compare_and_version(
        db, tenant_id, book_id,
        new_title="Original Title",
        new_authors=["Author A"],
        new_first_publish_year=2000,
        new_subjects=None,
        new_cover_image_url="https://covers.openlibrary.org/b/id/1-M.jpg",
    )
    assert created is True

    # Verify version has regression flagged
    cursor = await db.execute(
        "SELECT * FROM book_versions WHERE book_id = ?", (book_id,)
    )
    version = dict(await cursor.fetchone())
    assert version["has_regression"] == 1
    regression_fields = json.loads(version["regression_fields"])
    assert "subjects" in regression_fields

    # Verify book row preserved the old subjects value
    cursor = await db.execute("SELECT subjects FROM books WHERE id = ?", (book_id,))
    book_row = dict(await cursor.fetchone())
    subjects = json.loads(book_row["subjects"])
    assert subjects == ["Fiction", "Adventure"]


async def test_version_history_endpoint(client: AsyncClient, tenant_id: str, db: aiosqlite.Connection) -> None:
    book_id = await _seed_book(db, tenant_id)

    # Create a version by changing the title
    await compare_and_version(
        db, tenant_id, book_id,
        new_title="New Title",
        new_authors=["Author A"],
        new_first_publish_year=2000,
        new_subjects=["Fiction", "Adventure"],
        new_cover_image_url="https://covers.openlibrary.org/b/id/1-M.jpg",
    )

    resp = await client.get(f"/tenants/{tenant_id}/books/{book_id}/versions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["version_number"] == 2
    assert data["items"][0]["title"] == "New Title"
    assert "title" in data["items"][0]["diff"]

    # Also test single version endpoint
    version_id = data["items"][0]["id"]
    resp = await client.get(f"/tenants/{tenant_id}/books/{book_id}/versions/{version_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == version_id


async def test_version_cross_tenant(client: AsyncClient, tenant_id: str, db: aiosqlite.Connection) -> None:
    book_id = await _seed_book(db, tenant_id)

    # Create a version
    await compare_and_version(
        db, tenant_id, book_id,
        new_title="Changed Title",
        new_authors=["Author A"],
        new_first_publish_year=2000,
        new_subjects=["Fiction", "Adventure"],
        new_cover_image_url="https://covers.openlibrary.org/b/id/1-M.jpg",
    )

    # Create tenant B
    resp = await client.post("/tenants", json={"name": "Other Library", "slug": f"other-{uuid.uuid4().hex[:6]}"})
    assert resp.status_code == 201
    tenant_b = resp.json()["id"]

    # Tenant B should get 404 when accessing tenant A's book versions
    resp = await client.get(f"/tenants/{tenant_b}/books/{book_id}/versions")
    assert resp.status_code == 404
