"""Tiện ích mạng và giải mã URL cho LinkedIn CEO Finder."""

import logging
import re
import time
import urllib.parse
from typing import Optional
from curl_cffi import requests as curl_requests
from selectolax.parser import HTMLParser

from .config import IN_COLAB, get_default_proxy

logger = logging.getLogger(__name__)


def _mask_proxy(proxy_url: Optional[str]) -> str:
    """Che mật khẩu trong URL proxy để ghi log an toàn."""
    if not proxy_url:
        return "None"
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", proxy_url)


def http_get(
    url: str,
    proxy: Optional[str] = None,
    timeout: int = 15,
    retries: int = 2,
    delay_between_retries: float = 0.5,
) -> Optional[HTMLParser]:
    """Gửi HTTP GET request với curl_cffi Chrome impersonation (tự động thử lại nếu gặp lỗi mạng).

    Tự động fallback về proxy mặc định của hệ thống nếu tham số proxy là None.

    Parameters:
        url (str): Địa chỉ web cần truy cập.
        proxy (str, optional): Địa chỉ HTTP proxy nếu có.
        timeout (int): Thời gian chờ kết nối tối đa tính bằng giây (mặc định 15s cho proxy).
        retries (int): Số lần thử lại tối đa.
        delay_between_retries (float): Thời gian nghỉ giữa các lần thử lại.

    Returns:
        Optional[HTMLParser]: Cây DOM selectolax nếu thành công, None nếu thất bại.
    """
    # Tự động lấy proxy từ biến môi trường/crawler nếu tham số truyền vào là None
    effective_proxy = None if IN_COLAB else (proxy or get_default_proxy())
    masked_p = _mask_proxy(effective_proxy)

    for attempt in range(1, retries + 1):
        try:
            # 1. Thử gửi với curl_cffi Chrome impersonation
            r = curl_requests.get(
                url,
                proxy=effective_proxy,
                impersonate="chrome120",
                timeout=timeout,
            )
            if r.status_code == 200 and r.text:
                return HTMLParser(r.text)

            logger.warning(
                "⚠️ [http_get] HTTP %s cho URL '%s' (lần thử %d/%d) [proxy: %s]",
                r.status_code,
                url[:90],
                attempt,
                retries,
                masked_p,
            )
            time.sleep(delay_between_retries)
        except Exception as err:
            logger.warning(
                "⚠️ [http_get] Lỗi kết nối (lần thử %d/%d) cho URL '%s': %s [proxy: %s]",
                attempt,
                retries,
                url[:90],
                err,
                masked_p,
            )
            # Thử fallback với requests thông thường nếu curl_cffi gặp lỗi proxy handshake trên Linux
            try:
                import requests as py_requests

                proxies_dict = (
                    {"http": effective_proxy, "https": effective_proxy}
                    if effective_proxy
                    else None
                )
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                }
                fallback_res = py_requests.get(
                    url,
                    headers=headers,
                    proxies=proxies_dict,
                    timeout=timeout,
                )
                if fallback_res.status_code == 200 and fallback_res.text:
                    logger.info("✅ [http_get] Fallback sang standard requests thành công!")
                    return HTMLParser(fallback_res.text)
            except Exception:
                pass

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
