import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import uuid
from typing import Any

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
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(job_data, f, ensure_ascii=False, indent=2, default=str)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        if job_id in self._jobs_cache:
            return self._jobs_cache[job_id]
        file_path = self._job_file(job_id)
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
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
        lang: str,
        country: str,
        timeout: int,
        proxy: str | None,
        rotate_ua: bool,
        resume: bool,
        show_progress: bool,
    ) -> dict[str, Any]:
        with self._lock:
            if self._current_job_id is not None:
                raise RuntimeError(f"Another crawl job is currently running: {self._current_job_id}")

            now = datetime.now(timezone.utc)
            timestamp_str = now.strftime("%Y%m%d_%H%M%S")
            short_id = uuid.uuid4().hex[:6]
            job_id = f"job_{timestamp_str}_{short_id}"

            job_dir = settings.storage_path / job_id
            job_dir.mkdir(parents=True, exist_ok=True)

            job_data: dict[str, Any] = {
                "job_id": job_id,
                "status": "pending",
                "message": "Job created and queued for execution",
                "keyword": keyword,
                "max_articles": max_articles,
                "workers": workers,
                "lang": lang,
                "country": country,
                "timeout": timeout,
                "proxy": proxy,
                "rotate_ua": rotate_ua,
                "resume": resume,
                "show_progress": show_progress,
                "created_at": now.isoformat(),
                "started_at": None,
                "completed_at": None,
                "output_dir": str(job_dir),
                "excel_path": None,
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
                country,
                timeout,
                proxy,
                rotate_ua,
                resume,
                show_progress,
                job_dir,
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
        lang: str,
        country: str,
        timeout: int,
        proxy: str | None,
        rotate_ua: bool,
        resume: bool,
        show_progress: bool,
        output_dir: Path,
    ) -> None:
        job = self.get_job(job_id)
        if not job:
            return

        job["status"] = "running"
        job["message"] = "Crawling in progress..."
        job["started_at"] = datetime.now(timezone.utc).isoformat()
        self._save_job_state(job)

        try:
            result = crawl_google_news(
                keyword=keyword,
                max_articles=max_articles,
                output_dir=output_dir,
                workers=workers,
                lang=lang,
                country=country,
                timeout=timeout,
                proxy=proxy,
                rotate_ua=rotate_ua,
                resume=resume,
                show_progress=show_progress,
            )
            job["status"] = "completed"
            job["message"] = "Crawl job completed successfully"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["excel_path"] = result.get("xlsx")
            job["stats"] = result
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
