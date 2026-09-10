from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from PIL import Image

if TYPE_CHECKING:
    import requests

from crawler.config import TIMEOUT

PLACEHOLDER_HOSTS = ("gstatic.com", "google.com", "googleusercontent.com")
_VALID_EXTS = (".jpg", ".png", ".webp", ".gif")
_JUNK = ("icon", "avatar", "blank.gif", "spacer", "advert", "tracker", "button", "pixel")
_PARENT_JUNK_CLASSES = {"footer", "header", "nav", "menu", "sidebar", "comment", "related", "recommend", "share", "social"}
_PARENT_JUNK_TAGS = {"nav", "header", "footer", "aside", "form"}

MIN_WIDTH = 200
MIN_HEIGHT = 150
MAX_ASPECT_RATIO = 4.0


def is_placeholder_url(url: str) -> bool:
    return any(h in url.lower() for h in PLACEHOLDER_HOSTS)


def _meta_candidates(soup: BeautifulSoup, base_url: str) -> list[str]:
    out: list[str] = []
    for tag in soup.find_all("meta"):
        prop = tag.get("property", "") or tag.get("name", "")
        if prop in ("og:image", "twitter:image", "og:image:url", "twitter:image:src"):
            if val := tag.get("content"):
                v = val.strip().split("#")[0]
                if v.startswith("http") and not is_placeholder_url(v):
                    out.append(v)
                elif v and not is_placeholder_url(v):
                    out.append(urljoin(base_url, v))
    return out


def _link_candidates(soup: BeautifulSoup, base_url: str) -> list[str]:
    out: list[str] = []
    for link in soup.find_all("link", rel=True):
        rels = link.get("rel")
        rel_list = rels if isinstance(rels, list) else [str(rels)]
        if "image_src" in rel_list or "apple-touch-icon" in rel_list:
            if href := link.get("href"):
                h = href.strip().split("#")[0]
                if h.startswith("http") and not is_placeholder_url(h):
                    out.append(h)
                elif h and not is_placeholder_url(h):
                    out.append(urljoin(base_url, h))
    return out


def _picture_candidates(soup: BeautifulSoup, base_url: str) -> list[str]:
    out: list[str] = []
    for pic in soup.find_all("picture"):
        for source in pic.find_all("source"):
            srcset = source.get("srcset", "")
            if srcset:
                parts = [p.strip().split()[0] for p in srcset.split(",") if p.strip()]
                if parts:
                    best = parts[-1]
                    if best.startswith("http") and not is_placeholder_url(best):
                        out.append(best)
                    elif best and not is_placeholder_url(best):
                        out.append(urljoin(base_url, best))
                    break
        img = pic.find("img")
        if img:
            src = img.get("src") or img.get("data-src") or ""
            if src and not src.startswith("data:") and not is_placeholder_url(src):
                full_src = urljoin(base_url, src)
                out.append(full_src)
    return out


def _img_candidates(soup: BeautifulSoup, base_url: str) -> list[str]:
    out: list[str] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original") or ""
        if not src:
            srcset = img.get("srcset", "")
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
    """Extract clean image candidates for post-download validation."""
    soup = BeautifulSoup(html_text, "lxml")
    candidates = [
        *_meta_candidates(soup, base_url),
        *_link_candidates(soup, base_url),
        *_picture_candidates(soup, base_url),
        *_img_candidates(soup, base_url),
    ]
    uniq = list(dict.fromkeys(u.split("#")[0].strip().rstrip('",\'') for u in candidates))
    return [u for u in uniq if u.startswith("http") and not is_placeholder_url(u)][:12]


def download_single_image(
    url: str,
    dest_dir: Path,
    filename: str,
    session: requests.Session | None = None,
    timeout: int = TIMEOUT,
) -> Path | None:
    """Download single image and validate dimensions."""
    try:
        import requests as _requests

        sess = session or _requests.Session()
        resp = sess.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200 or len(resp.content) < 2048:
            return None

        # Validate with PIL
        try:
            with Image.open(BytesIO(resp.content)) as im:
                w, h = im.size
                ratio = max(w, h) / max(min(w, h), 1)
                if w < MIN_WIDTH or h < MIN_HEIGHT or ratio > MAX_ASPECT_RATIO:
                    return None
        except Exception:
            return None

        data = resp.content
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
    max_images: int | None = None,
    session: requests.Session | None = None,
    timeout: int = TIMEOUT,
    stop_event: Any = None,
) -> list[Path]:
    """Download valid article images with candidate fallback."""
    if not image_urls or (stop_event and stop_event.is_set()):
        return []
    dest_dir.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []
    limit = max_images if max_images is not None else len(image_urls)

    for url in image_urls:
        if stop_event and stop_event.is_set():
            break
        idx = len(saved) + 1
        res = download_single_image(url, dest_dir, f"{prefix}_{idx:02d}", session=session, timeout=timeout)
        if res is not None:
            saved.append(res)
            if len(saved) >= limit:
                break

    return saved
