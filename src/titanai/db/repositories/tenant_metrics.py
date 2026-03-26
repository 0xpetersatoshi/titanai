import uuid
from datetime import datetime, timezone

import aiosqlite


async def _ensure_metrics(db: aiosqlite.Connection, tenant_id: str) -> None:
    cursor = await db.execute("SELECT 1 FROM tenant_metrics WHERE tenant_id = ?", (tenant_id,))
    if await cursor.fetchone() is None:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """INSERT INTO tenant_metrics (id, tenant_id, window_start, updated_at)
            VALUES (?, ?, ?, ?)""",
            (str(uuid.uuid4()), tenant_id, now, now),
        )
        await db.commit()


async def increment_request_count(db: aiosqlite.Connection, tenant_id: str) -> int:
    await _ensure_metrics(db, tenant_id)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    cursor = await db.execute(
        "SELECT window_start, request_count_minute FROM tenant_metrics WHERE tenant_id = ?",
        (tenant_id,),
    )
    row = await cursor.fetchone()
    window_start = row[0]  # type: ignore[index]
    current_count = row[1]  # type: ignore[index]

    window_start_dt = datetime.fromisoformat(window_start)
    elapsed = (now - window_start_dt).total_seconds()

    if elapsed >= 60:
        await db.execute(
            "UPDATE tenant_metrics SET request_count_minute=1, window_start=?, updated_at=? WHERE tenant_id=?",
            (now_iso, now_iso, tenant_id),
        )
        await db.commit()
        return 1
    else:
        new_count = current_count + 1
        await db.execute(
            "UPDATE tenant_metrics SET request_count_minute=?, updated_at=? WHERE tenant_id=?",
            (new_count, now_iso, tenant_id),
        )
        await db.commit()
        return new_count


async def get_metrics(db: aiosqlite.Connection, tenant_id: str) -> dict:
    await _ensure_metrics(db, tenant_id)

    cursor = await db.execute(
        "SELECT request_count_minute, active_ingestion_jobs, total_books, total_ingestion_jobs, updated_at FROM tenant_metrics WHERE tenant_id = ?",
        (tenant_id,),
    )
    row = await cursor.fetchone()

    # Get live counts
    books_cursor = await db.execute("SELECT COUNT(*) FROM books WHERE tenant_id = ?", (tenant_id,))
    total_books = (await books_cursor.fetchone())[0]  # type: ignore[index]

    jobs_cursor = await db.execute("SELECT COUNT(*) FROM ingestion_jobs WHERE tenant_id = ?", (tenant_id,))
    total_jobs = (await jobs_cursor.fetchone())[0]  # type: ignore[index]

    active_cursor = await db.execute(
        "SELECT COUNT(*) FROM ingestion_jobs WHERE tenant_id = ? AND status IN ('queued', 'in_progress')",
        (tenant_id,),
    )
    active_jobs = (await active_cursor.fetchone())[0]  # type: ignore[index]

    return {
        "tenant_id": tenant_id,
        "request_count_minute": row[0],  # type: ignore[index]
        "active_ingestion_jobs": active_jobs,
        "total_books": total_books,
        "total_ingestion_jobs": total_jobs,
        "updated_at": row[4],  # type: ignore[index]
    }


async def get_all_metrics(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute(
        "SELECT t.id, t.name FROM tenants t ORDER BY t.name"
    )
    tenants = await cursor.fetchall()
    results = []
    for tenant_row in tenants:
        tid = tenant_row[0]  # type: ignore[index]
        metrics = await get_metrics(db, tid)
        metrics["tenant_name"] = tenant_row[1]  # type: ignore[index]
        results.append(metrics)
    return results
