from pydantic import BaseModel

from titanai.models.pagination import PaginatedResponse


class ReadingListBookItem(BaseModel):
    id: str
    id_type: str


class ReadingListCreate(BaseModel):
    patron_name: str
    patron_email: str
    books: list[ReadingListBookItem]


class ReadingListItemResponse(BaseModel):
    submitted_id: str
    submitted_id_type: str
    status: str
    book_id: str | None


class ReadingListResponse(BaseModel):
    id: str
    created_at: str
    books: list[ReadingListItemResponse]


class ReadingListSummary(BaseModel):
    id: str
    patron_name_hash: str
    patron_email_hash: str
    created_at: str


class ReadingListSummaryList(PaginatedResponse[ReadingListSummary]):
    pass
