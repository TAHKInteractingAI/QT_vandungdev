from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import requests
from selectolax.parser import HTMLParser

from crawler.config import DEFAULT_PROVIDER, HEADERS, TIMEOUT
from crawler.naming import format_published_date


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
    for loc in locales:
        remaining = max_articles - len(all_articles)
        if remaining <= 0:
            break
        try:
            fetched = fetch_rss(
                keyword=keyword,
                max_articles=remaining,
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


def discover_articles(
    keyword: str,
    max_articles: int,
    locales: list[dict[str, str]],
    time_window: str | None = None,
    session: requests.Session | None = None,
    timeout: int = TIMEOUT,
    provider: str = DEFAULT_PROVIDER,
) -> list[dict]:
    """Discover articles via Google News RSS across specified locales."""
    print(f"[crawl] Discovering articles via Google News RSS ({len(locales)} locale(s))...")
    return fetch_rss_multi(
        keyword,
        max_articles,
        locales,
        time_window=time_window,
        session=session,
        timeout=timeout,
    )
