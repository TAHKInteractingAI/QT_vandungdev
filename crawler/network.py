from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from crawler.config import HEADERS, POOL_MAXSIZE, TIMEOUT, get_random_user_agent

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None  # type: ignore

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
    """
    GET url, return (html_text, status_code, alive_status).
    When standalone or encountering anti-bot challenge (403/429), uses curl_cffi
    with Chrome TLS/JA3 impersonation to bypass Cloudflare and WAF protections.
    """
    headers = dict(HEADERS)
    if rotate_ua:
        headers["User-Agent"] = get_random_user_agent()

    # 1. Primary fetch attempt (using session if available)
    resp_text: str | None = None
    code: int | None = None

    try:
        if session is not None:
            req_headers = {"User-Agent": headers["User-Agent"]} if rotate_ua else None
            resp = session.get(url, headers=req_headers, timeout=timeout)
            code = resp.status_code
            if code == 200 and resp.text:
                return resp.text, code, f"alive {code}"
        else:
            # If no shared session, use curl_cffi directly for maximum stealth
            if curl_requests is not None:
                try:
                    c_resp = curl_requests.get(url, headers=headers, timeout=timeout, impersonate="chrome")
                    c_code = c_resp.status_code
                    if c_code == 200 and c_resp.text:
                        return c_resp.text, c_code, f"alive {c_code}"
                    code = c_code
                except Exception:
                    pass

            resp = requests.get(url, headers=headers, timeout=timeout)
            code = resp.status_code
            if code == 200 and resp.text:
                return resp.text, code, f"alive {code}"
    except requests.exceptions.Timeout:
        pass
    except requests.exceptions.ConnectionError:
        pass
    except Exception:
        pass

    # 2. Anti-bot bypass fallback with curl_cffi if blocked (403, 429, or empty/failed)
    if curl_requests is not None and (code is None or code in (403, 429, 503)):
        try:
            c_resp = curl_requests.get(url, headers=headers, timeout=timeout, impersonate="chrome")
            if c_resp.status_code == 200 and c_resp.text:
                return c_resp.text, c_resp.status_code, f"alive {c_resp.status_code} (curl_cffi)"
            code = c_resp.status_code
        except Exception:
            pass

    if code == 200:
        return resp_text, code, f"alive {code}"
    if code in _DEAD_CODES:
        return None, code, f"dead {code}"
    if code is not None:
        return None, code, f"http_{code}"
    return None, None, "error:RequestFailed"
