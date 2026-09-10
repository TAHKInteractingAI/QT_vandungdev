from __future__ import annotations

import re
from datetime import datetime


def sanitize_topic(keyword: str) -> str:
    """Sanitize keyword for folder name and filenames (remove forbidden chars)."""
    cleaned = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in (keyword or "").strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "News"


def sanitize_tab_title(title: str) -> str:
    """Sanitize worksheet tab title (remove forbidden chars : / ? * [ ] \\). Max 90 chars."""
    cleaned = re.sub(r"[\:\/\?\*\[\]\\]", "_", title).strip()
    return cleaned[:90] if cleaned else "Crawler_Run"


def generate_run_tag(keyword: str, run_time: datetime | None = None) -> tuple[str, str]:
    """
    Generate standardized (safe_topic, run_tag) with format <chủ đề>_hhmm_ddmmyy.
    - Year uses 2 digits (%y).
    """
    now = run_time or datetime.now()
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
