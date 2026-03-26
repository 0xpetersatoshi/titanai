import asyncio
import logging
from dataclasses import dataclass, field

import httpx

from titanai.core.config import Settings

logger = logging.getLogger(__name__)

BASE_URL = "https://openlibrary.org"
COVERS_URL = "https://covers.openlibrary.org"
USER_AGENT = "TitanAI/0.1.0 (contact@example.com)"


@dataclass
class WorkRecord:
    ol_work_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    first_publish_year: int | None = None
    subjects: list[str] = field(default_factory=list)
    cover_image_url: str | None = None


class OpenLibraryClient:
    def __init__(self, settings: Settings) -> None:
        self._semaphore = asyncio.Semaphore(settings.ol_rate_limit_per_second)
        self._timeout = settings.ol_request_timeout_seconds
        self._max_retries = settings.max_retries_per_request
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=self._timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, url: str) -> dict | None:
        for attempt in range(self._max_retries):
            async with self._semaphore:
                try:
                    resp = await self._client.get(url)
                    if resp.status_code == 200:
                        return resp.json()
                    if resp.status_code == 429:
                        retry_after = int(resp.headers.get("Retry-After", "5"))
                        logger.warning("Rate limited by OL, waiting %ds", retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    if resp.status_code >= 500:
                        wait = (2**attempt)
                        logger.warning("OL server error %d, retrying in %ds", resp.status_code, wait)
                        await asyncio.sleep(wait)
                        continue
                    logger.warning("OL returned %d for %s", resp.status_code, url)
                    return None
                except httpx.TimeoutException:
                    wait = (2**attempt)
                    logger.warning("OL timeout for %s, retrying in %ds", url, wait)
                    await asyncio.sleep(wait)
                    continue
        return None

    async def search_by_author(self, author: str) -> list[dict]:
        data = await self._request(f"{BASE_URL}/search.json?author={httpx.QueryParams({'q': author})['q']}&limit=100")
        if data is None:
            return []
        return data.get("docs", [])

    async def search_by_subject(self, subject: str) -> list[dict]:
        subject_path = subject.lower().replace(" ", "_")
        data = await self._request(f"{BASE_URL}/subjects/{subject_path}.json?limit=100")
        if data is None:
            return []
        return data.get("works", [])

    async def get_work(self, work_id: str) -> dict | None:
        return await self._request(f"{BASE_URL}{work_id}.json")

    async def get_author(self, author_id: str) -> dict | None:
        return await self._request(f"{BASE_URL}{author_id}.json")

    async def assemble_record(self, doc: dict, from_subject: bool = False) -> WorkRecord | None:
        if from_subject:
            work_key = doc.get("key", "")
            title = doc.get("title", "")
            authors = [a.get("name", "") for a in doc.get("authors", []) if a.get("name")]
            cover_id = doc.get("cover_id")
            subjects = [s for s in doc.get("subject", [])[:20]] if doc.get("subject") else []
            first_publish_year = doc.get("first_publish_year")
        else:
            work_key = doc.get("key", "")
            title = doc.get("title", "")
            authors = doc.get("author_name", []) or []
            cover_id = doc.get("cover_i")
            subjects = (doc.get("subject", []) or [])[:20]
            first_publish_year = doc.get("first_publish_year")

        if not work_key or not title:
            return None

        # Follow up for missing data
        if not authors or not subjects:
            work_data = await self.get_work(work_key)
            if work_data:
                if not subjects:
                    subjects = (work_data.get("subjects", []) or [])[:20]
                if not authors and work_data.get("authors"):
                    author_refs = work_data["authors"]
                    for ref in author_refs[:5]:
                        author_key = ref.get("author", {}).get("key") if isinstance(ref.get("author"), dict) else None
                        if author_key:
                            author_data = await self.get_author(author_key)
                            if author_data and author_data.get("name"):
                                authors.append(author_data["name"])

        cover_url = None
        if cover_id:
            cover_url = f"{COVERS_URL}/b/id/{cover_id}-M.jpg"

        return WorkRecord(
            ol_work_id=work_key,
            title=title,
            authors=authors if authors else ["Unknown"],
            first_publish_year=first_publish_year,
            subjects=subjects if subjects else None,
            cover_image_url=cover_url,
        )
