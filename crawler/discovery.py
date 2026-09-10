import base64
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, quote, quote_plus, unquote, urlparse

import requests
from selectolax.parser import HTMLParser

from crawler.config import (
    BING_LOCALE_MAP,
    CLOUDFLARE_WORKER_URL,
    DEFAULT_PROVIDER,
    HEADERS,
    TIMEOUT,
)
from crawler.naming import format_published_date

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None  # type: ignore

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


def extract_bing_publisher_url(link: str) -> str:
    """Extract real publisher URL from Bing News apiclick link."""
    if not link:
        return ""
    if "url=" in link:
        try:
            parsed = urlparse(link)
            qs = parse_qs(parsed.query)
            if "url" in qs and qs["url"]:
                target = qs["url"][0].strip()
                if target.startswith("http"):
                    return target
        except Exception:
            pass
    return link


def fetch_bing_rss(
    keyword: str,
    max_articles: int,
    locale: str | dict[str, str] = "vi",
    time_window: str | None = None,
    session: requests.Session | None = None,
    timeout: int = TIMEOUT,
) -> list[dict]:
    """Discover articles via Bing News RSS. Returns direct publisher URLs (100% un-obfuscated)."""
    lang = "vi"
    locale_name = "Vietnam (Tiếng Việt)"
    if isinstance(locale, dict):
        loc_key = locale.get("lang") or "vi"
        locale_name = locale.get("name") or loc_key
    else:
        loc_key = locale.lower()

    b_info = BING_LOCALE_MAP.get(loc_key, {"cc": "VN", "setlang": "vi"})
    cc = b_info["cc"]
    setlang = b_info["setlang"]

    query = keyword.strip()
    q = quote_plus(query)
    url = f"https://www.bing.com/news/search?q={q}&cc={cc}&setlang={setlang}&format=rss"

    resp = None
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
        snippet = HTMLParser(desc_raw).text(separator=" ", strip=True)[:500]

        source = ""
        if " - " in title:
            source = title.rsplit(" - ", 1)[-1].strip()
        if not source:
            source = "News"

        pub_url = extract_bing_publisher_url(link)

        articles.append(
            {
                "title": title,
                "source": source,
                "google_url": link,
                "url": pub_url,
                "publisher_url": pub_url,
                "decode_status": "direct_bing",
                "source_engine": "bing",
                "published": formatted_pub,
                "published_raw": pub,
                "snippet": snippet,
                "description_raw": desc_raw,
                "locale": locale_name,
                "country": cc,
                "lang": setlang,
            }
        )
    return articles


def fetch_bing_rss_multi(
    keyword: str,
    max_articles: int,
    locales: list[dict[str, str]],
    time_window: str | None = None,
    session: requests.Session | None = None,
    timeout: int = TIMEOUT,
) -> list[dict]:
    """Fetch articles from Bing News across multiple locales."""
    if not locales:
        return []
    if len(locales) == 1:
        return fetch_bing_rss(
            keyword,
            max_articles,
            locales[0],
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
            fetched = fetch_bing_rss(
                keyword,
                per_locale_limit,
                loc,
                time_window=time_window,
                session=session,
                timeout=timeout,
            )
            for art in fetched:
                dedup_key = (art.get("publisher_url") or art.get("title") or "").strip().lower()
                if dedup_key and dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    all_articles.append(art)
                if len(all_articles) >= max_articles:
                    break
        except Exception as e:
            print(f"[crawl] Notice: Failed to fetch Bing RSS for locale {loc.get('name') or loc.get('lang')}: {e}")

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
    """Unified news discovery supporting 'auto', 'bing', or 'google'."""
    p = (provider or "auto").strip().lower()

    if p == "bing":
        print(f"[crawl] Discovering articles via Bing News Engine ({len(locales)} locale(s))...")
        return fetch_bing_rss_multi(
            keyword,
            max_articles,
            locales,
            time_window=time_window,
            session=session,
            timeout=timeout,
        )

    if p == "google":
        print(f"[crawl] Discovering articles via Google News Engine ({len(locales)} locale(s))...")
        return fetch_rss_multi(
            keyword,
            max_articles,
            locales,
            time_window=time_window,
            session=session,
            timeout=timeout,
        )

    # Provider == 'auto': Try Google News first; if empty or fails, fallback to Bing News
    print(f"[crawl] Discovering articles via Google News RSS ({len(locales)} locale(s))...")
    try:
        articles = fetch_rss_multi(
            keyword,
            max_articles,
            locales,
            time_window=time_window,
            session=session,
            timeout=timeout,
        )
        if articles:
            return articles
    except Exception as e:
        print(f"[crawl] Notice: Google News discovery failed ({e}). Falling back to Bing News...")

    print(f"[crawl] Falling back to Bing News Engine ({len(locales)} locale(s))...")
    return fetch_bing_rss_multi(
        keyword,
        max_articles,
        locales,
        time_window=time_window,
        session=session,
        timeout=timeout,
    )


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
        # Fallback: Forward decoding request to Cloudflare Worker Edge
        try:
            worker_base = os.getenv("CLOUDFLARE_WORKER_URL", "https://qt-vandungdev.dungnguyen2661.workers.dev").rstrip("/")
            cf_url = f"{worker_base}/decode"
            params = {"url": f"https://news.google.com/rss/articles/{base64_str}"}
            w_resp = requests.get(cf_url, params=params, timeout=timeout)
            if w_resp.status_code == 200:
                data = w_resp.json()
                if data.get("status") and data.get("decoded_url"):
                    return data["decoded_url"]
        except Exception as e:
            print(f"[decode] Cloudflare Worker Edge fallback notice: {e}")
        return None

    try:
        parsed_data = json.loads(be_resp_text.split("\n\n")[1])[:-2]
        decoded_url = json.loads(parsed_data[0][2])[1]
        if decoded_url and "google.com" not in decoded_url and "google." not in decoded_url:
            return decoded_url
    except Exception:
        pass

    return None


def _decode_once(
    google_url: str,
    session: requests.Session | None = None,
    proxy: str | None = None,
    timeout: int = TIMEOUT,
) -> tuple[str | None, str]:
    """Single attempt to decode Google News or Bing News URL using multi-strategy cascading resolution."""
    if not google_url:
        return None, "empty_url"

    # Bing News Direct URL extraction (0ms)
    if "bing.com" in google_url:
        extracted = extract_bing_publisher_url(google_url)
        if extracted and "bing.com" not in extracted:
            return extracted, "direct_bing"

    # Direct publisher URL already provided
    if "news.google.com" not in google_url and "google.com" not in google_url:
        return google_url, "direct"

    # Strategy 0: Direct base64 regex decode (0ms, offline)
    direct = _extract_cbm_direct(google_url)
    if direct:
        return direct, "direct_b64"

    # Strategy 1: Delegate decoding to Cloudflare Worker Edge Gateway (Clean IP, Zero 429)
    worker_base = os.getenv("CLOUDFLARE_WORKER_URL", CLOUDFLARE_WORKER_URL)
    if worker_base:
        try:
            cf_url = f"{worker_base.rstrip('/')}/decode"
            w_resp = (session or requests).get(cf_url, params={"url": google_url}, timeout=timeout)
            if w_resp.status_code == 200:
                cf_data = w_resp.json()
                if cf_data.get("status") and cf_data.get("decoded_url"):
                    return cf_data["decoded_url"], "cloudflare_worker"
        except Exception as e:
            print(f"[decode] Cloudflare Worker Edge notice: {e}")

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
