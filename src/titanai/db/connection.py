import aiosqlite

from titanai.core.config import Settings

_db: aiosqlite.Connection | None = None


async def get_db_connection(settings: Settings) -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(settings.db_path)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def close_db_connection() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def get_db() -> aiosqlite.Connection:
    """Dependency for FastAPI routes. Requires init_db() called first."""
    if _db is None:
        raise RuntimeError("Database not initialized. Call get_db_connection() first.")
    return _db
