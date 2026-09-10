import re
import zoneinfo
from datetime import datetime
from email.utils import parsedate_to_datetime

DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"


def get_timezone(tz_name: str | None = None) -> zoneinfo.ZoneInfo:
    """Resolve timezone by name, defaulting to Asia/Ho_Chi_Minh."""
    target = (tz_name or DEFAULT_TIMEZONE).strip()
    try:
        return zoneinfo.ZoneInfo(target)
    except Exception:
        return zoneinfo.ZoneInfo(DEFAULT_TIMEZONE)


def format_published_date(raw_date: str, tz_name: str | None = None) -> str:
    """
    Format raw RSS pubDate (e.g. 'Thu, 10 Sep 2026 02:09:33 GMT') to readable local timezone format.
    Output example: '10/09/2026 09:09 (UTC+7)'
    """
    if not raw_date or not str(raw_date).strip():
        return ""
    cleaned = str(raw_date).strip()
    try:
        dt = parsedate_to_datetime(cleaned)
        target_tz = get_timezone(tz_name)
        dt_target = dt.astimezone(target_tz)
        offset = dt_target.utcoffset()
        if offset is not None:
            total_seconds = int(offset.total_seconds())
            sign = "+" if total_seconds >= 0 else "-"
            hours = abs(total_seconds) // 3600
            tz_label = f"UTC{sign}{hours}"
        else:
            tz_label = "UTC+7"
        return dt_target.strftime(f"%H:%M - %d/%m/%Y ({tz_label})")
    except Exception:
        return cleaned


def sanitize_topic(keyword: str) -> str:
    """Sanitize keyword for folder name and filenames (remove forbidden chars)."""
    cleaned = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in (keyword or "").strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "News"


def sanitize_tab_title(title: str) -> str:
    """Sanitize worksheet tab title (remove forbidden chars : / ? * [ ] \\). Max 90 chars."""
    cleaned = re.sub(r"[\:\/\?\*\[\]\\]", "_", title).strip()
    return cleaned[:90] if cleaned else "Crawler_Run"


def generate_run_tag(
    keyword: str,
    run_time: datetime | None = None,
    tz: str | None = None,
) -> tuple[str, str]:
    """
    Generate standardized (safe_topic, run_tag) with format <chủ đề>_hhmm_ddmmyy.
    - Uses specified timezone (default: Asia/Ho_Chi_Minh).
    - Year uses 2 digits (%y).
    """
    target_tz = get_timezone(tz)
    if run_time is None:
        now = datetime.now(target_tz)
    elif run_time.tzinfo is None:
        now = run_time.replace(tzinfo=target_tz)
    else:
        now = run_time.astimezone(target_tz)

    safe_topic = sanitize_topic(keyword)
    time_suffix = now.strftime("%H%M_%d%m%y")
    run_tag = f"{safe_topic}_{time_suffix}"
    return safe_topic, run_tag


def format_article_image_name(safe_topic: str, article_idx: int, image_idx: int = 1, ext: str = ".jpg") -> str:
    """
    Format image filename: <chủ đề>_0000_00.ext (e.g. Trillion_0001_01.jpg)
    - 4 digits article index: 0001
    - 2 digits image index: 01
    """
    extension = ext if ext.startswith(".") else f".{ext}"
    return f"{safe_topic}_{article_idx:04d}_{image_idx:02d}{extension}"


def format_article_id(safe_topic: str, article_idx: int) -> str:
    """
    Format article identifier: <chủ đề>_0000 (e.g. Trillion_0001)
    """
    return f"{safe_topic}_{article_idx:04d}"
