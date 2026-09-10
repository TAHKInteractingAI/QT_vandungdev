from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from crawler.excel import export_excel
from crawler.storage.base import BaseStorageBackend


class LocalStorageBackend(BaseStorageBackend):
    """Local storage backend: saves JSONL checkpoint, local images, and exports Excel file."""

    def __init__(self, output_dir: str | Path = "output") -> None:
        self.output_dir = Path(output_dir)
        self.images_dir = self.output_dir / "images"
        self.jsonl_path = self.output_dir / "articles.jsonl"
        self._lock = threading.Lock()

    def init_session(self, job_id: str, keyword: str, output_dir: str | Path | None = None) -> None:
        if output_dir:
            self.output_dir = Path(output_dir)
            self.images_dir = self.output_dir / "images"
            self.jsonl_path = self.output_dir / "articles.jsonl"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)

    def append_checkpoint(self, record: dict[str, Any]) -> None:
        rec = dict(record)
        if imgs := rec.get("saved_images"):
            rec["saved_images"] = [str(p) for p in imgs]
        with self._lock:
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def load_completed_checkpoint(self) -> dict[str, dict]:
        if not self.jsonl_path.exists():
            return {}
        completed: dict[str, dict] = {}
        with open(self.jsonl_path, "r", encoding="utf-8") as f:
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

    def process_saved_images(self, image_paths: list[Path], article_id: str) -> list[str | Path]:
        # In local storage mode, keep local paths
        return [Path(p) for p in image_paths]

    def finalize(self, articles: list[dict[str, Any]]) -> dict[str, Any]:
        xlsx = export_excel(articles, self.output_dir)

        # Export complete articles.json
        json_path = self.output_dir / "articles.json"
        clean_articles = []
        for art in articles:
            item = dict(art)
            if imgs := item.get("saved_images"):
                item["saved_images"] = [str(p) for p in imgs]
            clean_articles.append(item)

        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(clean_articles, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[LocalStorage] Warning: Failed to write {json_path}: {e}")

        return {
            "storage_mode": "local",
            "xlsx": str(xlsx),
            "json": str(json_path),
            "jsonl": str(self.jsonl_path),
            "output_dir": str(self.output_dir),
            "images_dir": str(self.images_dir),
        }
