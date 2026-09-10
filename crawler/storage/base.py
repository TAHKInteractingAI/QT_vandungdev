from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseStorageBackend(ABC):
    """Abstract interface for crawler storage backends."""

    @abstractmethod
    def init_session(self, job_id: str, keyword: str, output_dir: str | Path | None = None) -> None:
        """Initialize storage session resources (e.g. folders, spreadsheets)."""
        pass

    @abstractmethod
    def append_checkpoint(self, record: dict[str, Any]) -> None:
        """Persist a single processed article record for checkpointing."""
        pass

    @abstractmethod
    def load_completed_checkpoint(self) -> dict[str, dict]:
        """Load previously completed articles mapping (google_url -> record)."""
        pass

    @abstractmethod
    def process_saved_images(self, image_paths: list[Path], article_id: str) -> list[str | Path]:
        """Process local downloaded images (e.g. upload to Google Drive or keep local)."""
        pass

    @abstractmethod
    def finalize(self, articles: list[dict[str, Any]]) -> dict[str, Any]:
        """Finalize results and return destination metadata."""
        pass
