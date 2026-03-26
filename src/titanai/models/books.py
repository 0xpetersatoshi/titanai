from pydantic import BaseModel

from titanai.models.pagination import PaginatedResponse


class BookResponse(BaseModel):
    id: str
    ol_work_id: str
    title: str
    authors: list[str]
    first_publish_year: int | None
    subjects: list[str] | None
    cover_image_url: str | None
    current_version: int
    created_at: str
    updated_at: str


class BookList(PaginatedResponse[BookResponse]):
    pass


class BookVersionResponse(BaseModel):
    id: str
    version_number: int
    title: str
    authors: list[str]
    first_publish_year: int | None
    subjects: list[str] | None
    cover_image_url: str | None
    diff: dict | None
    has_regression: bool
    regression_fields: list[str] | None
    created_at: str


class BookVersionList(PaginatedResponse[BookVersionResponse]):
    pass
