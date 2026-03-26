import aiosqlite

TABLES = [
    """
    CREATE TABLE IF NOT EXISTS tenants (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        slug TEXT NOT NULL UNIQUE,
        rate_limit_per_minute INTEGER NOT NULL DEFAULT 60,
        ingestion_refresh_hours INTEGER NOT NULL DEFAULT 24,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS books (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id),
        ol_work_id TEXT NOT NULL,
        title TEXT NOT NULL,
        authors TEXT NOT NULL,
        first_publish_year INTEGER,
        subjects TEXT,
        cover_image_url TEXT,
        current_version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(tenant_id, ol_work_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS book_versions (
        id TEXT PRIMARY KEY,
        book_id TEXT NOT NULL REFERENCES books(id),
        version_number INTEGER NOT NULL,
        title TEXT NOT NULL,
        authors TEXT NOT NULL,
        first_publish_year INTEGER,
        subjects TEXT,
        cover_image_url TEXT,
        diff TEXT,
        has_regression INTEGER NOT NULL DEFAULT 0,
        regression_fields TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(book_id, version_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ingestion_jobs (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id),
        query_type TEXT NOT NULL CHECK(query_type IN ('author', 'subject')),
        query_value TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued', 'in_progress', 'completed', 'failed')),
        total_works INTEGER DEFAULT 0,
        processed_works INTEGER DEFAULT 0,
        succeeded INTEGER DEFAULT 0,
        failed INTEGER DEFAULT 0,
        errors TEXT,
        is_auto_refresh INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activity_logs (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id),
        job_id TEXT NOT NULL UNIQUE REFERENCES ingestion_jobs(id),
        query_type TEXT NOT NULL,
        query_value TEXT NOT NULL,
        total_fetched INTEGER NOT NULL,
        succeeded INTEGER NOT NULL,
        failed INTEGER NOT NULL,
        errors TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reading_lists (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id),
        patron_name_hash TEXT NOT NULL,
        patron_email_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reading_list_items (
        id TEXT PRIMARY KEY,
        reading_list_id TEXT NOT NULL REFERENCES reading_lists(id),
        submitted_id TEXT NOT NULL,
        submitted_id_type TEXT NOT NULL CHECK(submitted_id_type IN ('work_id', 'isbn')),
        resolved_ol_work_id TEXT,
        book_id TEXT REFERENCES books(id),
        status TEXT NOT NULL CHECK(status IN ('resolved', 'not_found'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tenant_metrics (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL UNIQUE REFERENCES tenants(id),
        request_count_minute INTEGER NOT NULL DEFAULT 0,
        active_ingestion_jobs INTEGER NOT NULL DEFAULT 0,
        total_books INTEGER NOT NULL DEFAULT 0,
        total_ingestion_jobs INTEGER NOT NULL DEFAULT 0,
        window_start TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_books_tenant ON books(tenant_id)",
    "CREATE INDEX IF NOT EXISTS idx_books_tenant_year ON books(tenant_id, first_publish_year)",
    "CREATE INDEX IF NOT EXISTS idx_book_versions_book ON book_versions(book_id)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_tenant_status ON ingestion_jobs(tenant_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_activity_logs_tenant_created ON activity_logs(tenant_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reading_lists_tenant ON reading_lists(tenant_id)",
    "CREATE INDEX IF NOT EXISTS idx_reading_lists_patron ON reading_lists(tenant_id, patron_email_hash)",
    "CREATE INDEX IF NOT EXISTS idx_reading_list_items_list ON reading_list_items(reading_list_id)",
]


async def create_tables(db: aiosqlite.Connection) -> None:
    for table_ddl in TABLES:
        await db.execute(table_ddl)
    for index_ddl in INDEXES:
        await db.execute(index_ddl)
    await db.commit()
