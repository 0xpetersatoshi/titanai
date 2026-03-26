import json
import uuid
from datetime import datetime, timezone

import aiosqlite

from titanai.models.ingestion import IngestionJobResponse


async def create_job(
    db: aiosqlite.Connection,
    tenant_id: str,
    query_type: str,
    query_value: str,
    is_auto_refresh: bool = False,
) -> IngestionJobResponse:
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """INSERT INTO ingestion_jobs (id, tenant_id, query_type, query_value, is_auto_refresh, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (job_id, tenant_id, query_type, query_value, int(is_auto_refresh), now),
    )
    await db.commit()
    return IngestionJobResponse(
        id=job_id, tenant_id=tenant_id, query_type=query_type, query_value=query_value,
        status="queued", total_works=0, processed_works=0, succeeded=0, failed=0,
        is_auto_refresh=is_auto_refresh, created_at=now, started_at=None, completed_at=None,
    )


async def claim_next_job(db: aiosqlite.Connection) -> IngestionJobResponse | None:
    now = datetime.now(timezone.utc).isoformat()
    cursor = await db.execute(
        """UPDATE ingestion_jobs SET status = 'in_progress', started_at = ?
        WHERE id = (
            SELECT j.id FROM ingestion_jobs j
            WHERE j.status = 'queued'
            ORDER BY (SELECT COUNT(*) FROM ingestion_jobs j2
                      WHERE j2.tenant_id = j.tenant_id AND j2.status = 'in_progress') ASC,
                     j.created_at ASC
            LIMIT 1
        )
        RETURNING *""",
        (now,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    await db.commit()
    return _row_to_job(row)


async def update_progress(
    db: aiosqlite.Connection,
    job_id: str,
    total_works: int,
    processed_works: int,
    succeeded: int,
    failed: int,
    errors: list[dict] | None = None,
) -> None:
    await db.execute(
        """UPDATE ingestion_jobs SET total_works=?, processed_works=?, succeeded=?, failed=?, errors=?
        WHERE id=?""",
        (total_works, processed_works, succeeded, failed, json.dumps(errors) if errors else None, job_id),
    )
    await db.commit()


async def mark_completed(db: aiosqlite.Connection, job_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "UPDATE ingestion_jobs SET status='completed', completed_at=? WHERE id=?",
        (now, job_id),
    )
    await db.commit()


async def mark_failed(db: aiosqlite.Connection, job_id: str, errors: list[dict] | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "UPDATE ingestion_jobs SET status='failed', completed_at=?, errors=? WHERE id=?",
        (now, json.dumps(errors) if errors else None, job_id),
    )
    await db.commit()


async def get_job(db: aiosqlite.Connection, tenant_id: str, job_id: str) -> IngestionJobResponse | None:
    cursor = await db.execute(
        "SELECT * FROM ingestion_jobs WHERE id = ? AND tenant_id = ?",
        (job_id, tenant_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_job(row)


async def list_jobs(
    db: aiosqlite.Connection,
    tenant_id: str,
    status: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[IngestionJobResponse], int]:
    where = ["tenant_id = ?"]
    params: list = [tenant_id]
    if status:
        where.append("status = ?")
        params.append(status)
    where_clause = " AND ".join(where)

    cursor = await db.execute(f"SELECT COUNT(*) FROM ingestion_jobs WHERE {where_clause}", params)
    total = (await cursor.fetchone())[0]  # type: ignore[index]

    cursor = await db.execute(
        f"SELECT * FROM ingestion_jobs WHERE {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    rows = await cursor.fetchall()
    return [_row_to_job(row) for row in rows], total


async def count_active_jobs(db: aiosqlite.Connection, tenant_id: str) -> int:
    cursor = await db.execute(
        "SELECT COUNT(*) FROM ingestion_jobs WHERE tenant_id = ? AND status IN ('queued', 'in_progress')",
        (tenant_id,),
    )
    return (await cursor.fetchone())[0]  # type: ignore[index]


async def reset_stale_jobs(db: aiosqlite.Connection) -> int:
    cursor = await db.execute(
        "UPDATE ingestion_jobs SET status = 'queued', started_at = NULL WHERE status = 'in_progress'"
    )
    await db.commit()
    return cursor.rowcount


async def get_completed_queries(db: aiosqlite.Connection, tenant_id: str) -> list[tuple[str, str]]:
    cursor = await db.execute(
        """SELECT DISTINCT query_type, query_value FROM ingestion_jobs
        WHERE tenant_id = ? AND status = 'completed'""",
        (tenant_id,),
    )
    return [(row[0], row[1]) for row in await cursor.fetchall()]  # type: ignore[index]


async def has_active_job(db: aiosqlite.Connection, tenant_id: str, query_type: str, query_value: str) -> bool:
    cursor = await db.execute(
        """SELECT 1 FROM ingestion_jobs
        WHERE tenant_id = ? AND query_type = ? AND query_value = ? AND status IN ('queued', 'in_progress')
        LIMIT 1""",
        (tenant_id, query_type, query_value),
    )
    return await cursor.fetchone() is not None


def _row_to_job(row: aiosqlite.Row) -> IngestionJobResponse:
    d = dict(row)
    d["is_auto_refresh"] = bool(d["is_auto_refresh"])
    if d.get("errors"):
        d["errors"] = json.loads(d["errors"])
    return IngestionJobResponse(**d)
