from __future__ import annotations

import json
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import requests

from crawler.config import (
    DEFAULT_COUNTRY,
    DEFAULT_LANG,
    DEFAULT_WORKERS,
    POOL_MAXSIZE,
    TIMEOUT,
)
from crawler.discovery import decode_publisher_url, fetch_rss
from crawler.excel import export_excel
from crawler.images import download_images, extract_image_urls
from crawler.network import create_session, fetch_with_status
from crawler.storage.base import BaseStorageBackend
from crawler.storage.local import LocalStorageBackend

_checkpoint_lock = threading.Lock()
_ui_lock = threading.Lock()


def _append_checkpoint(jsonl_path: Path, art: dict) -> None:
    """Append single article record to JSONL checkpoint file (thread-safe)."""
    record = dict(art)
    if imgs := record.get("saved_images"):
        record["saved_images"] = [str(p) for p in imgs]
    with _checkpoint_lock:
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_completed_checkpoint(jsonl_path: Path) -> dict[str, dict]:
    """Load existing checkpoint into a mapping of google_url -> article dict."""
    if not jsonl_path.exists():
        return {}
    completed: dict[str, dict] = {}
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                key = data.get("google_url") or data.get("url") or data.get("title")
                if key:
                    if imgs := data.get("saved_images"):
                        data["saved_images"] = [Path(p) for p in imgs]
                    completed[key] = data
            except Exception:
                continue
    return completed


def _process_one(
    art: dict,
    prefix: str,
    images_dir: Path,
    session: requests.Session | None = None,
    proxy: str | None = None,
    rotate_ua: bool = False,
    timeout: int = TIMEOUT,
    stop_event: threading.Event | None = None,
) -> str:
    """Process single article. Early returns, no nested ladder. Returns status."""
    if stop_event and stop_event.is_set():
        return "interrupted"

    google_url = art.get("google_url", "")
    if not google_url:
        return "no_google_url"

    publisher_url, decode_status = decode_publisher_url(google_url, session=session, proxy=proxy, timeout=timeout)
    if stop_event and stop_event.is_set():
        return "interrupted"

    if not publisher_url:
        return f"decode_failed ({decode_status})"
    art["publisher_url"] = publisher_url
    art["url"] = publisher_url

    html, code, alive_status = fetch_with_status(publisher_url, session=session, timeout=timeout, rotate_ua=rotate_ua)
    if stop_event and stop_event.is_set():
        return "interrupted"

    art["alive"] = alive_status
    art["http_code"] = code
    if html is None:
        return alive_status

    urls = extract_image_urls(publisher_url, html, publisher_url)
    art["image_urls"] = urls
    if not urls:
        return f"{alive_status} | no_images_found"

    saved = download_images(urls, images_dir, prefix, session=session, timeout=timeout, stop_event=stop_event)
    art["saved_images"] = saved
    if not saved:
        return f"{alive_status} | download_failed | {len(urls)} candidates"
    return f"{alive_status} | ok | {len(saved)} image(s)"


def crawl_google_news(
    keyword: str,
    max_articles: int = 20,
    output_dir: str | Path = "output",
    *,
    workers: int = DEFAULT_WORKERS,
    proxy: str | None = None,
    rotate_ua: bool = False,
    lang: str = DEFAULT_LANG,
    country: str = DEFAULT_COUNTRY,
    timeout: int = TIMEOUT,
    resume: bool = True,
    show_progress: bool = True,
    storage: BaseStorageBackend | None = None,
    job_id: str | None = None,
) -> dict:
    if not keyword or not keyword.strip():
        raise ValueError("keyword must be non-empty")
    if max_articles <= 0:
        raise ValueError("max_articles must be > 0")
    if workers <= 0:
        raise ValueError("workers must be > 0")

    keyword = keyword.strip()
    safe_keyword = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in keyword)
    safe_keyword = safe_keyword.strip("_") or "News"
    effective_job_id = job_id or f"{safe_keyword}_{datetime.now().strftime('%H%M_%d%m%Y')}"
    backend = storage or LocalStorageBackend(output_dir=output_dir)
    backend.init_session(job_id=effective_job_id, keyword=keyword, output_dir=output_dir)

    output_dir = Path(output_dir)
    images_dir = output_dir / "images"
    jsonl_path = output_dir / "articles.jsonl"
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    extra_info = []
    if proxy:
        extra_info.append(f"proxy={proxy}")
    if rotate_ua:
        extra_info.append("rotate_ua=True")
    extra_str = f" ({', '.join(extra_info)})" if extra_info else ""
    print(f"[crawl] keyword={keyword!r} max={max_articles} workers={workers} lang={lang} country={country}{extra_str} output={output_dir}")
    print("[crawl] Press Ctrl+C to stop safely at any time.")

    if not resume and jsonl_path.exists():
        jsonl_path.unlink()

    completed_map = backend.load_completed_checkpoint() if resume else {}
    if completed_map:
        print(f"[crawl] loaded {len(completed_map)} previously completed article(s) from checkpoint")

    interrupted = False
    articles: list[dict] = []
    pool_size = max(POOL_MAXSIZE, workers * 4)

    with create_session(proxy=proxy, pool_size=pool_size) as session:
        try:
            articles = fetch_rss(keyword, max_articles, lang=lang, country=country, session=session, timeout=timeout)
        except KeyboardInterrupt:
            print("\n[crawl] Stop requested via Ctrl+C during RSS discovery.")
            xlsx = export_excel([], output_dir)
            return {
                "keyword": keyword,
                "discovered": 0,
                "processed": 0,
                "decoded": 0,
                "alive": 0,
                "with_images": 0,
                "saved_images": 0,
                "interrupted": True,
                "xlsx": str(xlsx),
                "jsonl": str(jsonl_path),
                "output_dir": str(output_dir),
                "images_dir": str(images_dir),
            }

        print(f"[crawl] discovered {len(articles)} articles")
        if not articles:
            xlsx = export_excel([], output_dir)
            return {
                "keyword": keyword,
                "discovered": 0,
                "processed": 0,
                "decoded": 0,
                "alive": 0,
                "with_images": 0,
                "saved_images": 0,
                "interrupted": False,
                "xlsx": str(xlsx),
                "jsonl": str(jsonl_path),
                "output_dir": str(output_dir),
                "images_dir": str(images_dir),
            }

        for idx, art in enumerate(articles, 1):
            art["order"] = idx
            art["article_id"] = f"article_{idx:05d}"
            art["status"] = ""
            art["saved_images"] = []
            art["publisher_url"] = ""

        try:
            from tqdm.auto import tqdm as _tqdm  # type: ignore

            _has_tqdm = True
        except ImportError:
            _has_tqdm = False
            _tqdm = None  # type: ignore

        use_bar = show_progress and _has_tqdm
        pbar = _tqdm(total=len(articles), desc=keyword[:30], unit=" News", ncols=90) if use_bar else None  # type: ignore

        stop_event = threading.Event()

        def _report_progress(idx: int, art: dict) -> None:
            if stop_event.is_set():
                return
            with _ui_lock:
                if stop_event.is_set():
                    return
                title = (art.get("title") or "").strip()
                if len(title) > 50:
                    title = title[:47] + "..."
                source = art.get("source", "")
                status = art.get("status", "")
                line = f"{idx:3d}. {title} — {source} [{status}]"
                if use_bar:
                    try:
                        _tqdm.write(line)
                    except Exception:
                        print(line)
                    if pbar is not None:
                        try:
                            pbar.update(1)
                            alive_cnt = sum(1 for a in articles if a.get("http_code") == 200)
                            ok_cnt = sum(1 for a in articles if " | ok |" in a.get("status", ""))
                            pbar.set_postfix(alive=alive_cnt, ok=ok_cnt, refresh=False)
                        except Exception:
                            pass
                else:
                    print(line)

        def _worker_task(idx: int, art: dict) -> None:
            if stop_event.is_set():
                return
            g_url = art.get("google_url", "")
            if resume and g_url in completed_map:
                prev = completed_map[g_url]
                art.update(prev)
                art["order"] = idx
                art["article_id"] = f"article_{idx:05d}"
                _report_progress(idx, art)
                return

            prefix = art.get("article_id") or f"article_{idx:05d}"
            status = _process_one(
                art,
                prefix,
                images_dir,
                session=session,
                proxy=proxy,
                rotate_ua=rotate_ua,
                timeout=timeout,
                stop_event=stop_event,
            )
            if stop_event.is_set():
                return
            art["status"] = status
            if art.get("saved_images"):
                art["saved_images"] = backend.process_saved_images(art["saved_images"], prefix)
            backend.append_checkpoint(art)
            _report_progress(idx, art)

        executor = ThreadPoolExecutor(max_workers=max(1, workers))
        try:
            futures = [
                executor.submit(_worker_task, idx, art)
                for idx, art in enumerate(articles, 1)
            ]
            for f in futures:
                f.result()
        except KeyboardInterrupt:
            interrupted = True
            stop_event.set()
            print("\n[crawl] Stop requested (Ctrl+C). Cancelling pending tasks and saving progress...")
            executor.shutdown(wait=False, cancel_futures=True)
        finally:
            stop_event.set()
            if use_bar and pbar is not None:
                try:
                    pbar.close()  # type: ignore
                except Exception:
                    pass
            executor.shutdown(wait=False)

    processed_articles = [a for a in articles if a.get("status")]
    processed_articles.sort(key=lambda a: a.get("order", 0))
    decode_ok = sum(1 for a in processed_articles if a.get("publisher_url"))
    alive_cnt = sum(1 for a in processed_articles if a.get("http_code") == 200)
    ok = sum(1 for a in processed_articles if " | ok |" in a.get("status", ""))
    total = sum(len(a.get("saved_images", [])) for a in processed_articles)

    dest_info = backend.finalize(processed_articles)
    if interrupted:
        print(f"[crawl] safe exit (Ctrl+C): {len(processed_articles)}/{len(articles)} articles processed, {ok} with images -> {dest_info}")
    else:
        print(f"[crawl] done: {len(articles)} discovered, {decode_ok} decoded, {alive_cnt} alive 200, {ok} with images, {total} files -> {dest_info}")

    result_payload = {
        "keyword": keyword,
        "discovered": len(articles),
        "processed": len(processed_articles),
        "decoded": decode_ok,
        "alive": alive_cnt,
        "with_images": ok,
        "saved_images": total,
        "interrupted": interrupted,
        "output_dir": str(output_dir),
        "images_dir": str(images_dir),
    }
    result_payload.update(dest_info)
    return result_payload
