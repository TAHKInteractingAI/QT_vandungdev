from __future__ import annotations

import base64
import json
import re
import time
from urllib.parse import quote, urlparse

import requests
from selectolax.parser import HTMLParser

from crawler.config import HEADERS, TIMEOUT

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None  # type: ignore

try:
    from googlenewsdecoder import gnewsdecoder
except ImportError:
    gnewsdecoder = None  # type: ignore


def _extract_url_from_html(html_text: str) -> str | None:
    """Extract destination URL from Google redirect HTML page."""
    tree = HTMLParser(html_text)
    # 1. Meta refresh
    for meta in tree.css("meta"):
        http_equiv = meta.attributes.get("http-equiv") or ""
        if http_equiv.lower() == "refresh":
            content = meta.attributes.get("content", "")
            if "url=" in content.lower():
                target = content.lower().split("url=")[-1].split(";")[0].strip("\"' ")
                if target.startswith("http") and "google.com" not in target:
                    return target
    # 2. Noscript anchors
    for a in tree.css("noscript a"):
        href = (a.attributes.get("href") or "").strip()
        if href.startswith("http") and "google.com" not in href:
            return href
    # 3. Data attributes / data-n-au
    for el in tree.css("[data-n-au]"):
        u = (el.attributes.get("data-n-au") or "").strip()
        if u.startswith("http") and "google.com" not in u:
            return u
    # 4. Fallback: check any external link inside main containers
    for a in tree.css("a"):
        href = (a.attributes.get("href") or "").strip()
        if href.startswith("http") and not any(h in href for h in ("google.com", "gstatic.com", "googleusercontent.com")):
            return href
    return None


def _extract_cbm_direct(google_url: str) -> str | None:
    """Strategy 0: Try direct base64 extraction for older Google News CBM URL formats."""
    try:
        path = urlparse(google_url).path.split("/")
        if len(path) > 1 and path[-2] in ["articles", "read"]:
            b64 = path[-1]
            padded = b64 + "=" * ((4 - len(b64) % 4) % 4)
            raw = base64.urlsafe_b64decode(padded)
            m = re.search(rb"https?://[^\x00-\x1f\x7f-\xff\s\"\'<>]+", raw)
            if m:
                u = m.group(0).decode("utf-8", errors="ignore")
                if "google.com" not in u and "google." not in u:
                    return u
    except Exception:
        pass
    return None


def _decode_cbm_batchexecute(
    base64_str: str,
    proxy: str | None = None,
    timeout: int = TIMEOUT,
) -> str | None:
    """Strategy 1: Fetch signature from rss/articles endpoint with SOCS cookie to bypass Google CAPTCHA,
    then resolve target URL via Google batchexecute RPC.
    """
    rss_url = f"https://news.google.com/rss/articles/{base64_str}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": "SOCS=CAESEwgDEgk2NDgyOTM5MDQaAmVuIAEaBgiA_L20Bg",
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None

    html_text: str | None = None
    c_session = None
    if curl_requests is not None:
        try:
            c_session = curl_requests.Session(impersonate="chrome")
            c_resp = c_session.get(rss_url, headers=headers, timeout=timeout, proxies=proxies, allow_redirects=True)
            if c_resp.status_code == 200:
                html_text = c_resp.text
            else:
                print(f"[decode] curl_cffi status: {c_resp.status_code}")
        except Exception as e:
            print(f"[decode] curl_cffi GET error: {e}")

    if not html_text:
        try:
            resp = requests.get(rss_url, headers=headers, timeout=timeout, proxies=proxies, allow_redirects=True)
            if resp.status_code == 200:
                html_text = resp.text
            else:
                print(f"[decode] requests status: {resp.status_code}")
        except Exception as e:
            print(f"[decode] requests GET error: {e}")

    if not html_text:
        print("[decode] Failed to retrieve HTML from rss/articles")
        return None

    tree = HTMLParser(html_text)
    data_el = tree.css_first("c-wiz > div[jscontroller]")
    if not data_el:
        title_el = tree.css_first("title")
        t_val = title_el.text() if title_el else "no title"
        print(f"[decode] c-wiz element not found in HTML (title={t_val!r}, len={len(html_text)})")
        return None

    sig = data_el.attributes.get("data-n-a-sg")
    ts = data_el.attributes.get("data-n-a-ts")
    if not sig or not ts:
        print(f"[decode] Missing sig/ts: sig={sig!r}, ts={ts!r}")
        return None

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

    be_resp_text: str | None = None
    try:
        if c_session is not None:
            try:
                be_resp = c_session.post(be_url, headers=be_headers, data=be_data, timeout=timeout, proxies=proxies)
                if be_resp.status_code == 200:
                    be_resp_text = be_resp.text
                else:
                    print(f"[decode] batchexecute c_session status: {be_resp.status_code}")
            except Exception as e:
                print(f"[decode] batchexecute c_session error: {e}")
        elif curl_requests is not None:
            try:
                be_resp = curl_requests.post(be_url, headers=be_headers, data=be_data, impersonate="chrome", timeout=timeout, proxies=proxies)
                if be_resp.status_code == 200:
                    be_resp_text = be_resp.text
            except Exception:
                pass

        if not be_resp_text:
            try:
                be_resp = requests.post(be_url, headers=be_headers, data=be_data, timeout=timeout, proxies=proxies)
                if be_resp.status_code == 200:
                    be_resp_text = be_resp.text
            except Exception:
                pass

        if not be_resp_text:
            return None

        try:
            parsed_data = json.loads(be_resp_text.split("\n\n")[1])[:-2]
            decoded_url = json.loads(parsed_data[0][2])[1]
            if decoded_url and "google.com" not in decoded_url and "google." not in decoded_url:
                return decoded_url
        except Exception:
            pass

        return None
    finally:
        if c_session is not None:
            try:
                c_session.close()
            except Exception:
                pass


def _decode_once(
    google_url: str,
    session: requests.Session | None = None,
    proxy: str | None = None,
    timeout: int = TIMEOUT,
) -> tuple[str | None, str]:
    """Single attempt to decode Google News URL using multi-strategy cascading resolution."""
    if not google_url:
        return None, "empty_url"

    # Direct publisher URL already provided
    if "news.google.com" not in google_url and "google.com" not in google_url:
        return google_url, "direct"

    # Strategy 0: Direct base64 regex decode (0ms, offline)
    direct = _extract_cbm_direct(google_url)
    if direct:
        return direct, "direct_b64"

    # Extract base64 token for local fallback strategies
    try:
        path = urlparse(google_url).path.split("/")
        base64_str = path[-1] if path else ""
    except Exception:
        base64_str = ""

    # Strategy 2: Robust batchexecute via rss/articles with SOCS cookie (Direct fallback)
    if base64_str:
        decoded = _decode_cbm_batchexecute(base64_str, proxy=proxy, timeout=timeout)
        if decoded:
            return decoded, "decoded"

    # Strategy 2: googlenewsdecoder library fallback
    if gnewsdecoder is not None:
        try:
            res = gnewsdecoder(google_url, interval=0.1, proxy=proxy)
            if isinstance(res, dict) and res.get("status") and res.get("decoded_url"):
                g_decoded = res["decoded_url"]
                if g_decoded and "google.com" not in g_decoded:
                    return g_decoded, "decoded"
        except Exception:
            pass

    # Strategy 3: HTTP Follow Redirect with curl_cffi (Chrome TLS impersonation)
    try:
        if curl_requests is not None:
            c_kwargs: dict = {"timeout": timeout, "allow_redirects": True, "impersonate": "chrome"}
            if proxy:
                c_kwargs["proxies"] = {"http": proxy, "https": proxy}
            c_resp = curl_requests.get(google_url, **c_kwargs)
            final_url = c_resp.url
            if final_url and "google.com" not in final_url and "google." not in final_url:
                return final_url, "redirect_followed (curl_cffi)"
            if c_resp.text:
                extracted = _extract_url_from_html(c_resp.text)
                if extracted:
                    return extracted, "html_extracted (curl_cffi)"

        client = session or requests
        req_kwargs: dict = {"timeout": timeout, "allow_redirects": True}
        if session is None:
            req_kwargs["headers"] = HEADERS
            if proxy:
                req_kwargs["proxies"] = {"http": proxy, "https": proxy}

        resp = client.get(google_url, **req_kwargs)
        final_url = resp.url
        if final_url and "google.com" not in final_url and "google." not in final_url:
            return final_url, "redirect_followed"

        # Strategy 4: HTML Parser for meta refresh / embedded links
        if resp.text:
            extracted = _extract_url_from_html(resp.text)
            if extracted:
                return extracted, "html_extracted"

    except Exception as e:
        return None, f"fallback_error:{type(e).__name__}"

    return None, "decode_failed"


def decode_publisher_url(
    google_url: str,
    session: requests.Session | None = None,
    proxy: str | None = None,
    timeout: int = TIMEOUT,
    retries: int = 2,
    retry_delay: float = 1.0,
) -> tuple[str | None, str]:
    """
    Multi-strategy decoder with automatic retries and proxy failover rotation:
    CBM google_url -> publisher_url.
    Try the `retries` again (default 2 times, total 3 attempts) if it fails,
    rotating to a fresh Webshare proxy IP on each attempt.
    """
    if not google_url:
        return None, "empty_url"
    if "news.google.com" not in google_url and "google.com" not in google_url:
        return google_url, "direct"

    from crawler.proxy_manager import proxy_manager

    last_status = "decode_failed"
    for attempt in range(retries + 1):
        if attempt > 0:
            time.sleep(retry_delay * attempt)
        effective_proxy = proxy_manager.get_proxy(requested_proxy=proxy, attempt=attempt)
        url, status = _decode_once(google_url, session=session, proxy=effective_proxy, timeout=timeout)
        if url:
            suffix = f" (retry {attempt})" if attempt > 0 else ""
            return url, f"{status}{suffix}"
        last_status = status

    return None, last_status
