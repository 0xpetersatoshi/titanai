import asyncio
import logging

import aiosqlite

from titanai.core.config import Settings
from titanai.db.repositories import ingestion_jobs as job_repo
from titanai.services.openlibrary import OpenLibraryClient
from titanai.workers.ingestion import execute_job

logger = logging.getLogger(__name__)


class WorkerPool:
    def __init__(self, db: aiosqlite.Connection, settings: Settings) -> None:
        self._db = db
        self._settings = settings
        self._tasks: list[asyncio.Task] = []  # type: ignore[type-arg]
        self._running = False
        self._ol_client = OpenLibraryClient(settings)

    async def start(self) -> None:
        reset_count = await job_repo.reset_stale_jobs(self._db)
        if reset_count:
            logger.info("Reset %d stale in_progress jobs to queued", reset_count)

        self._running = True
        for i in range(self._settings.worker_count):
            task = asyncio.create_task(self._worker_loop(i))
            self._tasks.append(task)
        logger.info("Started %d workers", self._settings.worker_count)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self._ol_client.close()
        logger.info("Worker pool stopped")

    async def _worker_loop(self, worker_id: int) -> None:
        while self._running:
            try:
                job = await job_repo.claim_next_job(self._db)
                if job is None:
                    await asyncio.sleep(self._settings.poll_interval_seconds)
                    continue

                logger.info("Worker %d claimed job %s (tenant=%s, %s=%s)",
                            worker_id, job.id, job.tenant_id, job.query_type, job.query_value)
                await execute_job(
                    self._db, self._ol_client,
                    job.id, job.tenant_id, job.query_type, job.query_value,
                )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Worker %d encountered unexpected error", worker_id)
                await asyncio.sleep(self._settings.poll_interval_seconds)
