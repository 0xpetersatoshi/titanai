import json
import uuid
from datetime import datetime, timezone

import aiosqlite

from titanai.models.ingestion import ActivityLogResponse


async def create_log(
    db: aiosqlite.Connection,
    tenant_id: str,
    job_id: str,
    query_type: str,
    query_value: str,
    total_fetched: int,
    succeeded: int,
    failed: int,
    errors: list[dict] | None = None,
) -> ActivityLogResponse:
    log_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    errors_json = json.dumps(errors) if errors else None
    await db.execute(
        """INSERT INTO activity_logs (id, tenant_id, job_id, query_type, query_value, total_fetched, succeeded, failed, errors, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (log_id, tenant_id, job_id, query_type, query_value, total_fetched, succeeded, failed, errors_json, now),
    )
    await db.commit()
    return ActivityLogResponse(
        id=log_id, tenant_id=tenant_id, job_id=job_id,
        query_type=query_type, query_value=query_value,
        total_fetched=total_fetched, succeeded=succeeded, failed=failed,
        errors=errors, created_at=now,
    )


async def list_logs(
    db: aiosqlite.Connection,
    tenant_id: str,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[ActivityLogResponse], int]:
    cursor = await db.execute(
        "SELECT COUNT(*) FROM activity_logs WHERE tenant_id = ?", (tenant_id,)
    )
    total = (await cursor.fetchone())[0]  # type: ignore[index]

    cursor = await db.execute(
        "SELECT * FROM activity_logs WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (tenant_id, limit, offset),
    )
    rows = await cursor.fetchall()
    items = [_row_to_log(row) for row in rows]
    return items, total


def _row_to_log(row: aiosqlite.Row) -> ActivityLogResponse:
    d = dict(row)
    if d.get("errors"):
        d["errors"] = json.loads(d["errors"])
    return ActivityLogResponse(**d)
