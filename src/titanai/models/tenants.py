from pydantic import BaseModel

from titanai.models.pagination import PaginatedResponse


class TenantCreate(BaseModel):
    name: str
    slug: str


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    rate_limit_per_minute: int
    ingestion_refresh_hours: int
    created_at: str
    updated_at: str


class TenantList(PaginatedResponse[TenantResponse]):
    pass
