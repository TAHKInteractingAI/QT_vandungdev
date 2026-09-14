from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import gspread
import orjson
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from crawler.naming import generate_run_tag, sanitize_tab_title
from crawler.sheet_schema import (
    COLUMN_SPECS,
    HEADERS,
    ROW_HEIGHT_PX,
)
from crawler.storage.base import BaseStorageBackend

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class GoogleCloudStorageBackend(BaseStorageBackend):
    """Google Cloud Storage backend: uploads images and JSON to Google Drive, appends rows to Google Sheets."""

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
        self.tab_name: str = "Crawler_Run"
        self.safe_topic: str = "News"
        self._lock = threading.Lock()
        self._drive_lock = threading.Lock()
        self._completed: dict[str, dict] = {}

    def _resolve_credentials(self, path: str | Path | None) -> tuple[Any, str | None]:
        root = Path(__file__).resolve().parents[2]

        # 1. Try OAuth 2.0 User Token from env var JSON string
        token_env = os.getenv("GOOGLE_TOKEN_JSON")
        if token_env:
            try:
                info = orjson.loads(token_env)
                creds = UserCredentials.from_authorized_user_info(info, scopes=_SCOPES)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                print("[GoogleStorage] Authenticated using OAuth 2.0 User Credentials from GOOGLE_TOKEN_JSON env var")
                return creds, "env:GOOGLE_TOKEN_JSON"
            except Exception as e:
                print(f"[GoogleStorage] Warning: Failed to load user token from GOOGLE_TOKEN_JSON: {e}")

        # 2. Try OAuth 2.0 User Token from files (including Render /etc/secrets/token.json)
        token_candidates = []
        if path and Path(path).name == "token.json":
            token_candidates.append(Path(path))
        token_candidates.append(root / "token.json")
        token_candidates.append(Path("token.json"))
        token_candidates.append(Path("/etc/secrets/token.json"))

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

        # 3. Try Service Account from env var JSON string
        sa_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if sa_env:
            try:
                info = orjson.loads(sa_env)
                creds = ServiceAccountCredentials.from_service_account_info(info, scopes=_SCOPES)
                print("[GoogleStorage] Authenticated using Service Account from GOOGLE_SERVICE_ACCOUNT_JSON env var")
                return creds, "env:GOOGLE_SERVICE_ACCOUNT_JSON"
            except Exception as e:
                print(f"[GoogleStorage] Warning: Failed to load service account from GOOGLE_SERVICE_ACCOUNT_JSON: {e}")

        # 4. Try Service Account from files
        resolved_sa_path: str | None = None
        if path and Path(path).exists() and Path(path).name != "token.json":
            resolved_sa_path = str(path)
        elif os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and Path(os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")).exists():
            resolved_sa_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        elif Path("/etc/secrets/service_account.json").exists():
            resolved_sa_path = "/etc/secrets/service_account.json"
        else:
            for pattern in ["service_account.json", "plucky-courier-*.json", "credentials*.json"]:
                matches = list(root.glob(pattern))
                if matches:
                    resolved_sa_path = str(matches[0])
                    break

        if not resolved_sa_path or not Path(resolved_sa_path).exists():
            raise FileNotFoundError(
                "Neither valid token.json (OAuth2 User) nor Service Account credentials JSON found. "
                "Run `python crawler/scripts/auth_google_drive.py`, upload secret file on Render, or provide service_account.json."
            )

        print(f"[GoogleStorage] Authenticated using Service Account: {resolved_sa_path}")
        creds = ServiceAccountCredentials.from_service_account_file(str(resolved_sa_path), scopes=_SCOPES)
        return creds, resolved_sa_path

    def init_session(
        self,
        job_id: str,
        keyword: str,
        output_dir: str | Path | None = None,
        tz: str | None = None,
    ) -> None:
        self.spreadsheet = self.gc.open_by_key(self.spreadsheet_id)

        self.safe_topic, default_run_tag = generate_run_tag(keyword, tz=tz)
        self.tab_name = default_run_tag

        # Insert new worksheet at index=0 (the very first tab on the left)
        try:
            self.worksheet = self.spreadsheet.add_worksheet(title=self.tab_name, rows=100, cols=12, index=0)
        except Exception:
            suffix = job_id[-4:] if len(job_id) >= 4 else "01"
            self.tab_name = sanitize_tab_title(f"{self.tab_name}_{suffix}")
            self.worksheet = self.spreadsheet.add_worksheet(title=self.tab_name, rows=100, cols=12, index=0)

        # Header row
        self.worksheet.append_row(HEADERS, value_input_option="USER_ENTERED")
        self.worksheet.format("A1:J1", {"textFormat": {"bold": True}})

        # Subfolder in Google Drive: <topic>_hhmm_ddmmyy
        folder_metadata = {
            "name": self.tab_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if self.drive_parent_folder_id:
            folder_metadata["parents"] = [self.drive_parent_folder_id]

        created_folder = self.drive_service.files().create(body=folder_metadata, fields="id").execute()
        self.job_folder_id = created_folder.get("id")

        # Local directory in storage/<topic>_hhmm_ddmmyy
        if output_dir:
            out_p = Path(output_dir)
            if out_p.name in ("storage", "output", "outputs"):
                self.output_dir = out_p / self.tab_name
            else:
                self.output_dir = out_p
        else:
            self.output_dir = Path("storage") / self.tab_name

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self.output_dir / f"{self.tab_name}_articles.json"
        self.jsonl_path = self.output_dir / f"{self.tab_name}_articles.jsonl"

    def append_checkpoint(self, record: dict[str, Any]) -> None:
        key = record.get("google_url") or record.get("url") or record.get("title")
        rec = dict(record)
        if imgs := rec.get("saved_images"):
            rec["saved_images"] = [str(p) for p in imgs]
        if key:
            with self._lock:
                self._completed[key] = rec
                if hasattr(self, "jsonl_path") and self.jsonl_path:
                    try:
                        line_bytes = orjson.dumps(rec) + b"\n"
                        with open(self.jsonl_path, "ab") as f:
                            f.write(line_bytes)
                    except Exception:
                        pass

    def load_completed_checkpoint(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._completed)

    def process_saved_images(self, image_paths: list[Path], article_id: str) -> list[str]:
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
                # Keep exact clean filename (e.g. Trillion_0001_01.jpg)
                file_metadata = {
                    "name": path_obj.name,
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

        sorted_articles = sorted(articles, key=lambda a: a.get("order", 0)) if any("order" in a for a in articles) else list(articles)

        rows_to_append: list[list[Any]] = []
        for i, art in enumerate(sorted_articles, 1):
            order_num = art.get("order", i)
            title = art.get("title", "")
            source = art.get("source", "")
            published = art.get("published", "")
            snippet = art.get("snippet", "")
            status = art.get("status", "ok")

            def _esc_formula_str(s: str) -> str:
                return (s or "").replace('"', '""')

            sep = ";" if any(loc in (getattr(self.spreadsheet, "locale", "") or "").lower() for loc in ["vi", "fr", "de", "es", "it", "nl", "pt", "ru"]) else ","

            g_url = art.get("google_url", "")
            engine_name = "Google News"
            g_formula = f'=HYPERLINK("{_esc_formula_str(g_url)}"{sep} "{engine_name}")' if g_url else ""

            pub_url = art.get("publisher_url", "")
            pub_formula = ""
            if pub_url:
                domain = urlparse(pub_url).netloc.lower()
                if domain.startswith("www."):
                    domain = domain[4:]
                label = _esc_formula_str(domain or "Trang nguồn")
                pub_formula = f'=HYPERLINK("{_esc_formula_str(pub_url)}"{sep} "{label}")'

            saved_images = art.get("saved_images", [])
            drive_img_url = str(saved_images[0]) if saved_images else ""
            original_image_urls = art.get("image_urls", [])
            original_img_url = str(original_image_urls[0]) if original_image_urls else ""

            preview_url = ""
            if drive_img_url and drive_img_url.startswith("http"):
                preview_url = drive_img_url
            elif original_img_url and original_img_url.startswith("http"):
                preview_url = original_img_url

            img_formula = f'=IMAGE("{_esc_formula_str(preview_url)}")' if preview_url else ""

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

            try:
                sheet_id = self.worksheet.id
                num_data_rows = len(rows_to_append)

                try:
                    self.worksheet.freeze(rows=1)
                except Exception:
                    pass

                try:
                    self.worksheet.set_basic_filter(f"A1:J{num_data_rows + 1}")
                except Exception:
                    pass

                requests = [
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": 1,
                                "endIndex": num_data_rows + 1,
                            },
                            "properties": {"pixelSize": ROW_HEIGHT_PX},
                            "fields": "pixelSize",
                        }
                    }
                ]

                for col_idx, spec in enumerate(COLUMN_SPECS):
                    requests.append({
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "startIndex": col_idx,
                                "endIndex": col_idx + 1,
                            },
                            "properties": {"pixelSize": spec["pixel_width"]},
                            "fields": "pixelSize",
                        }
                    })

                self.spreadsheet.batch_update({"requests": requests})

                self.worksheet.format(
                    f"A2:J{num_data_rows + 1}",
                    {
                        "wrapStrategy": "WRAP",
                        "verticalAlignment": "TOP",
                        "horizontalAlignment": "LEFT",
                    },
                )
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

        # 1. Save full JSON locally
        json_drive_link = None
        clean_articles = []
        for art in sorted_articles:
            item = dict(art)
            if imgs := item.get("saved_images"):
                item["saved_images"] = [str(p) for p in imgs]
            clean_articles.append(item)

        if hasattr(self, "json_path") and self.json_path:
            try:
                json_bytes = orjson.dumps(clean_articles, option=orjson.OPT_INDENT_2)
                with open(self.json_path, "wb") as f:
                    f.write(json_bytes)
            except Exception as e:
                print(f"[GoogleStorage] Warning: Failed to write {self.json_path}: {e}")

            # 2. Upload JSON to Google Drive into the SAME subfolder with images
            if self.json_path.exists() and self.job_folder_id:
                try:
                    media = MediaFileUpload(str(self.json_path), mimetype="application/json", resumable=False)
                    json_meta = {
                        "name": self.json_path.name,
                        "parents": [self.job_folder_id],
                    }
                    with self._drive_lock:
                        up_json = self.drive_service.files().create(
                            body=json_meta,
                            media_body=media,
                            fields="id, webViewLink",
                        ).execute()
                        json_file_id = up_json.get("id")
                        if json_file_id:
                            try:
                                self.drive_service.permissions().create(
                                    fileId=json_file_id,
                                    body={"type": "anyone", "role": "reader"},
                                ).execute()
                            except Exception:
                                pass
                            json_drive_link = f"https://drive.google.com/uc?export=view&id={json_file_id}"
                            print(f"[GoogleStorage] Uploaded JSON to Drive: {self.json_path.name}")
                except Exception as up_err:
                    print(f"[GoogleStorage] Warning: Failed to upload JSON to Google Drive: {up_err}")

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
            "tab_name": self.tab_name,
        }
        if json_drive_link:
            result["json_drive_url"] = json_drive_link
        if hasattr(self, "json_path") and self.json_path:
            result["json"] = str(self.json_path)
        if hasattr(self, "jsonl_path") and self.jsonl_path:
            result["jsonl"] = str(self.jsonl_path)
        return result
