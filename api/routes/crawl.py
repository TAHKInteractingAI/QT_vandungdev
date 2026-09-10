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
    lang: str | list[str] | None,
    timeout: int | None,
    proxy: str | None,
    rotate_ua: bool | None,
    resume: bool | None,
    show_progress: bool | None,
    time_window: str | None = None,
    storage_mode: str | None = None,
    timezone: str | None = None,
    ping_url: str | None = None,
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
    final_time_window = time_window or settings.DEFAULT_TIME_WINDOW
    final_timeout = timeout if timeout is not None else settings.DEFAULT_TIMEOUT
    final_proxy = proxy if proxy is not None else settings.DEFAULT_PROXY
    final_rotate_ua = rotate_ua if rotate_ua is not None else settings.DEFAULT_ROTATE_UA
    final_resume = resume if resume is not None else settings.DEFAULT_RESUME
    final_show_progress = show_progress if show_progress is not None else settings.DEFAULT_SHOW_PROGRESS
    final_storage_mode = storage_mode or settings.DEFAULT_STORAGE_MODE
    final_timezone = timezone or settings.DEFAULT_TIMEZONE
    final_ping_url = ping_url

    try:
        job_data = job_manager.create_and_start_job(
            keyword=final_keyword,
            max_articles=final_max,
            workers=final_workers,
            lang=final_lang,
            timeout=final_timeout,
            proxy=final_proxy,
            rotate_ua=final_rotate_ua,
            resume=final_resume,
            show_progress=final_show_progress,
            time_window=final_time_window,
            storage_mode=final_storage_mode,
            tz=final_timezone,
            ping_url=final_ping_url,
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
    - lang/languages: Market code(s) e.g. 'vi', 'us', 'vi,us,jp' or preset 'top', 'global', 'asia', 'tech'
    - timeout: HTTP request timeout in seconds (default: 10)
    - proxy: HTTP/HTTPS/SOCKS5 proxy address
    - rotate_ua: Rotate User-Agent per request from modern browser pool
    - resume: Resume from checkpoint articles.jsonl (default: True)
    - show_progress: Show progress bar in server terminal output (default: False)
    - time_window: News time window filter, e.g. '1d' (24h), '2d' (48h), '7d', '1h'
    - storage_mode: Storage mode 'google' (Cloud) or 'local' (Excel)
    """
    keyword = req.keyword if req else None
    max_articles = req.max_articles if req else None
    workers = req.workers if req else None
    lang = (req.languages or req.lang) if req else None
    timeout = req.timeout if req else None
    proxy = req.proxy if req else None
    rotate_ua = req.rotate_ua if req else None
    resume = req.resume if req else None
    show_progress = req.show_progress if req else None
    time_window = req.time_window if req else None
    storage_mode = req.storage_mode if req else None
    timezone = (req.timezone or req.tz) if req else None
    ping_url = req.ping_url if req else None

    job_data = _trigger_job(
        keyword,
        max_articles,
        workers,
        lang,
        timeout,
        proxy,
        rotate_ua,
        resume,
        show_progress,
        time_window,
        storage_mode,
        timezone,
        ping_url,
    )
    return CrawlJobResponse(
        job_id=job_data["job_id"],
        status=job_data["status"],
        message=job_data["message"],
        keyword=job_data["keyword"],
        max_articles=job_data["max_articles"],
        workers=job_data["workers"],
        lang=job_data["lang"],
        markets=job_data.get("markets"),
        time_window=job_data.get("time_window"),
        timeout=job_data["timeout"],
        proxy=job_data["proxy"],
        rotate_ua=job_data["rotate_ua"],
        resume=job_data["resume"],
        storage_mode=job_data.get("storage_mode"),
        timezone=job_data.get("timezone"),
        ping_url=job_data.get("ping_url"),
        created_at=job_data["created_at"],
        excel_url=f"/api/v1/jobs/{job_data['job_id']}/download/excel",
        spreadsheet_url=job_data.get("spreadsheet_url"),
        drive_folder_url=job_data.get("drive_folder_url"),
    )


@router.get("/trigger", status_code=status.HTTP_202_ACCEPTED, response_model=CrawlJobResponse)
async def trigger_crawl_get(
    keyword: str | None = Query(None),
    max_articles: int | None = Query(None, alias="max"),
    workers: int | None = Query(None),
    lang: str | None = Query(None, alias="languages"),
    time_window: str | None = Query(None, alias="when"),
    timeout: int | None = Query(None),
    proxy: str | None = Query(None),
    rotate_ua: bool | None = Query(None),
    resume: bool | None = Query(None),
    show_progress: bool | None = Query(None),
    storage_mode: str | None = Query(None),
    timezone: str | None = Query(None, alias="tz"),
    ping_url: str | None = Query(None),
    _authorized: bool = Depends(verify_api_key),
):
    """
    Trigger a new news crawl job via HTTP GET (convenient for webhooks or URL pings).
    Supports ?lang=vi,us or ?languages=top&when=1d&tz=Asia/Ho_Chi_Minh&ping_url=...
    """
    job_data = _trigger_job(
        keyword,
        max_articles,
        workers,
        lang,
        timeout,
        proxy,
        rotate_ua,
        resume,
        show_progress,
        time_window,
        storage_mode,
        timezone,
        ping_url,
    )
    return CrawlJobResponse(
        job_id=job_data["job_id"],
        status=job_data["status"],
        message=job_data["message"],
        keyword=job_data["keyword"],
        max_articles=job_data["max_articles"],
        workers=job_data["workers"],
        lang=job_data["lang"],
        markets=job_data.get("markets"),
        time_window=job_data.get("time_window"),
        timeout=job_data["timeout"],
        proxy=job_data["proxy"],
        rotate_ua=job_data["rotate_ua"],
        resume=job_data["resume"],
        storage_mode=job_data.get("storage_mode"),
        timezone=job_data.get("timezone"),
        ping_url=job_data.get("ping_url"),
        created_at=job_data["created_at"],
        excel_url=f"/api/v1/jobs/{job_data['job_id']}/download/excel",
        spreadsheet_url=job_data.get("spreadsheet_url"),
        drive_folder_url=job_data.get("drive_folder_url"),
    )


@router.get("/debug/decode")
async def debug_decode_endpoint(
    url: str = Query(...),
    _authorized: bool = Depends(verify_api_key),
):
    """Diagnostic endpoint to trace Google News decoding step-by-step from server IP."""
    import base64
    import json
    import re
    from urllib.parse import quote, urlparse
    from selectolax.parser import HTMLParser

    logs = []
    try:
        from curl_cffi import requests as c_req
        logs.append("curl_cffi is available")
    except Exception as e:
        c_req = None
        logs.append(f"curl_cffi unavailable: {e}")

    path = urlparse(url).path.split("/")
    base64_str = path[-1] if path else ""
    logs.append(f"base64_str: {base64_str[:30]}...")

    # Direct b64 test
    try:
        padded = base64_str + "=" * ((4 - len(base64_str) % 4) % 4)
        raw = base64.urlsafe_b64decode(padded)
        m = re.search(rb"https?://[^\x00-\x1f\x7f-\xff\s\"\'<>]+", raw)
        if m:
            logs.append(f"direct_b64: {m.group(0).decode('utf-8', errors='ignore')}")
    except Exception as e:
        logs.append(f"direct_b64 error: {e}")

    # RSS articles GET
    rss_url = f"https://news.google.com/rss/articles/{base64_str}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": "SOCS=CAESEwgDEgk2NDgyOTM5MDQaAmVuIAEaBgiA_L20Bg",
    }
    html_text = ""
    c_session = None
    if c_req:
        try:
            c_session = c_req.Session(impersonate="chrome")
            r = c_session.get(rss_url, headers=headers, timeout=10, allow_redirects=True)
            logs.append(f"curl_cffi GET status: {r.status_code}, url: {r.url}, len: {len(r.text)}")
            html_text = r.text
        except Exception as e:
            logs.append(f"curl_cffi GET exception: {type(e).__name__}: {e}")

    if not html_text:
        try:
            import requests as req
            r2 = req.get(rss_url, headers=headers, timeout=10, allow_redirects=True)
            logs.append(f"requests GET status: {r2.status_code}, url: {r2.url}, len: {len(r2.text)}")
            html_text = r2.text
        except Exception as e:
            logs.append(f"requests GET exception: {type(e).__name__}: {e}")

    tree = HTMLParser(html_text)
    data_el = tree.css_first("c-wiz > div[jscontroller]")
    logs.append(f"data_el found: {data_el is not None}")
    if data_el:
        sig = data_el.attributes.get("data-n-a-sg")
        ts = data_el.attributes.get("data-n-a-ts")
        logs.append(f"sig: {sig}, ts: {ts}")
        be_url = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
        payload = [
            "Fbv4je",
            f'["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{base64_str}",{ts},"{sig}"]',
        ]
        be_headers = {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": headers["User-Agent"],
            "Cookie": "SOCS=CAESEwgDEgk2NDgyOTM5MDQaAmVuIAEaBgiA_L20Bg",
            "Origin": "https://news.google.com",
            "Referer": "https://news.google.com/",
        }
        be_data = f"f.req={quote(json.dumps([[payload]]))}"
        try:
            if c_session is not None:
                be_r = c_session.post(be_url, headers=be_headers, data=be_data, timeout=10)
            elif c_req:
                be_r = c_req.post(be_url, headers=be_headers, data=be_data, impersonate="chrome", timeout=10)
            else:
                import requests as req
                be_r = req.post(be_url, headers=be_headers, data=be_data, timeout=10)
            logs.append(f"batchexecute status: {be_r.status_code}, len: {len(be_r.text)}")
            parsed = json.loads(be_r.text.split("\n\n")[1])[:-2]
            decoded = json.loads(parsed[0][2])[1]
            logs.append(f"SUCCESS decoded_url: {decoded}")
        except Exception as e:
            logs.append(f"batchexecute exception: {type(e).__name__}: {e}")
    else:
        title = tree.css_first("title")
        logs.append(f"HTML title: {title.text() if title else 'none'}")
        logs.append(f"HTML snippet: {html_text[:400]}")

    return {"logs": logs}

