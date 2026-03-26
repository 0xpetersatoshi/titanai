import logging
from dataclasses import dataclass

import aiosqlite

from titanai.db.repositories import books as book_repo
from titanai.services.openlibrary import OpenLibraryClient, WorkRecord
from titanai.services.versions import compare_and_version

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    total_works: int = 0
    succeeded: int = 0
    failed: int = 0
    errors: list[dict] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


async def run_ingestion(
    db: aiosqlite.Connection,
    ol_client: OpenLibraryClient,
    tenant_id: str,
    query_type: str,
    query_value: str,
) -> IngestionResult:
    result = IngestionResult()

    if query_type == "author":
        docs = await ol_client.search_by_author(query_value)
    elif query_type == "subject":
        docs = await ol_client.search_by_subject(query_value)
    else:
        return result

    result.total_works = len(docs)
    from_subject = query_type == "subject"

    for doc in docs:
        try:
            record = await ol_client.assemble_record(doc, from_subject=from_subject)
            if record is None:
                result.failed += 1
                result.errors.append({"work_id": doc.get("key", "unknown"), "error": "Could not assemble record"})
                continue

            existing_id = await book_repo.book_exists(db, tenant_id, record.ol_work_id)
            if existing_id:
                await compare_and_version(
                    db, tenant_id, existing_id,
                    new_title=record.title,
                    new_authors=record.authors,
                    new_first_publish_year=record.first_publish_year,
                    new_subjects=record.subjects,
                    new_cover_image_url=record.cover_image_url,
                )
                result.succeeded += 1
                continue

            await book_repo.create_book(
                db, tenant_id,
                ol_work_id=record.ol_work_id,
                title=record.title,
                authors=record.authors,
                first_publish_year=record.first_publish_year,
                subjects=record.subjects,
                cover_image_url=record.cover_image_url,
            )
            result.succeeded += 1
        except Exception as exc:
            result.failed += 1
            work_id = doc.get("key", "unknown")
            result.errors.append({"work_id": work_id, "error": str(exc)})
            logger.exception("Failed to process work %s", work_id)

    return result
