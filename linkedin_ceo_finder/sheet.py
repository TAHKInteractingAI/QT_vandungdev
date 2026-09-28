"""Thao tác tích hợp Google Sheet cho LinkedIn CEO Finder.

Bao gồm kết nối (Colab OAuth + Service Account fallback), làm đẹp giao diện bảng (formatting),
sắp xếp theo thời gian mới nhất (sorting & renumbering) và lưu trữ dữ liệu.
"""

from datetime import datetime
import json
import os
import re
from typing import Any, Dict, List, Optional, Set, Union
import gspread

from .config import (
    DEFAULT_SERVICE_ACCOUNT,
    DEFAULT_SHEET_ID,
    DEFAULT_WORKSHEET_NAME,
    IN_COLAB,
    SHEET_COL_WIDTHS,
    SHEET_HEADERS,
    get_sheet_id,
)
from .models import CEOLead


def format_sheet(ws: Any) -> None:
    """Làm đẹp bảng dữ liệu: Đóng băng tiêu đề, tô màu header navy, căn lề và chuẩn hóa kích thước 7 cột."""
    try:
        ws.freeze(rows=1)
        ws.format(
            "A1:G1",
            {
                "backgroundColor": {"red": 0.12, "green": 0.31, "blue": 0.47},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "textFormat": {
                    "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                    "bold": True,
                    "fontSize": 10,
                },
            },
        )
        last_row = len(ws.col_values(1))
        if last_row > 1:
            ws.format(
                f"A2:A{last_row}",
                {"horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"},
            )
            ws.format(
                f"G2:G{last_row}",
                {"horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"},
            )
            ws.format(f"B2:F{last_row}", {"verticalAlignment": "MIDDLE"})

        requests = [
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": ws.id,
                        "dimension": "COLUMNS",
                        "startIndex": i,
                        "endIndex": i + 1,
                    },
                    "properties": {"pixelSize": w},
                    "fields": "pixelSize",
                }
            }
            for i, w in enumerate(SHEET_COL_WIDTHS)
        ]
        ws.spreadsheet.batch_update({"requests": requests})
    except Exception as e:
        print(f"⚠️ Lưu ý khi format sheet: {e}")


def sort_and_renumber_sheet(ws: Any) -> None:
    """Sắp xếp toàn bộ dữ liệu theo Ngày Cập Nhật mới nhất lên đầu và đánh lại STT chuẩn."""
    try:
        all_vals = ws.get_all_values()
        if len(all_vals) <= 2:
            return
        data_rows = [r for r in all_vals[1:] if any(r)]
        # r[6] là Ngày Cập Nhật trong bảng 7 cột (mới nhất xếp trên cùng)
        data_rows.sort(key=lambda r: str(r[6] if len(r) > 6 else "") or "", reverse=True)
        for idx, r in enumerate(data_rows, start=1):
            r[0] = str(idx)
        ws.update(values=data_rows, range_name=f"A2:G{len(data_rows) + 1}")
    except Exception as e:
        print(f"⚠️ Lưu ý khi sắp xếp sheet: {e}")


def get_existing_sheet_ceos(ws: Any) -> Set[str]:
    """Lấy danh sách định danh (LinkedIn URL, slug, tên) của CEO đã có trong Google Sheet."""
    if not ws:
        return set()
    try:
        all_vals = ws.get_all_values()
        if len(all_vals) <= 1:
            return set()

        headers = [h.strip().lower() for h in all_vals[0]]
        li_idx = next((i for i, h in enumerate(headers) if "linkedin" in h), -1)
        name_idx = next(
            (i for i, h in enumerate(headers) if "name" in h or "tên" in h or "ceo" in h),
            -1,
        )

        seen = set()
        for row in all_vals[1:]:
            if li_idx != -1 and len(row) > li_idx and row[li_idx].strip():
                clean_url = row[li_idx].strip().split("?")[0].rstrip("/").lower()
                seen.add(clean_url)
                m = re.search(r"linkedin\.com/in/([^/]+)", clean_url, re.I)
                if m:
                    seen.add(m.group(1).lower())
            if name_idx != -1 and len(row) > name_idx and row[name_idx].strip():
                seen.add(row[name_idx].strip().lower())
        return seen
    except Exception as e:
        print(f"⚠️ Lỗi đọc CEO cũ từ Sheet: {e}")
        return set()


def connect_google_sheet(
    service_account_path: str = DEFAULT_SERVICE_ACCOUNT,
    sheet_id: str = DEFAULT_SHEET_ID,
    worksheet_name: str = DEFAULT_WORKSHEET_NAME,
) -> Optional[Any]:
    """Kết nối Google Sheet với cơ chế hỗ trợ Colab OAuth & fallback Service Account."""
    sid = sheet_id or get_sheet_id()
    if not sid:
        print("⚠️ Chưa cấu hình sheet_id hoặc biến môi trường SHEET_CEO / GOOGLE_SPREADSHEET_ID.")
        return None

    ws_name = worksheet_name or DEFAULT_WORKSHEET_NAME or "sheet1"
    sa_path = service_account_path or os.getenv(
        "GOOGLE_APPLICATION_CREDENTIALS", "service_account.json"
    )

    print("⏳ Xác thực Google Client...")
    gc = None
    if IN_COLAB:
        try:
            from google.colab import auth
            from google.auth import default

            auth.authenticate_user()
            creds, _ = default()
            gc = gspread.authorize(creds)
            print("✅ Colab OAuth: Thành công.")
        except Exception:
            pass

    # 1. Thử xác thực từ biến môi trường GOOGLE_SERVICE_ACCOUNT_JSON (chuỗi JSON trên Render / Cloud)
    if not gc and os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"):
        try:
            sa_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
            gc = gspread.service_account_from_dict(sa_info)
            print("✅ Service Account từ biến môi trường GOOGLE_SERVICE_ACCOUNT_JSON: Thành công.")
        except Exception as e:
            print(f"⚠️ Lỗi xác thực Service Account từ GOOGLE_SERVICE_ACCOUNT_JSON: {e}")

    # 2. Thử Render Secret File (/etc/secrets/service_account.json)
    if not gc and os.path.exists("/etc/secrets/service_account.json"):
        try:
            gc = gspread.service_account(filename="/etc/secrets/service_account.json")
            print("✅ Service Account từ Render Secret File (/etc/secrets/service_account.json): Thành công.")
        except Exception as e:
            print(f"⚠️ Lỗi xác thực Service Account từ Render Secret File: {e}")

    # 3. Thử từ file credentials cục bộ (sa_path)
    if not gc:
        if not os.path.exists(sa_path):
            print(f"❌ Không tìm thấy file credentials tại '{sa_path}' và không có biến GOOGLE_SERVICE_ACCOUNT_JSON.")
            return None
        try:
            gc = gspread.service_account(filename=sa_path)
            print(f"✅ Service Account: Thành công ({sa_path}).")
        except Exception as e:
            print(f"❌ Lỗi xác thực Service Account: {e}")
            return None

    try:
        sh = gc.open_by_key(sid)
        print(f"✅ Mở Spreadsheet: '{sh.title}'")
    except Exception as e:
        print(f"❌ Lỗi mở Spreadsheet ID '{sid[:6]}...': {e}")
        return None

    try:
        try:
            ws = sh.worksheet(ws_name)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=ws_name, rows=100, cols=10)
            print(f"✅ Đã tạo tab mới: '{ws_name}'")

        expected = SHEET_HEADERS
        all_vals = ws.get_all_values()
        if not all_vals:
            ws.update(values=[expected], range_name="A1")
            print("✅ Đã tạo tiêu đề (Headers) mới.")
        elif all_vals[0] != expected:
            print("🔄 Chuẩn hóa bảng sang cấu trúc 7 cột gọn gàng...")
            migrated = []
            for i, r in enumerate(all_vals[1:], start=1):
                if not any(r):
                    continue
                name = r[1] if len(r) > 1 else ""
                role = r[2] if len(r) > 2 else ""
                kw = r[3] if len(r) > 3 else ""
                comp = r[4] if len(r) > 4 else ""
                li = r[5] if len(r) > 5 else ""
                date_val = (
                    r[8]
                    if len(r) >= 9
                    else (
                        r[6]
                        if len(r) >= 7 and "-" in r[6]
                        else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )
                )
                migrated.append([str(i), name, role, kw, comp, li, date_val])
            ws.clear()
            ws.update(values=[expected] + migrated, range_name=f"A1:G{len(migrated) + 1}")
            print(f"✅ Đã đồng bộ {len(migrated)} dòng dữ liệu sang cấu trúc 7 cột.")

        sort_and_renumber_sheet(ws)
        format_sheet(ws)
        print(f"✅ Worksheet '{ws.title}' sẵn sàng ({ws.row_count} hàng, {ws.col_count} cột).")
        return ws
    except Exception as e:
        print(f"❌ Lỗi thao tác Worksheet '{ws_name}': {e}")
        return None


def save_leads_to_sheet(
    leads: List[Union[CEOLead, Dict[str, Any]]],
    worksheet: Optional[Any] = None,
    sheet_id: str = DEFAULT_SHEET_ID,
    worksheet_name: str = DEFAULT_WORKSHEET_NAME,
    service_account_path: str = DEFAULT_SERVICE_ACCOUNT,
) -> bool:
    """Lưu danh sách leads vào Google Sheet: Ngày cập nhật gần nhất luôn xếp trên cùng, STT liên tục (7 cột)."""
    if not leads:
        print("⚠️ Không có dữ liệu để lưu.")
        return False

    ws = worksheet or connect_google_sheet(
        service_account_path=service_account_path,
        sheet_id=sheet_id,
        worksheet_name=worksheet_name,
    )
    if not ws:
        print("❌ Không thể kết nối Google Sheet để lưu.")
        return False

    try:
        all_vals = ws.get_all_values()
        cols = ["name", "role", "keyword", "company", "linkedin_link"]

        # 1. Dữ liệu mới tìm được
        new_data = []
        for item in leads:
            l = item.to_dict() if isinstance(item, CEOLead) else item
            updated_at = l.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            link = l.get("linkedin_link") or l.get("url") or ""
            row_vals = [
                l.get("name", ""),
                l.get("role", ""),
                l.get("keyword", ""),
                l.get("company", ""),
                link,
                updated_at,
            ]
            new_data.append(row_vals)

        # 2. Dữ liệu hiện có trong Sheet (bỏ cột STT cũ)
        existing_data = []
        for r in all_vals[1:]:
            if any(r):
                row_info = list(r[1:7])
                while len(row_info) < 6:
                    row_info.append("")
                existing_data.append(row_info)

        # 3. Gộp và sắp xếp theo Ngày Cập Nhật mới nhất lên trên cùng (descending)
        combined = new_data + existing_data
        combined.sort(key=lambda r: str(r[-1] or ""), reverse=True)

        # 4. Gắn STT 1 -> N từ trên xuống dưới
        final_rows = [[i] + r for i, r in enumerate(combined, start=1)]

        # 5. Cập nhật vào Sheet và áp dụng định dạng 7 cột
        ws.update(values=final_rows, range_name=f"A2:G{len(final_rows) + 1}")
        format_sheet(ws)
        print(f"✅ Đã lưu {len(leads)} CEO mới (xếp mới nhất lên trên cùng, tổng cộng {len(final_rows)} dòng).")
        return True
    except Exception as e:
        print(f"❌ Lỗi ghi dữ liệu vào Sheet: {e}")
        return False
