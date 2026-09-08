from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

from crawler.config import HEADERS, PLACEHOLDER_HOSTS, TIMEOUT

_JUNK = (
    "spinner",
    "pixel",
    "transparent",
    "1x1",
    "avatar",
    "thumb/24x24",
    "thumb/48x48",
    "icon-",
    "icon.",
    "/icon",
    "logo",
    "banner",
    "adv",
    "badge",
    "button",
    "favicon",
    "placeholder",
    "share",
    "social",
    "widget",
)
_VALID_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_PARENT_JUNK_TAGS = {"header", "footer", "nav", "aside", "menu"}
_PARENT_JUNK_CLASSES = ("header", "footer", "sidebar", "menu", "banner", "adv", "social", "widget", "logo", "icon")

# Minimum size threshold and aspect ratio for article content images
MIN_WIDTH = 200
MIN_HEIGHT = 150
MAX_ASPECT_RATIO = 4.0


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
        parent_names = {p.name.lower() for p in source.parents}
        if parent_names & _PARENT_JUNK_TAGS:
            continue
        parent_classes = " ".join(" ".join(p.get("class", [])) for p in source.parents if p.get("class")).lower()
        if any(bad in parent_classes for bad in _PARENT_JUNK_CLASSES):
            continue

        srcset = source.get("srcset", "") or source.get("data-srcset", "")
        if not srcset:
            continue
        first = srcset.split(",")[0].strip().split()[0]
        if not first or first.startswith("data:") or is_placeholder_url(first):
            continue
        low = first.lower()
        if any(x in low for x in _JUNK):
            continue
        out.append(urljoin(base_url, first))
    return out


def _img_candidates(soup, base_url: str) -> list[str]:
    out: list[str] = []
    for img in soup.find_all("img"):
        src = (
            img.get("data-src")
            or img.get("data-original")
            or img.get("data-lazy-src")
            or img.get("src")
            or ""
        ).strip()
        if not src:
            srcset = img.get("srcset", "") or img.get("data-srcset", "")
            if srcset:
                parts = [p.strip().split()[0] for p in srcset.split(",") if p.strip()]
                if parts:
                    src = parts[-1]
        if not src or src.startswith("data:") or is_placeholder_url(src):
            continue

        parent_names = {p.name.lower() for p in img.parents}
        if parent_names & _PARENT_JUNK_TAGS:
            continue

        parent_classes = " ".join(" ".join(p.get("class", [])) for p in img.parents if p.get("class")).lower()
        parent_ids = " ".join(str(p.get("id", "")) for p in img.parents if p.get("id")).lower()
        if any(bad in parent_classes or bad in parent_ids for bad in _PARENT_JUNK_CLASSES):
            continue

        w, h = img.get("width", ""), img.get("height", "")
        try:
            if (w and int(w) < 150) or (h and int(h) < 100):
                continue
        except ValueError:
            pass

        low = src.lower()
        if any(x in low for x in _JUNK):
            continue

        cls = " ".join(img.get("class", [])).lower()
        alt = (img.get("alt") or "").lower()
        if any(bad in cls or bad in alt for bad in ["logo", "icon", "avatar", "banner", "adv"]):
            continue

        out.append(urljoin(base_url, src))
        if len(out) >= 12:
            break
    return out


def extract_image_urls(page_url: str, html_text: str, base_url: str) -> list[str]:
    """Extract up to 8 clean image candidates for post-download validation."""
    soup = BeautifulSoup(html_text, "lxml")
    candidates = [
        *_meta_candidates(soup, base_url),
        *_link_candidates(soup, base_url),
        *_picture_candidates(soup, base_url),
        *_img_candidates(soup, base_url),
    ]
    uniq = list(dict.fromkeys(u.split("#")[0].strip().rstrip('",\'') for u in candidates))
    return [u for u in uniq if u.startswith("http") and not is_placeholder_url(u)][:8]


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
        if len(data) < 2048:
            return None

        # Assessing the actual size and aspect ratio of images via PIL
        try:
            with Image.open(BytesIO(data)) as im:
                w, h = im.size
                ratio = max(w, h) / max(min(w, h), 1)
                if w < MIN_WIDTH or h < MIN_HEIGHT or ratio > MAX_ASPECT_RATIO:
                    return None
        except Exception:
            return None

        ctype = resp.headers.get("Content-Type", "")
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
    max_images: int = 1,
    session: requests.Session | None = None,
    timeout: int = TIMEOUT,
    stop_event: Any = None,
) -> list[Path]:
    """Download valid article images sequentially or concurrently with candidate fallback."""
    if not image_urls or (stop_event and stop_event.is_set()):
        return []
    dest_dir.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []
    # Iterate through the list of candidates (maximum 8) until you have collected enough valid images (max_images).
    for url in image_urls:
        if stop_event and stop_event.is_set():
            break
        idx = len(saved) + 1
        res = _download_single(url, dest_dir, f"{prefix}_{idx:02d}", session=session, timeout=timeout)
        if res is not None:
            saved.append(res)
            if len(saved) >= max_images:
                break

    return saved
