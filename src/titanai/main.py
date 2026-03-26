import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from titanai.core.config import get_settings
from titanai.db.connection import get_db_connection, close_db_connection
from titanai.db.schema import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    db = await get_db_connection(settings)
    await create_tables(db)

    # Start workers unless in test mode
    worker_pool = None
    refresh_timer = None
    if not os.environ.get("TITANAI_TEST_MODE"):
        from titanai.workers.pool import WorkerPool
        from titanai.workers.refresh import RefreshTimer

        worker_pool = WorkerPool(db, settings)
        await worker_pool.start()

        refresh_timer = RefreshTimer(db, settings)
        await refresh_timer.start()

    yield

    if refresh_timer:
        await refresh_timer.stop()
    if worker_pool:
        await worker_pool.stop()
    await close_db_connection()


def create_app() -> FastAPI:
    app = FastAPI(title="TitanAI", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    from titanai.api.tenants import router as tenants_router
    from titanai.api.ingestion import router as ingestion_router
    from titanai.api.books import router as books_router
    from titanai.api.reading_lists import router as reading_lists_router
    from titanai.api.metrics import router as metrics_router

    app.include_router(tenants_router)
    app.include_router(ingestion_router)
    app.include_router(books_router)
    app.include_router(reading_lists_router)
    app.include_router(metrics_router)

    return app


app = create_app()
