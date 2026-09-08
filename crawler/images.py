from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from crawler.config import HEADERS, PLACEHOLDER_HOSTS, TIMEOUT

_JUNK = ("spinner", "pixel", "transparent", "1x1", "avatar")
_VALID_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def is_placeholder_url(url: str) -> bool:
    low = url.lower()
    return any(h in low for h in PLACEHOLDER_HOSTS)


def _meta_candidates(soup, base_url: str) -> list[str]:
    out: list[str] = []
    for tag in soup.find_all("meta"):
        prop = (tag.get("property", "") or tag.get("name", "")).strip().lower()
        if prop not in ("og:image", "og:image:secure_url", "twitter:image", "twitter:image:src"):
            continue
        content = (tag.get("content") or "").strip()
        if not content or is_placeholder_url(content):
            continue
        out.append(urljoin(base_url, content))
    return out


def _link_candidates(soup, base_url: str) -> list[str]:
    out: list[str] = []
    for tag in soup.find_all("link", rel=lambda x: x and "image_src" in x.lower() if isinstance(x, str) else False):
        href = (tag.get("href") or "").strip()
        if not href or is_placeholder_url(href):
            continue
        out.append(urljoin(base_url, href))
    return out


def _picture_candidates(soup, base_url: str) -> list[str]:
    out: list[str] = []
    for source in soup.find_all("source"):
        srcset = source.get("srcset", "") or source.get("data-srcset", "")
        if not srcset:
            continue
        first = srcset.split(",")[0].strip().split()[0]
        if not first or first.startswith("data:") or is_placeholder_url(first):
            continue
        out.append(urljoin(base_url, first))
    return out


def _img_candidates(soup, base_url: str) -> list[str]:
    out: list[str] = []
    for img in soup.find_all("img"):
        src = (img.get("src") or img.get("data-src") or img.get("data-original") or img.get("data-lazy-src") or "").strip()
        if not src:
            srcset = img.get("srcset", "") or img.get("data-srcset", "")
            if srcset:
                parts = [p.strip().split()[0] for p in srcset.split(",") if p.strip()]
                if parts:
                    src = parts[-1]
        if not src or src.startswith("data:") or is_placeholder_url(src):
            continue
        w, h = img.get("width", ""), img.get("height", "")
        try:
            if w and h and int(w) < 80 and int(h) < 80:
                continue
        except ValueError:
            pass
        low = src.lower()
        if any(x in low for x in _JUNK):
            continue
        if "logo" in low and "cdn" not in low:
            continue
        out.append(urljoin(base_url, src))
        if len(out) >= 8:
            break
    return out


def extract_image_urls(page_url: str, html_text: str, base_url: str) -> list[str]:
    """Extract 1-2 best image candidates. Flat pipeline, no nested loops."""
    soup = BeautifulSoup(html_text, "lxml")
    # ponytail: collect flat, dedupe once
    candidates = [
        *_meta_candidates(soup, base_url),
        *_link_candidates(soup, base_url),
        *_picture_candidates(soup, base_url),
        *_img_candidates(soup, base_url),
    ]
    # dedupe, keep order
    uniq = list(dict.fromkeys(u.split("#")[0].strip().rstrip('",\'') for u in candidates))
    # filter once
    uniq = [u for u in uniq if u.startswith("http") and not is_placeholder_url(u)]
    return uniq[:2]


def _download_single(
    url: str,
    dest_dir: Path,
    filename: str,
    session: requests.Session | None = None,
    timeout: int = TIMEOUT,
) -> Path | None:
    try:
        if session is not None:
            resp = session.get(url, timeout=timeout, stream=True)
        else:
            resp = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
        if resp.status_code != 200:
            return None
        data = resp.content
        if len(data) < 1024:
            return None
        ctype = resp.headers.get("Content-Type", "")
        is_image = data.startswith((b"\xff\xd8", b"\x89PNG", b"GIF8", b"RIFF")) or "image" in ctype or "octet-stream" in ctype
        if not is_image and "text/html" in ctype:
            return None
        ext = Path(urlparse(url).path).suffix.lower()
        if ext == ".jpeg":
            ext = ".jpg"
        elif ext not in _VALID_EXTS:
            if (data.startswith(b"RIFF") and b"WEBP" in data[:16]) or "webp" in ctype:
                ext = ".webp"
            elif data.startswith(b"\x89PNG") or "png" in ctype:
                ext = ".png"
            elif data.startswith(b"GIF8") or "gif" in ctype:
                ext = ".gif"
            else:
                ext = ".jpg"
        fpath = dest_dir / f"{filename}{ext}"
        fpath.write_bytes(data)
        return fpath
    except Exception:
        return None


def download_images(
    image_urls: list[str],
    dest_dir: Path,
    prefix: str,
    session: requests.Session | None = None,
    timeout: int = TIMEOUT,
) -> list[Path]:
    """Download image URLs concurrently. Returns saved paths in candidate order."""
    if not image_urls:
        return []
    dest_dir.mkdir(parents=True, exist_ok=True)
    if len(image_urls) == 1:
        res = _download_single(image_urls[0], dest_dir, f"{prefix}_01", session=session, timeout=timeout)
        return [res] if res else []

    with ThreadPoolExecutor(max_workers=min(len(image_urls), 4)) as pool:
        futures = [
            pool.submit(_download_single, url, dest_dir, f"{prefix}_{idx:02d}", session, timeout)
            for idx, url in enumerate(image_urls, 1)
        ]
        results = [f.result() for f in futures]
    return [p for p in results if p is not None]
