"""Mô hình dữ liệu Lead cho LinkedIn CEO Finder."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import zoneinfo


def now_hcm_str() -> str:
    """Lấy thời gian hiện tại theo múi giờ Việt Nam (Asia/Ho_Chi_Minh, UTC+7)."""
    try:
        tz = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")
        return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class CEOLead:
    """Đại diện cho thông tin một Lead lãnh đạo / CEO tìm được."""

    name: str
    role: str
    keyword: str
    company: str = "N/A"
    linkedin_link: str = ""
    ai_status: str = "Chưa xác minh"
    updated_at: str = field(default_factory=now_hcm_str)

    @property
    def url(self) -> str:
        """Tương thích ngược với notebook cũ."""
        return self.linkedin_link

    def __getitem__(self, item: str) -> Any:
        """Hỗ trợ truy cập dạng từ điển lead['key']."""
        if item == "url":
            return self.linkedin_link
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        """Hỗ trợ dict-like get method."""
        try:
            return self[item]
        except AttributeError:
            return default

    def to_dict(self) -> Dict[str, Any]:
        """Chuyển đổi thành từ điển (dictionary)."""
        return {
            "name": self.name.strip(),
            "role": self.role.strip(),
            "keyword": self.keyword.strip(),
            "company": self.company.strip() or "N/A",
            "linkedin_link": self.linkedin_link.strip(),
            "ai_status": self.ai_status.strip() or "Chưa xác minh",
            "updated_at": self.updated_at,
            "url": self.linkedin_link.strip(),
        }

    def to_sheet_row(self, stt: Optional[int] = None) -> List[Any]:
        """Chuyển đổi thành hàng dữ liệu phù hợp với bảng 8 cột trên Google Sheet.

        Columns: [STT, CEO Name, Role / Title, Keyword, Company, LinkedIn URL, Xác Minh AI, Ngày Cập Nhật]
        """
        row = [
            self.name.strip(),
            self.role.strip(),
            self.keyword.strip(),
            self.company.strip() or "N/A",
            self.linkedin_link.strip(),
            self.ai_status.strip() or "Chưa xác minh",
            self.updated_at,
        ]
        if stt is not None:
            return [stt] + row
        return row

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CEOLead":
        """Khởi tạo từ dict."""
        return cls(
            name=data.get("name", "").strip(),
            role=data.get("role", "").strip(),
            keyword=data.get("keyword", "").strip(),
            company=data.get("company", "N/A").strip() or "N/A",
            linkedin_link=data.get("linkedin_link") or data.get("url") or "",
            ai_status=data.get("ai_status") or data.get("ai_verification") or "Chưa xác minh",
            updated_at=data.get("updated_at") or now_hcm_str(),
        )
