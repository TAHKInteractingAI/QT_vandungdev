"""Tiện ích mạng và giải mã URL cho LinkedIn CEO Finder."""

import re
import time
import urllib.parse
from typing import Optional
from curl_cffi import requests
from selectolax.parser import HTMLParser

from .config import DEFAULT_PROXY, IN_COLAB


def http_get(
    url: str,
    proxy: Optional[str] = DEFAULT_PROXY,
    timeout: int = 12,
    retries: int = 2,
    delay_between_retries: float = 0.4,
) -> Optional[HTMLParser]:
    """Gửi HTTP GET request với curl_cffi Chrome impersonation (tự động thử lại nếu gặp lỗi mạng).

    Parameters:
        url (str): Địa chỉ web cần truy cập.
        proxy (str, optional): Địa chỉ HTTP proxy nếu có.
        timeout (int): Thời gian chờ kết nối tối đa tính bằng giây.
        retries (int): Số lần thử lại tối đa.
        delay_between_retries (float): Thời gian nghỉ giữa các lần thử lại.

    Returns:
        Optional[HTMLParser]: Cây DOM selectolax nếu thành công, None nếu thất bại.
    """
    actual_proxy = None if IN_COLAB else proxy
    for _ in range(retries):
        try:
            r = requests.get(
                url,
                proxy=actual_proxy,
                impersonate="chrome120",
                timeout=timeout,
            )
            if r.status_code == 200:
                return HTMLParser(r.text)
            time.sleep(delay_between_retries)
        except Exception:
            time.sleep(delay_between_retries)
    return None


def unquote_yahoo_url(raw_href: str) -> str:
    """Giải mã link thực từ URL redirect trung gian của Yahoo (tham số RU=).

    Parameters:
        raw_href (str): Link redirect gốc chứa tham số RU=...

    Returns:
        str: Link đích thực tế đã được làm sạch query parameter thừa.
    """
    m = re.search(r"RU=([^/&?]+)", raw_href, re.I)
    target = urllib.parse.unquote(m.group(1)) if m else raw_href
    return target.split("?")[0].rstrip("/")
