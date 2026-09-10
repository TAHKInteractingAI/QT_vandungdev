from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from crawler.storage.base import BaseStorageBackend

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_HEADERS = [
    "#",
    "Preview",
    "Title",
    "Snippet",
    "Published",
    "Source",
    "Google News URL",
    "Publisher URL",
    "Image",
    "Status",
]
# Exact column pixel widths requested:
# '#' = 45, 'Preview' = 145 (+20% for larger images), 'Title' = 300, 'Snippet' = 300, 'Published' = 150, 'Source' = 100,
# 'Google News URL' = 200, 'Publisher URL' = 200, 'Image' = 200, 'Status' = 200
_COL_PIXEL_WIDTHS = [
    45,   # Col A (1): '#'
    145,  # Col B (2): 'Preview'
    300,  # Col C (3): 'Title'
    300,  # Col D (4): 'Snippet'
    150,  # Col E (5): 'Published'
    100,  # Col F (6): 'Source'
    200,  # Col G (7): 'Google News URL'
    200,  # Col H (8): 'Publisher URL'
    200,  # Col I (9): 'Image'
    200,  # Col J (10): 'Status'
]


def _sanitize_tab_title(title: str) -> str:
    """Sanitize Google Sheets tab title (remove forbidden chars : / ? * [ ])"""
    cleaned = re.sub(r"[\:\/\?\*\[\]\\]", "_", title).strip()
    return cleaned[:90] if cleaned else "Crawler_Run"


class GoogleCloudStorageBackend(BaseStorageBackend):
    """Google Cloud Storage backend: uploads images to Google Drive and appends rows to Google Sheets."""

    def __init__(
        self,
        credentials_path: str | Path | None = None,
        spreadsheet_id: str | None = None,
        drive_parent_folder_id: str | None = None,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id or os.getenv("GOOGLE_SPREADSHEET_ID")
        self.drive_parent_folder_id = drive_parent_folder_id or os.getenv("GOOGLE_DRIVE_PARENT_FOLDER_ID")

        if not self.spreadsheet_id:
            raise ValueError("GOOGLE_SPREADSHEET_ID is required for GoogleCloudStorageBackend")

        self.creds, self.credentials_path = self._resolve_credentials(credentials_path)
        self.drive_service = build("drive", "v3", credentials=self.creds)
        self.gc = gspread.authorize(self.creds)

        self.spreadsheet = None
        self.worksheet = None
        self.job_folder_id: str | None = None
        self._lock = threading.Lock()
        self._drive_lock = threading.Lock()
        self._completed: dict[str, dict] = {}

    def _resolve_credentials(self, path: str | Path | None) -> tuple[Any, str | None]:
        """
        Resolves credentials by checking:
        1. OAuth 2.0 User token (token.json) for individual drive quota.
        2. Provided credentials_path (service account JSON or user token JSON).
        3. Environment variable GOOGLE_APPLICATION_CREDENTIALS.
        4. Workspace root for plucky-courier-*.json, service_account.json, or credentials*.json.
        """
        root = Path(__file__).resolve().parents[2]

        # 1. Priority: check token.json in workspace root or specified path
        token_candidates = []
        if path and Path(path).name == "token.json":
            token_candidates.append(Path(path))
        token_candidates.append(root / "token.json")
        token_candidates.append(Path("token.json"))

        for tok_path in token_candidates:
            if tok_path.exists():
                try:
                    creds = UserCredentials.from_authorized_user_file(str(tok_path), scopes=_SCOPES)
                    if creds and creds.expired and creds.refresh_token:
                        creds.refresh(Request())
                    print(f"[GoogleStorage] Authenticated using OAuth 2.0 User Credentials: {tok_path}")
                    return creds, str(tok_path)
                except Exception as e:
                    print(f"[GoogleStorage] Warning: Failed to load user token from {tok_path}: {e}")

        # 2. Fallback: Service Account credentials
        resolved_sa_path: str | None = None
        if path and Path(path).exists() and Path(path).name != "token.json":
            resolved_sa_path = str(path)
        elif os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and Path(os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")).exists():
            resolved_sa_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        else:
            for pattern in ["service_account.json", "plucky-courier-*.json", "credentials*.json"]:
                matches = list(root.glob(pattern))
                if matches:
                    resolved_sa_path = str(matches[0])
                    break

        if not resolved_sa_path or not Path(resolved_sa_path).exists():
            raise FileNotFoundError(
                "Neither valid token.json (OAuth2 User) nor Service Account credentials JSON found. "
                "Run `python scripts/auth_google_drive.py` or provide service_account.json."
            )

        print(f"[GoogleStorage] Authenticated using Service Account: {resolved_sa_path}")
        creds = ServiceAccountCredentials.from_service_account_file(str(resolved_sa_path), scopes=_SCOPES)
        return creds, resolved_sa_path

    def init_session(self, job_id: str, keyword: str, output_dir: str | Path | None = None) -> None:
        # 1. Connect to Spreadsheet
        self.spreadsheet = self.gc.open_by_key(self.spreadsheet_id)

        # 2. Format tab name and folder name as <chủ đề>_hhmm_ddmmyyyy
        now = datetime.now()
        time_suffix = now.strftime("%H%M_%d%m%Y")
        safe_keyword = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in keyword.strip())
        safe_keyword = safe_keyword.strip("_") or "News"
        tab_name = _sanitize_tab_title(f"{safe_keyword}_{time_suffix}")

        try:
            self.worksheet = self.spreadsheet.add_worksheet(title=tab_name, rows=100, cols=12)
        except Exception:
            # If tab name exists, add random suffix from job_id
            tab_name = _sanitize_tab_title(f"{tab_name}_{job_id[-4:]}")
            self.worksheet = self.spreadsheet.add_worksheet(title=tab_name, rows=100, cols=12)

        # 3. Add & format header row in Sheet
        self.worksheet.append_row(_HEADERS, value_input_option="USER_ENTERED")
        self.worksheet.format("A1:J1", {"textFormat": {"bold": True}})

        # 4. Create dedicated subfolder in Google Drive for job images (<chủ đề>_hhmm_ddmmyyyy)
        folder_metadata = {
            "name": tab_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if self.drive_parent_folder_id:
            folder_metadata["parents"] = [self.drive_parent_folder_id]

        created_folder = self.drive_service.files().create(body=folder_metadata, fields="id").execute()
        self.job_folder_id = created_folder.get("id")

        # 5. Local directory for JSON checkpoints / exports
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = Path("storage/outputs") / tab_name
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self.output_dir / "articles.json"
        self.jsonl_path = self.output_dir / "articles.jsonl"

    def append_checkpoint(self, record: dict[str, Any]) -> None:
        key = record.get("google_url") or record.get("url") or record.get("title")
        rec = dict(record)
        if imgs := rec.get("saved_images"):
            rec["saved_images"] = [str(p) for p in imgs]
        if key:
            with self._lock:
                self._completed[key] = rec
                # Persist to local JSONL checkpoint as well
                if hasattr(self, "jsonl_path") and self.jsonl_path:
                    try:
                        with open(self.jsonl_path, "a", encoding="utf-8") as f:
                            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    except Exception:
                        pass

    def load_completed_checkpoint(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._completed)

    def process_saved_images(self, image_paths: list[Path], article_id: str) -> list[str]:
        """Upload local downloaded image files to Google Drive, set public read, return direct link."""
        uploaded_urls: list[str] = []
        for img_path in image_paths:
            path_obj = Path(img_path)
            if not path_obj.exists():
                continue

            ext = path_obj.suffix.lower()
            mime_type = "image/jpeg"
            if ext in (".png",):
                mime_type = "image/png"
            elif ext in (".webp",):
                mime_type = "image/webp"
            elif ext in (".gif",):
                mime_type = "image/gif"

            try:
                media = MediaFileUpload(str(path_obj), mimetype=mime_type, resumable=False)
                file_metadata = {
                    "name": f"{article_id}_{path_obj.name}",
                    "parents": [self.job_folder_id] if self.job_folder_id else [],
                }
                with self._drive_lock:
                    up_file = self.drive_service.files().create(
                        body=file_metadata,
                        media_body=media,
                        fields="id, webViewLink",
                    ).execute()

                    file_id = up_file.get("id")
                    if file_id:
                        # Grant public read permission so =IMAGE() function in Google Sheets can render it
                        try:
                            self.drive_service.permissions().create(
                                fileId=file_id,
                                body={"type": "anyone", "role": "reader"},
                            ).execute()
                        except Exception:
                            pass

                if file_id:
                    direct_link = f"https://drive.google.com/uc?export=view&id={file_id}"
                    uploaded_urls.append(direct_link)
            except Exception as err:
                print(f"[GoogleStorage] Image upload failed for {img_path}: {err}")

        return uploaded_urls

    def finalize(self, articles: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.worksheet:
            raise RuntimeError("Google Worksheet has not been initialized.")

        # Sort articles consistently by order
        sorted_articles = sorted(articles, key=lambda a: a.get("order", 0)) if any("order" in a for a in articles) else list(articles)

        rows_to_append: list[list[Any]] = []
        for i, art in enumerate(sorted_articles, 1):
            order_num = art.get("order", i)
            title = art.get("title", "")
            source = art.get("source", "")
            published = art.get("published", "")
            snippet = art.get("snippet", "")
            status = art.get("status", "ok")

            # Helper to escape quotes for Sheets formulas
            def _esc_formula_str(s: str) -> str:
                return (s or "").replace('"', '""')

            # Formula separator depends on Google Sheet locale (vi_VN uses ;, en_US uses ,)
            sep = ";" if any(loc in (getattr(self.spreadsheet, "locale", "") or "").lower() for loc in ["vi", "fr", "de", "es", "it", "nl", "pt", "ru"]) else ","

            # Google News URL formula
            g_url = art.get("google_url", "")
            g_formula = f'=HYPERLINK("{_esc_formula_str(g_url)}"{sep} "Google News")' if g_url else ""

            # Publisher URL formula
            pub_url = art.get("publisher_url", "")
            pub_formula = ""
            if pub_url:
                domain = urlparse(pub_url).netloc.lower()
                if domain.startswith("www."):
                    domain = domain[4:]
                label = _esc_formula_str(domain or "Trang nguồn")
                pub_formula = f'=HYPERLINK("{_esc_formula_str(pub_url)}"{sep} "{label}")'

            # Drive Image & =IMAGE(...) preview formula with original CDN fallback
            saved_images = art.get("saved_images", [])
            drive_img_url = str(saved_images[0]) if saved_images else ""
            original_image_urls = art.get("image_urls", [])
            original_img_url = str(original_image_urls[0]) if original_image_urls else ""

            # Determine preview URL: prefer drive_img_url if uploaded, else fallback to original CDN URL
            preview_url = ""
            if drive_img_url and drive_img_url.startswith("http"):
                preview_url = drive_img_url
            elif original_img_url and original_img_url.startswith("http"):
                preview_url = original_img_url

            img_formula = f'=IMAGE("{_esc_formula_str(preview_url)}")' if preview_url else ""
            
            # Drive link formula
            drive_link_formula = ""
            if drive_img_url and drive_img_url.startswith("http"):
                drive_link_formula = f'=HYPERLINK("{_esc_formula_str(drive_img_url)}"{sep} "Xem ảnh Drive")'
            elif self.job_folder_id:
                folder_url = f"https://drive.google.com/drive/folders/{self.job_folder_id}"
                drive_link_formula = f'=HYPERLINK("{_esc_formula_str(folder_url)}"{sep} "Thư mục Drive")'

            rows_to_append.append([
                order_num,
                img_formula,
                title,
                snippet,
                published,
                source,
                g_formula,
                pub_formula,
                drive_link_formula,
                status,
            ])

        if rows_to_append:
            self.worksheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")

            # Format styling & resize dimensions matching crawler/excel.py exactly
            try:
                sheet_id = self.worksheet.id
                num_data_rows = len(rows_to_append)

                # 1. Freeze top row (A2 freeze_panes equivalent)
                try:
                    self.worksheet.freeze(rows=1)
                except Exception:
                    pass

                # 2. Auto filter on header row A1:J{num_data_rows+1} (auto_filter equivalent)
                try:
                    self.worksheet.set_basic_filter(f"A1:J{num_data_rows + 1}")
                except Exception:
                    pass

                # 3. Dimension properties batch_update: Row height (86px, enlarged for preview images) + exact 10 column widths
                requests = [
                    # Set row height for data rows (startIndex 1 to num_data_rows + 1) to 86 pixels (increased by 20%)
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": 1,
                                "endIndex": num_data_rows + 1,
                            },
                            "properties": {"pixelSize": 86},
                            "fields": "pixelSize",
                        }
                    }
                ]

                # Add column widths for all 10 columns matching _COL_PIXEL_WIDTHS
                for col_idx, pixel_w in enumerate(_COL_PIXEL_WIDTHS):
                    requests.append({
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "startIndex": col_idx,
                                "endIndex": col_idx + 1,
                            },
                            "properties": {"pixelSize": pixel_w},
                            "fields": "pixelSize",
                        }
                    })

                self.spreadsheet.batch_update({"requests": requests})

                # 4. Alignments matching crawler/excel.py:
                # - Text columns: wrap_text=True, vertical='top', horizontal='left'
                self.worksheet.format(
                    f"A2:J{num_data_rows + 1}",
                    {
                        "wrapStrategy": "WRAP",
                        "verticalAlignment": "TOP",
                        "horizontalAlignment": "LEFT",
                    },
                )

                # - Column '#' (Col A / 1) and 'Preview' (Col B / 2): vertical='top', horizontal='center'
                self.worksheet.format(
                    f"A2:A{num_data_rows + 1}",
                    {
                        "verticalAlignment": "TOP",
                        "horizontalAlignment": "CENTER",
                    },
                )
                self.worksheet.format(
                    f"B2:B{num_data_rows + 1}",
                    {
                        "verticalAlignment": "TOP",
                        "horizontalAlignment": "CENTER",
                    },
                )
            except Exception as dim_err:
                print(f"[GoogleStorage] Notice: Could not adjust sheet dimensions: {dim_err}")

        # Persist full articles.json locally as well
        if hasattr(self, "json_path") and self.json_path:
            clean_articles = []
            for art in sorted_articles:
                item = dict(art)
                if imgs := item.get("saved_images"):
                    item["saved_images"] = [str(p) for p in imgs]
                clean_articles.append(item)
            try:
                with open(self.json_path, "w", encoding="utf-8") as f:
                    json.dump(clean_articles, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[GoogleStorage] Warning: Failed to write {self.json_path}: {e}")

        sheet_url = f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}/edit#gid={self.worksheet.id}"
        drive_folder_url = f"https://drive.google.com/drive/folders/{self.job_folder_id}" if self.job_folder_id else ""

        print(f"[GoogleStorage] Done! Updated Google Sheet: {sheet_url}")
        if drive_folder_url:
            print(f"[GoogleStorage] Uploaded images to Google Drive: {drive_folder_url}")

        result: dict[str, Any] = {
            "storage_mode": "google",
            "spreadsheet_id": self.spreadsheet_id,
            "spreadsheet_url": sheet_url,
            "worksheet_id": self.worksheet.id,
            "worksheet_title": self.worksheet.title,
            "drive_folder_id": self.job_folder_id,
            "drive_folder_url": drive_folder_url,
        }
        if hasattr(self, "json_path") and self.json_path:
            result["json"] = str(self.json_path)
        if hasattr(self, "jsonl_path") and self.jsonl_path:
            result["jsonl"] = str(self.jsonl_path)
        return result
