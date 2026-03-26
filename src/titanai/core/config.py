from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "TITANAI_"}

    pii_secret_key: str
    db_path: str = "titanai.db"

    worker_count: int = 3
    poll_interval_seconds: int = 2
    ol_rate_limit_per_second: int = 2
    ol_request_timeout_seconds: int = 10
    max_retries_per_request: int = 3
    max_concurrent_jobs_per_tenant: int = 2
    refresh_check_interval_minutes: int = 15
    shutdown_grace_seconds: int = 30


def get_settings() -> Settings:
    settings = Settings()  # type: ignore[call-arg]
    if len(settings.pii_secret_key) < 32:
        raise ValueError("TITANAI_PII_SECRET_KEY must be at least 32 bytes (64 hex chars or 32+ raw chars)")
    return settings
