import logging

import aiosqlite

from titanai.core.config import Settings
from titanai.db.repositories import activity_logs as activity_log_repo
from titanai.db.repositories import ingestion_jobs as job_repo
from titanai.services.ingestion import run_ingestion
from titanai.services.openlibrary import OpenLibraryClient

logger = logging.getLogger(__name__)


async def execute_job(
    db: aiosqlite.Connection,
    ol_client: OpenLibraryClient,
    job_id: str,
    tenant_id: str,
    query_type: str,
    query_value: str,
) -> None:
    try:
        result = await run_ingestion(db, ol_client, tenant_id, query_type, query_value)
        await job_repo.update_progress(
            db, job_id,
            total_works=result.total_works,
            processed_works=result.succeeded + result.failed,
            succeeded=result.succeeded,
            failed=result.failed,
            errors=result.errors if result.errors else None,
        )
        await job_repo.mark_completed(db, job_id)
        await activity_log_repo.create_log(
            db, tenant_id, job_id, query_type, query_value,
            total_fetched=result.total_works,
            succeeded=result.succeeded,
            failed=result.failed,
            errors=result.errors if result.errors else None,
        )
        logger.info("Job %s completed: %d succeeded, %d failed", job_id, result.succeeded, result.failed)
    except Exception as exc:
        logger.exception("Job %s failed: %s", job_id, exc)
        errors = [{"error": str(exc)}]
        await job_repo.mark_failed(db, job_id, errors=errors)
        await activity_log_repo.create_log(
            db, tenant_id, job_id, query_type, query_value,
            total_fetched=0, succeeded=0, failed=0,
            errors=errors,
        )
