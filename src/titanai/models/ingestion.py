from pydantic import BaseModel

from titanai.models.pagination import PaginatedResponse


class IngestionJobCreate(BaseModel):
    query_type: str
    query_value: str


class IngestionJobResponse(BaseModel):
    id: str
    tenant_id: str
    query_type: str
    query_value: str
    status: str
    total_works: int
    processed_works: int
    succeeded: int
    failed: int
    is_auto_refresh: bool
    created_at: str
    started_at: str | None
    completed_at: str | None


class IngestionJobList(PaginatedResponse[IngestionJobResponse]):
    pass


class ActivityLogResponse(BaseModel):
    id: str
    tenant_id: str
    job_id: str
    query_type: str
    query_value: str
    total_fetched: int
    succeeded: int
    failed: int
    errors: list[dict] | None
    created_at: str


class ActivityLogList(PaginatedResponse[ActivityLogResponse]):
    pass
