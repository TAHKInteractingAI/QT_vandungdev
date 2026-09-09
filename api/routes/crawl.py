from fastapi import APIRouter, Depends, HTTPException, Query, status
from api.config import settings
from api.schemas.crawl import CrawlJobResponse, CrawlTriggerRequest
from api.security import verify_api_key
from api.services.job_manager import job_manager

router = APIRouter(prefix="/api/v1/crawl", tags=["Crawl"])


def _trigger_job(
    keyword: str | None,
    max_articles: int | None,
    workers: int | None,
    lang: str | None,
    country: str | None,
    timeout: int | None,
    proxy: str | None,
    rotate_ua: bool | None,
    resume: bool | None,
    show_progress: bool | None,
) -> dict:
    if job_manager.is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Another job is currently running: {job_manager.current_job_id}. Concurrency lock is active.",
        )

    final_keyword = keyword or settings.DEFAULT_KEYWORD
    final_max = max_articles if max_articles is not None else settings.DEFAULT_MAX_ARTICLES
    final_workers = workers if workers is not None else settings.DEFAULT_WORKERS
    final_lang = lang or settings.DEFAULT_LANG
    final_country = country or settings.DEFAULT_COUNTRY
    final_timeout = timeout if timeout is not None else settings.DEFAULT_TIMEOUT
    final_proxy = proxy if proxy is not None else settings.DEFAULT_PROXY
    final_rotate_ua = rotate_ua if rotate_ua is not None else settings.DEFAULT_ROTATE_UA
    final_resume = resume if resume is not None else settings.DEFAULT_RESUME
    final_show_progress = show_progress if show_progress is not None else settings.DEFAULT_SHOW_PROGRESS

    try:
        job_data = job_manager.create_and_start_job(
            keyword=final_keyword,
            max_articles=final_max,
            workers=final_workers,
            lang=final_lang,
            country=final_country,
            timeout=final_timeout,
            proxy=final_proxy,
            rotate_ua=final_rotate_ua,
            resume=final_resume,
            show_progress=final_show_progress,
        )
        return job_data
    except RuntimeError as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(err),
        )


@router.post("/trigger", status_code=status.HTTP_202_ACCEPTED, response_model=CrawlJobResponse)
async def trigger_crawl_post(
    req: CrawlTriggerRequest | None = None,
    _authorized: bool = Depends(verify_api_key),
):
    """
    Trigger a new news crawl job via HTTP POST.
    Responds immediately within < 50ms with HTTP 202 Accepted.
    Accepts all configuration parameters matching crawler/cli.py:
    - keyword: Search query keyword
    - max_articles: Maximum number of articles (default: 20)
    - workers: Concurrent worker threads for image/article download (default: 5)
    - lang: News language code (default: 'vi')
    - country: News country code (default: 'VN')
    - timeout: HTTP request timeout in seconds (default: 10)
    - proxy: HTTP/HTTPS/SOCKS5 proxy address
    - rotate_ua: Rotate User-Agent per request from modern browser pool
    - resume: Resume from checkpoint articles.jsonl (default: True)
    - show_progress: Show progress bar in server terminal output (default: False)
    """
    keyword = req.keyword if req else None
    max_articles = req.max_articles if req else None
    workers = req.workers if req else None
    lang = req.lang if req else None
    country = req.country if req else None
    timeout = req.timeout if req else None
    proxy = req.proxy if req else None
    rotate_ua = req.rotate_ua if req else None
    resume = req.resume if req else None
    show_progress = req.show_progress if req else None

    job_data = _trigger_job(
        keyword,
        max_articles,
        workers,
        lang,
        country,
        timeout,
        proxy,
        rotate_ua,
        resume,
        show_progress,
    )
    return CrawlJobResponse(
        job_id=job_data["job_id"],
        status=job_data["status"],
        message=job_data["message"],
        keyword=job_data["keyword"],
        max_articles=job_data["max_articles"],
        workers=job_data["workers"],
        lang=job_data["lang"],
        country=job_data["country"],
        timeout=job_data["timeout"],
        proxy=job_data["proxy"],
        rotate_ua=job_data["rotate_ua"],
        resume=job_data["resume"],
        created_at=job_data["created_at"],
        excel_url=f"/api/v1/jobs/{job_data['job_id']}/download/excel",
    )


@router.get("/trigger", status_code=status.HTTP_202_ACCEPTED, response_model=CrawlJobResponse)
async def trigger_crawl_get(
    keyword: str | None = Query(None),
    max_articles: int | None = Query(None, alias="max"),
    workers: int | None = Query(None),
    lang: str | None = Query(None),
    country: str | None = Query(None),
    timeout: int | None = Query(None),
    proxy: str | None = Query(None),
    rotate_ua: bool | None = Query(None),
    resume: bool | None = Query(None),
    show_progress: bool | None = Query(None),
    _authorized: bool = Depends(verify_api_key),
):
    """
    Trigger a new news crawl job via HTTP GET (convenient for webhooks or URL pings).
    """
    job_data = _trigger_job(
        keyword,
        max_articles,
        workers,
        lang,
        country,
        timeout,
        proxy,
        rotate_ua,
        resume,
        show_progress,
    )
    return CrawlJobResponse(
        job_id=job_data["job_id"],
        status=job_data["status"],
        message=job_data["message"],
        keyword=job_data["keyword"],
        max_articles=job_data["max_articles"],
        workers=job_data["workers"],
        lang=job_data["lang"],
        country=job_data["country"],
        timeout=job_data["timeout"],
        proxy=job_data["proxy"],
        rotate_ua=job_data["rotate_ua"],
        resume=job_data["resume"],
        created_at=job_data["created_at"],
        excel_url=f"/api/v1/jobs/{job_data['job_id']}/download/excel",
    )
