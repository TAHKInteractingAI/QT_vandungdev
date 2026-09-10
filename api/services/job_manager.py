from datetime import datetime, timezone
from pathlib import Path
import threading
import uuid
from typing import Any

import orjson

from api.config import settings
from crawler.core import crawl_google_news


class JobManager:
    """
    Manages Crawl Job lifecycle:
    - Concurrency Lock: Ensures only 1 crawl job runs at any given time.
    - Background Worker: Executes crawl_google_news in a separate thread without blocking the Event Loop.
    - Flexible Configuration: Accepts all parameters supported by crawler/cli.py (proxy, rotate_ua, resume, timeout...).
    - Persistence: Persists job state and metadata to storage/jobs/{job_id}.json.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._current_job_id: str | None = None
        self._jobs_cache: dict[str, dict[str, Any]] = {}

    @property
    def current_job_id(self) -> str | None:
        return self._current_job_id

    def is_running(self) -> bool:
        return self._current_job_id is not None

    def _job_file(self, job_id: str) -> Path:
        return settings.jobs_metadata_path / f"{job_id}.json"

    def _save_job_state(self, job_data: dict[str, Any]) -> None:
        job_id = job_data["job_id"]
        self._jobs_cache[job_id] = job_data
        file_path = self._job_file(job_id)
        json_bytes = orjson.dumps(job_data, option=orjson.OPT_INDENT_2)
        with open(file_path, "wb") as f:
            f.write(json_bytes)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        if job_id in self._jobs_cache:
            return self._jobs_cache[job_id]
        file_path = self._job_file(job_id)
        if file_path.exists():
            try:
                with open(file_path, "rb") as f:
                    data = orjson.loads(f.read())
                    self._jobs_cache[job_id] = data
                    return data
            except Exception:
                return None
        return None

    def get_latest_job(self) -> dict[str, Any] | None:
        if self._current_job_id:
            return self.get_job(self._current_job_id)
        job_files = sorted(settings.jobs_metadata_path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if job_files:
            return self.get_job(job_files[0].stem)
        return None

    def create_and_start_job(
        self,
        keyword: str,
        max_articles: int,
        workers: int,
        lang: str | list[str],
        timeout: int,
        proxy: str | None,
        rotate_ua: bool,
        resume: bool,
        show_progress: bool,
        time_window: str | None = None,
        storage_mode: str | None = None,
        tz: str | None = None,
        ping_url: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._current_job_id is not None:
                raise RuntimeError(f"Another crawl job is currently running: {self._current_job_id}")

            effective_tz = tz or settings.DEFAULT_TIMEZONE
            effective_ping_url = ping_url or settings.CRON_HEARTBEAT_URL
            effective_provider = provider or settings.DEFAULT_PROVIDER

            from crawler.naming import generate_run_tag, get_timezone
            tz_obj = get_timezone(effective_tz)
            now = datetime.now(tz_obj)
            safe_keyword, time_tag = generate_run_tag(keyword, now, tz=effective_tz)
            short_id = uuid.uuid4().hex[:4]
            job_id = f"{time_tag}_{short_id}"

            job_dir = settings.storage_path / time_tag
            job_dir.mkdir(parents=True, exist_ok=True)

            effective_storage_mode = (storage_mode or settings.DEFAULT_STORAGE_MODE or "google").lower()

            from crawler.config import resolve_locales
            resolved = resolve_locales(lang)
            markets_list = [m.get("name", m["lang"]) for m in resolved]
            primary_lang = ",".join(lang) if isinstance(lang, list) else str(lang)

            job_data: dict[str, Any] = {
                "job_id": job_id,
                "status": "pending",
                "message": "Job created and queued for execution",
                "keyword": keyword,
                "max_articles": max_articles,
                "workers": workers,
                "lang": primary_lang,
                "markets": markets_list,
                "time_window": time_window,
                "provider": effective_provider,
                "timeout": timeout,
                "proxy": proxy,
                "rotate_ua": rotate_ua,
                "resume": resume,
                "show_progress": show_progress,
                "storage_mode": effective_storage_mode,
                "timezone": effective_tz,
                "ping_url": effective_ping_url,
                "created_at": now.isoformat(),
                "started_at": None,
                "completed_at": None,
                "output_dir": str(job_dir),
                "excel_path": None,
                "json_path": None,
                "jsonl_path": None,
                "spreadsheet_url": None,
                "drive_folder_url": None,
                "stats": None,
                "error": None,
            }
            self._current_job_id = job_id
            self._save_job_state(job_data)

        # Run crawler worker in background thread
        threading.Thread(
            target=self._run_crawler_thread,
            args=(
                job_id,
                keyword,
                max_articles,
                workers,
                lang,
                time_window,
                timeout,
                proxy,
                rotate_ua,
                resume,
                show_progress,
                effective_storage_mode,
                job_dir,
                effective_tz,
                effective_ping_url,
                effective_provider,
            ),
            daemon=True,
        ).start()

        return job_data

    def _run_crawler_thread(
        self,
        job_id: str,
        keyword: str,
        max_articles: int,
        workers: int,
        lang: str | list[str],
        time_window: str | None,
        timeout: int,
        proxy: str | None,
        rotate_ua: bool,
        resume: bool,
        show_progress: bool,
        storage_mode: str,
        output_dir: Path,
        tz: str | None = None,
        ping_url: str | None = None,
        provider: str = "auto",
    ) -> None:
        job = self.get_job(job_id)
        if not job:
            return

        job["status"] = "running"
        job["message"] = "Crawling in progress..."
        job["started_at"] = datetime.now(timezone.utc).isoformat()
        self._save_job_state(job)

        try:
            # Instantiate backend based on storage_mode
            backend = None
            if storage_mode == "google":
                try:
                    from crawler.storage.google import GoogleCloudStorageBackend
                    backend = GoogleCloudStorageBackend()
                except Exception as g_err:
                    print(f"[JobManager] Warning: Google Cloud storage init failed ({g_err}), falling back to local Excel.")
                    from crawler.storage.local import LocalStorageBackend
                    backend = LocalStorageBackend(output_dir=output_dir)
            else:
                from crawler.storage.local import LocalStorageBackend
                backend = LocalStorageBackend(output_dir=output_dir)

            result = crawl_google_news(
                keyword=keyword,
                max_articles=max_articles,
                output_dir=output_dir,
                workers=workers,
                lang=lang,
                time_window=time_window,
                timeout=timeout,
                proxy=proxy,
                rotate_ua=rotate_ua,
                resume=resume,
                show_progress=show_progress,
                storage=backend,
                job_id=job_id,
                timezone=tz,
                provider=provider,
            )
            job["status"] = "completed"
            job["message"] = "Crawl job completed successfully"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["excel_path"] = result.get("xlsx")
            job["json_path"] = result.get("json")
            job["jsonl_path"] = result.get("jsonl")
            job["spreadsheet_url"] = result.get("spreadsheet_url")
            job["drive_folder_url"] = result.get("drive_folder_url")
            job["stats"] = result

            # Send Heartbeat Ping notification to cron-job.org / monitoring service
            if ping_url:
                try:
                    import requests
                    requests.get(ping_url, timeout=10)
                    print(f"[JobManager] Heartbeat ping sent successfully to {ping_url}")
                except Exception as ping_err:
                    print(f"[JobManager] Warning: Failed to send heartbeat ping: {ping_err}")

        except Exception as exc:
            job["status"] = "failed"
            job["message"] = f"Crawl job failed with error: {str(exc)}"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
        finally:
            with self._lock:
                self._current_job_id = None
            self._save_job_state(job)


job_manager = JobManager()
