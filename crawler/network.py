from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from crawler.config import HEADERS, POOL_MAXSIZE, TIMEOUT, get_random_user_agent

_DEAD_CODES = {401, 403, 404, 410, 429, 500, 502, 503}


def create_session(
    proxy: str | None = None,
    pool_size: int = POOL_MAXSIZE,
    max_retries: int = 3,
    backoff: float = 0.5,
) -> requests.Session:
    """Create a configured requests.Session with connection pooling, proxy, and retry backoff."""
    session = requests.Session()
    session.headers.update(HEADERS)
    if proxy:
        session.proxies = {
            "http": proxy,
            "https": proxy,
        }
    adapter = HTTPAdapter(
        pool_connections=pool_size,
        pool_maxsize=pool_size,
        max_retries=Retry(
            total=max_retries,
            backoff_factor=backoff,
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False,
        ),
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def fetch_with_status(
    url: str,
    session: requests.Session | None = None,
    timeout: int = TIMEOUT,
    rotate_ua: bool = False,
) -> tuple[str | None, int | None, str]:
    """GET url, return (html_text, status_code, alive_status)."""
    headers = dict(HEADERS)
    if rotate_ua:
        headers["User-Agent"] = get_random_user_agent()

    try:
        if session is not None:
            req_headers = {"User-Agent": headers["User-Agent"]} if rotate_ua else None
            resp = session.get(url, headers=req_headers, timeout=timeout)
        else:
            resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.exceptions.Timeout:
        return None, None, "timeout"
    except requests.exceptions.ConnectionError:
        return None, None, "connection_error"
    except Exception as e:
        return None, None, f"error:{type(e).__name__}"

    code = resp.status_code
    if code == 200 and resp.text:
        return resp.text, code, f"alive {code}"
    if code in _DEAD_CODES:
        return None, code, f"dead {code}"
    return None, code, f"http_{code}"
