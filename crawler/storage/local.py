from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import orjson

from crawler.excel import append_to_master_excel, export_excel
from crawler.naming import generate_run_tag
from crawler.storage.base import BaseStorageBackend


class LocalStorageBackend(BaseStorageBackend):
    """
    Local storage backend: saves JSONL checkpoint, local images,
    exports standalone Excel, and optionally appends to news_master.xlsx.
    """

    def __init__(self, output_dir: str | Path | None = None) -> None:
        self.output_dir = Path(output_dir) if output_dir else Path("storage")
        self.images_dir = self.output_dir / "images"
        self.jsonl_path = self.output_dir / "articles.jsonl"
        self.tab_name = "Articles"
        self.safe_topic = "News"
        self._lock = threading.Lock()

    def init_session(self, job_id: str, keyword: str, output_dir: str | Path | None = None) -> None:
        self.safe_topic, default_run_tag = generate_run_tag(keyword)
        self.tab_name = default_run_tag

        if output_dir:
            out_p = Path(output_dir)
            # If user provided base directory like 'storage' or 'output', append run_tag subfolder
            if out_p.name in ("storage", "output", "outputs"):
                self.output_dir = out_p / default_run_tag
            else:
                self.output_dir = out_p
        else:
            self.output_dir = Path("storage") / default_run_tag

        self.images_dir = self.output_dir / "images"
        self.jsonl_path = self.output_dir / f"{self.tab_name}_articles.jsonl"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)

    def append_checkpoint(self, record: dict[str, Any]) -> None:
        rec = dict(record)
        if imgs := rec.get("saved_images"):
            rec["saved_images"] = [str(p) for p in imgs]
        line_bytes = orjson.dumps(rec) + b"\n"
        with self._lock:
            with open(self.jsonl_path, "ab") as f:
                f.write(line_bytes)

    def load_completed_checkpoint(self) -> dict[str, dict]:
        if not self.jsonl_path.exists():
            return {}
        completed: dict[str, dict] = {}
        with open(self.jsonl_path, "rb") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = orjson.loads(line)
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
        # 1. Export standalone Excel file in subfolder
        xlsx_name = f"{self.tab_name}_articles.xlsx"
        xlsx = export_excel(
            articles=articles,
            output_dir=self.output_dir,
            filename=xlsx_name,
            tab_name=self.tab_name,
            images_dir=self.images_dir,
        )

        # 2. Append worksheet to storage/news_master.xlsx as first tab (index=0)
        master_path = self.output_dir.parent / "news_master.xlsx"
        try:
            append_to_master_excel(
                articles=articles,
                master_path=master_path,
                tab_name=self.tab_name,
                images_dir=self.images_dir,
            )
        except Exception as e:
            print(f"[LocalStorage] Notice: Could not append to master excel: {e}")

        # 3. Export complete <topic>_articles.json
        json_path = self.output_dir / f"{self.tab_name}_articles.json"
        clean_articles = []
        for art in articles:
            item = dict(art)
            if imgs := item.get("saved_images"):
                item["saved_images"] = [str(p) for p in imgs]
            clean_articles.append(item)

        try:
            json_bytes = orjson.dumps(clean_articles, option=orjson.OPT_INDENT_2)
            with open(json_path, "wb") as f:
                f.write(json_bytes)
        except Exception as e:
            print(f"[LocalStorage] Warning: Failed to write {json_path}: {e}")

        return {
            "storage_mode": "local",
            "xlsx": str(xlsx),
            "master_xlsx": str(master_path),
            "json": str(json_path),
            "jsonl": str(self.jsonl_path),
            "output_dir": str(self.output_dir),
            "images_dir": str(self.images_dir),
            "tab_name": self.tab_name,
        }
