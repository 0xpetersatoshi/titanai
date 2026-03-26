import os
import uuid
from collections.abc import AsyncIterator

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("TITANAI_PII_SECRET_KEY", "test-secret-key-that-is-at-least-32-bytes-long!!")
os.environ.setdefault("TITANAI_DB_PATH", ":memory:")
os.environ["TITANAI_TEST_MODE"] = "1"


@pytest.fixture
async def db() -> AsyncIterator[aiosqlite.Connection]:
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    from titanai.db.schema import create_tables

    await create_tables(conn)
    yield conn
    await conn.close()


@pytest.fixture
async def client(db: aiosqlite.Connection) -> AsyncIterator[AsyncClient]:
    from titanai.db import connection as conn_module
    from titanai.main import create_app

    original_db = conn_module._db
    conn_module._db = db

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    conn_module._db = original_db


@pytest.fixture
async def tenant_id(client: AsyncClient) -> str:
    resp = await client.post("/tenants", json={"name": f"Test Library {uuid.uuid4().hex[:6]}", "slug": f"test-{uuid.uuid4().hex[:6]}"})
    assert resp.status_code == 201
    return resp.json()["id"]
