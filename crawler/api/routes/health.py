from datetime import datetime, timezone
from fastapi import APIRouter
from crawler.api.schemas.health import HealthResponse
from crawler.api.services.job_manager import job_manager

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def healthcheck():
    return HealthResponse(
        status="ok",
        service="google-news-crawler-api",
        timestamp=datetime.now(timezone.utc),
        active_job=job_manager.current_job_id,
    )
