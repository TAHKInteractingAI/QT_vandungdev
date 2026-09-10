from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image
from selectolax.parser import HTMLParser, Node

from crawler.config import HEADERS, PLACEHOLDER_HOSTS, TIMEOUT

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None  # type: ignore

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


def _meta_candidates(tree: HTMLParser, base_url: str) -> list[str]:
    out: list[str] = []
    for tag in tree.css("meta"):
        prop = (tag.attributes.get("property", "") or tag.attributes.get("name", "")).strip().lower()
        if prop not in ("og:image", "og:image:secure_url", "twitter:image", "twitter:image:src"):
            continue
        content = (tag.attributes.get("content") or "").strip()
        if not content or is_placeholder_url(content):
            continue
        out.append(urljoin(base_url, content))
    return out


def _link_candidates(tree: HTMLParser, base_url: str) -> list[str]:
    out: list[str] = []
    for tag in tree.css("link"):
        rel = (tag.attributes.get("rel") or "").lower()
        if "image_src" not in rel:
            continue
        href = (tag.attributes.get("href") or "").strip()
        if not href or is_placeholder_url(href):
            continue
        out.append(urljoin(base_url, href))
    return out


def _picture_candidates(tree: HTMLParser, base_url: str) -> list[str]:
    out: list[str] = []
    for source in tree.css("picture source"):
        curr = source.parent
        p_tags: set[str] = set()
        p_classes: list[str] = []
        while curr and curr.tag != "-root":
            p_tags.add(curr.tag.lower())
            if cls := curr.attributes.get("class"):
                p_classes.append(cls.lower())
            curr = curr.parent

        if p_tags & _PARENT_JUNK_TAGS:
            continue
        parent_classes = " ".join(p_classes)
        if any(bad in parent_classes for bad in _PARENT_JUNK_CLASSES):
            continue

        srcset = source.attributes.get("srcset", "") or source.attributes.get("data-srcset", "")
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


def _img_candidates(tree: HTMLParser, base_url: str) -> list[str]:
    out: list[str] = []
    for img in tree.css("img"):
        src = (
            img.attributes.get("data-src")
            or img.attributes.get("data-original")
            or img.attributes.get("data-lazy-src")
            or img.attributes.get("src")
            or ""
        ).strip()
        if not src:
            srcset = img.attributes.get("srcset", "") or img.attributes.get("data-srcset", "")
            if srcset:
                parts = [p.strip().split()[0] for p in srcset.split(",") if p.strip()]
                if parts:
                    src = parts[-1]
        if not src or src.startswith("data:") or is_placeholder_url(src):
            continue

        curr = img.parent
        p_tags: set[str] = set()
        p_classes: list[str] = []
        p_ids: list[str] = []
        while curr and curr.tag != "-root":
            p_tags.add(curr.tag.lower())
            if cls := curr.attributes.get("class"):
                p_classes.append(cls.lower())
            if cid := curr.attributes.get("id"):
                p_ids.append(cid.lower())
            curr = curr.parent

        if p_tags & _PARENT_JUNK_TAGS:
            continue

        parent_classes = " ".join(p_classes)
        parent_ids = " ".join(p_ids)
        if any(bad in parent_classes or bad in parent_ids for bad in _PARENT_JUNK_CLASSES):
            continue

        w, h = img.attributes.get("width", ""), img.attributes.get("height", "")
        try:
            if (w and int(w) < 150) or (h and int(h) < 100):
                continue
        except ValueError:
            pass

        low = src.lower()
        if any(x in low for x in _JUNK):
            continue

        cls = (img.attributes.get("class") or "").lower()
        alt = (img.attributes.get("alt") or "").lower()
        if any(bad in cls or bad in alt for bad in ["logo", "icon", "avatar", "banner", "adv"]):
            continue

        out.append(urljoin(base_url, src))
        if len(out) >= 12:
            break
    return out


def extract_image_urls(page_url: str, html_text: str, base_url: str) -> list[str]:
    """Extract up to 8 clean image candidates for post-download validation using high performance selectolax."""
    tree = HTMLParser(html_text)
    candidates = [
        *_meta_candidates(tree, base_url),
        *_link_candidates(tree, base_url),
        *_picture_candidates(tree, base_url),
        *_img_candidates(tree, base_url),
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
        resp = None
        if session is not None:
            resp = session.get(url, timeout=timeout, stream=True)
        else:
            resp = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)

        if resp.status_code != 200 and curl_requests is not None:
            # Fallback to curl_cffi (Chrome TLS fingerprint) if blocked by Cloudflare/CDN (e.g. 403)
            try:
                resp = curl_requests.get(url, headers=HEADERS, timeout=timeout, impersonate="chrome")
            except Exception:
                pass

        if resp is None or resp.status_code != 200:
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
