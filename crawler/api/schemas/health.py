from datetime import datetime
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "google-news-crawler-api"
    timestamp: datetime
    active_job: str | None = None
