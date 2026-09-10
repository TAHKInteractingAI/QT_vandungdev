from __future__ import annotations

import time
import html
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import requests
from selectolax.parser import HTMLParser

from crawler.config import HEADERS, TIMEOUT
from crawler.naming import format_published_date

try:
    from googlenewsdecoder import gnewsdecoder
except ImportError:
    gnewsdecoder = None  # type: ignore


def fetch_rss(
    keyword: str,
    max_articles: int,
    locale: str | dict[str, str] = "vi",
    time_window: str | None = None,
    session: requests.Session | None = None,
    timeout: int = TIMEOUT,
) -> list[dict]:
    """Discover articles via Google News RSS for a specific locale/market. Returns google_url (CBM).
    Supports time_window (e.g. '1d', '2d', '48h', '7d', '1h') via 'when:' operator.
    """
    if isinstance(locale, dict):
        loc_cfg = locale
    else:
        from crawler.config import resolve_locales
        loc_cfg = resolve_locales(locale)[0]

    lang = loc_cfg["lang"]
    country = loc_cfg["country"]
    ceid = loc_cfg.get("ceid", f"{country}:{lang}")
    locale_name = loc_cfg.get("name", f"{country}:{lang}")

    query = keyword.strip()
    if time_window and "when:" not in query.lower():
        tw = time_window.strip().lower()
        if tw.startswith("when:"):
            tw = tw[5:]
        query = f"{query} when:{tw}"

    q = quote_plus(query)
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
        formatted_pub = format_published_date(pub)
        desc_raw = it.findtext("description") or ""
        desc_unesc = html.unescape(desc_raw)
        snippet = HTMLParser(desc_unesc).text(separator=" ", strip=True)[:500]
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
                "published": formatted_pub,
                "published_raw": pub,
                "snippet": snippet,
                "description_raw": desc_raw,
                "locale": locale_name,
                "country": country,
                "lang": lang,
            }
        )
    return articles


def fetch_rss_multi(
    keyword: str,
    max_articles: int,
    locales: list[dict[str, str]],
    time_window: str | None = None,
    session: requests.Session | None = None,
    timeout: int = TIMEOUT,
) -> list[dict]:
    """
    Fetch articles across multiple locales sequentially, deduplicating articles by link and title.
    Distributes target article count evenly across locales while collecting up to max_articles.
    """
    if not locales:
        return []

    # If only 1 locale, delegate directly
    if len(locales) == 1:
        return fetch_rss(
            keyword=keyword,
            max_articles=max_articles,
            locale=locales[0],
            time_window=time_window,
            session=session,
            timeout=timeout,
        )

    all_articles: list[dict] = []
    seen_keys: set[str] = set()
    per_locale_limit = max(1, (max_articles + len(locales) - 1) // len(locales))

    for loc in locales:
        if len(all_articles) >= max_articles:
            break
        try:
            fetched = fetch_rss(
                keyword=keyword,
                max_articles=per_locale_limit,
                locale=loc,
                time_window=time_window,
                session=session,
                timeout=timeout,
            )
            for art in fetched:
                dedup_key = (art.get("google_url") or art.get("title") or "").strip().lower()
                if dedup_key and dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    all_articles.append(art)
                if len(all_articles) >= max_articles:
                    break
        except Exception as e:
            print(f"[crawl] Notice: Failed to fetch RSS for locale {loc.get('name') or loc.get('lang')}: {e}")

    return all_articles[:max_articles]


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


def _decode_once(
    google_url: str,
    session: requests.Session | None = None,
    proxy: str | None = None,
    timeout: int = TIMEOUT,
) -> tuple[str | None, str]:
    """Single attempt to decode Google News URL using 3 fallback strategies."""
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


def decode_publisher_url(
    google_url: str,
    session: requests.Session | None = None,
    proxy: str | None = None,
    timeout: int = TIMEOUT,
    retries: int = 2,
    retry_delay: float = 1.0,
) -> tuple[str | None, str]:
    """
    Multi-strategy decoder with automatic retries: CBM google_url -> publisher_url.
    Try the `retries` again (default 2 times, total 3 attempts) if it fails.
    """
    if not google_url or "news.google.com" not in google_url:
        return None, "not_google_url"

    last_status = "decode_failed"
    for attempt in range(retries + 1):
        if attempt > 0:
            time.sleep(retry_delay * attempt)
        url, status = _decode_once(google_url, session=session, proxy=proxy, timeout=timeout)
        if url:
            suffix = f" (retry {attempt})" if attempt > 0 else ""
            return url, f"{status}{suffix}"
        last_status = status

    return None, last_status
