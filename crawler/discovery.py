from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from crawler.config import HEADERS, TIMEOUT

try:
    from googlenewsdecoder import gnewsdecoder
except ImportError:
    gnewsdecoder = None  # type: ignore


def fetch_rss(
    keyword: str,
    max_articles: int,
    lang: str = "vi",
    country: str = "VN",
    session: requests.Session | None = None,
    timeout: int = TIMEOUT,
) -> list[dict]:
    """Discover articles via Google News RSS. Returns google_url (CBM)."""
    q = quote_plus(keyword)
    ceid = f"{country}:{lang}"
    url = f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={country}&ceid={ceid}"
    if session is not None:
        resp = session.get(url, timeout=timeout)
    else:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = root.findall(".//item")
    articles: list[dict] = []
    for it in items[:max_articles]:
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        desc_raw = it.findtext("description") or ""
        desc_unesc = html.unescape(desc_raw)
        snippet = BeautifulSoup(desc_unesc, "html.parser").get_text(" ", strip=True)[:500]
        source_el = it.find("source")
        source = (source_el.text.strip() if source_el is not None and source_el.text else "")
        if not source and " - " in title:
            source = title.rsplit(" - ", 1)[-1]
        articles.append(
            {
                "title": title,
                "source": source,
                "google_url": link,
                "url": link,
                "published": pub,
                "snippet": snippet,
                "description_raw": desc_raw,
            }
        )
    return articles


def _extract_url_from_html(html_text: str) -> str | None:
    """Extract destination URL from Google redirect HTML page."""
    soup = BeautifulSoup(html_text, "html.parser")
    # 1. Meta refresh
    for meta in soup.find_all("meta", attrs={"http-equiv": lambda x: x and x.lower() == "refresh"}):
        content = meta.get("content", "")
        if "url=" in content.lower():
            target = content.lower().split("url=")[-1].split(";")[0].strip("\"' ")
            if target.startswith("http") and "google.com" not in target:
                return target
    # 2. Noscript anchors
    for ns in soup.find_all("noscript"):
        for a in ns.find_all("a"):
            href = (a.get("href") or "").strip()
            if href.startswith("http") and "google.com" not in href:
                return href
    # 3. Data attributes / data-n-au
    for el in soup.find_all(attrs={"data-n-au": True}):
        u = el["data-n-au"].strip()
        if u.startswith("http") and "google.com" not in u:
            return u
    # 4. Fallback: check any external link inside main containers
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if href.startswith("http") and not any(h in href for h in ("google.com", "gstatic.com", "googleusercontent.com")):
            return href
    return None


def decode_publisher_url(
    google_url: str,
    session: requests.Session | None = None,
    proxy: str | None = None,
    timeout: int = TIMEOUT,
) -> tuple[str | None, str]:
    """
    Multi-strategy decoder: CBM google_url -> publisher_url.
    1. googlenewsdecoder (Primary)
    2. HTTP Redirect Follow (Fallback 1)
    3. HTML Meta Refresh / Anchor Extraction (Fallback 2)
    """
    if not google_url or "news.google.com" not in google_url:
        return None, "not_google_url"

    # Strategy 1: googlenewsdecoder
    if gnewsdecoder is not None:
        try:
            res = gnewsdecoder(google_url, interval=0.1, proxy=proxy)
            if isinstance(res, dict) and res.get("status") and res.get("decoded_url"):
                decoded = res["decoded_url"]
                if decoded and "google.com" not in decoded:
                    return decoded, "decoded"
        except Exception:
            pass

    # Strategy 2: HTTP Follow Redirect
    client = session or requests
    try:
        req_kwargs: dict = {"timeout": timeout, "allow_redirects": True}
        if session is None:
            req_kwargs["headers"] = HEADERS
            if proxy:
                req_kwargs["proxies"] = {"http": proxy, "https": proxy}

        resp = client.get(google_url, **req_kwargs)
        final_url = resp.url
        if final_url and "google.com" not in final_url and "google." not in final_url:
            return final_url, "redirect_followed"

        # Strategy 3: HTML Parser for meta refresh / embedded links
        if resp.text:
            extracted = _extract_url_from_html(resp.text)
            if extracted:
                return extracted, "html_extracted"

    except Exception as e:
        return None, f"fallback_error:{type(e).__name__}"

    return None, "decode_failed"
