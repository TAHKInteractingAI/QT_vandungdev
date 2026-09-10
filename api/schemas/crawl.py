from datetime import datetime
from pydantic import BaseModel, Field


class CrawlTriggerRequest(BaseModel):
    keyword: str | None = Field(default=None, description="Search keyword, e.g. 'Công nghệ bán dẫn' or 'AI'")
    max_articles: int | None = Field(default=None, ge=1, le=100, description="Max articles to crawl (default: 20)")
    workers: int | None = Field(default=None, ge=1, le=20, description="Number of concurrent workers (default: 5)")
    lang: str | None = Field(default=None, description="News language, e.g. 'vi', 'en'")
    country: str | None = Field(default=None, description="News country, e.g. 'VN', 'US'")
    timeout: int | None = Field(default=None, ge=1, le=60, description="HTTP timeout in seconds (default: 10)")
    proxy: str | None = Field(default=None, description="HTTP/HTTPS/SOCKS5 proxy URL (e.g. http://127.0.0.1:7890)")
    rotate_ua: bool | None = Field(default=None, description="Rotate User-Agent per request from modern browser pool")
    resume: bool | None = Field(default=None, description="Enable/disable checkpoint resume from articles.jsonl (default: True)")
    show_progress: bool | None = Field(default=False, description="Display progress bar in server stdout (default: False)")
    time_window: str | None = Field(default=None, description="News time window filter, e.g. '1d' (24h), '2d' (48h), '7d', '1h'")
    storage_mode: str | None = Field(default=None, description="Storage mode: 'google' (Google Sheets + Drive) or 'local' (Excel + folder)")


class CrawlJobResponse(BaseModel):
    job_id: str
    status: str
    message: str
    keyword: str
    max_articles: int
    workers: int
    lang: str
    country: str
    time_window: str | None = None
    timeout: int
    proxy: str | None = None
    rotate_ua: bool
    resume: bool
    storage_mode: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    stats: dict | None = None
    excel_url: str | None = None
    spreadsheet_url: str | None = None
    drive_folder_url: str | None = None
