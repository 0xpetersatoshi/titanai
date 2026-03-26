import asyncio
import logging
from datetime import datetime, timezone, timedelta

import aiosqlite

from titanai.core.config import Settings
from titanai.db.repositories import ingestion_jobs as job_repo
from titanai.db.repositories import tenants as tenant_repo

logger = logging.getLogger(__name__)


class RefreshTimer:
    def __init__(self, db: aiosqlite.Connection, settings: Settings) -> None:
        self._db = db
        self._settings = settings
        self._task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Refresh timer started (every %d minutes)", self._settings.refresh_check_interval_minutes)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Refresh timer stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._settings.refresh_check_interval_minutes * 60)
                await self._check_staleness()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Refresh timer error")

    async def _check_staleness(self) -> None:
        tenants, _ = await tenant_repo.list_tenants(self._db, offset=0, limit=1000)
        now = datetime.now(timezone.utc)

        for tenant in tenants:
            threshold = now - timedelta(hours=tenant.ingestion_refresh_hours)
            completed_queries = await job_repo.get_completed_queries(self._db, tenant.id)

            for query_type, query_value in completed_queries:
                if await job_repo.has_active_job(self._db, tenant.id, query_type, query_value):
                    continue
                await job_repo.create_job(
                    self._db, tenant.id, query_type, query_value, is_auto_refresh=True,
                )
                logger.info("Auto-refresh job created for tenant %s: %s=%s", tenant.id, query_type, query_value)
