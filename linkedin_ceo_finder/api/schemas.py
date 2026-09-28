"""Pydantic schemas cho LinkedIn CEO Finder API."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class CEOLeadSchema(BaseModel):
    """Schema biểu diễn thông tin một Lead lãnh đạo / CEO."""

    name: str = Field(..., description="Họ và tên của CEO / Lãnh đạo")
    role: str = Field(..., description="Chức danh (CEO, Founder, Tổng Giám Đốc...)")
    keyword: str = Field(..., description="Từ khóa hoặc nguồn tên miền tìm kiếm")
    company: str = Field("N/A", description="Tên công ty")
    linkedin_link: str = Field("", description="Đường dẫn LinkedIn cá nhân")
    updated_at: str = Field(..., description="Thời gian cập nhật")


class DomainSearchRequest(BaseModel):
    """Request tìm kiếm CEO theo danh sách tên miền website."""

    domains: List[str] = Field(
        ...,
        min_length=1,
        description="Danh sách tên miền công ty (vd: ['google.com', 'nvidia.com'])",
        examples=[["google.com", "microsoft.com", "nvidia.com"]],
    )
    target_count: Optional[int] = Field(
        None,
        description="Số lượng CEO tối đa cần tìm (mặc định: lấy tất cả các domain hợp lệ)",
    )
    save_to_sheet: bool = Field(
        True,
        description="Tự động đồng bộ và lưu kết quả vào Google Sheet (mặc định True)",
    )
    max_workers: int = Field(
        5,
        ge=1,
        le=20,
        description="Số luồng chạy song song đồng thời",
    )
    sync: bool = Field(
        False,
        description="Nếu False (mặc định cho cron-job): Chạy nền và trả về ngay thông báo 'running'. Nếu True: Chờ quét xong và trả về kết quả.",
    )
    sheet_id: Optional[str] = Field(
        None,
        description="Tùy chọn ghi đè Google Sheet ID (nếu không dùng biến môi trường SHEET_CEO)",
    )
    worksheet_name: Optional[str] = Field(
        None,
        description="Tên tab worksheet cần lưu trong Google Sheet",
    )
    proxy: Optional[str] = Field(
        None,
        description="Tùy chọn proxy HTTP (nếu cần thay đổi)",
    )


class KeywordSearchRequest(BaseModel):
    """Request tìm kiếm CEO theo từ khóa ngành nghề (hỗ trợ cả từ khóa đơn lẻ lẫn danh sách nhiều từ khóa)."""

    keyword: Optional[str] = Field(
        None,
        description="Từ khóa đơn lẻ (vd: 'Fintech Vietnam', 'AI')",
        examples=["Fintech Vietnam"],
    )
    keywords: Optional[Union[List[str], str]] = Field(
        None,
        description="Danh sách nhiều từ khóa (vd: ['Fintech Vietnam', 'AI Vietnam']) hoặc chuỗi từ khóa",
        examples=[["Fintech Vietnam", "AI Vietnam"]],
    )
    target_count: int = Field(
        5,
        ge=1,
        le=50,
        description="Số lượng CEO mục tiêu cần tìm cho mỗi từ khóa",
    )
    max_workers: int = Field(
        5,
        ge=1,
        le=20,
        description="Số luồng chạy song song đồng thời khi có nhiều từ khóa",
    )
    save_to_sheet: bool = Field(
        True,
        description="Tự động đồng bộ và lưu kết quả vào Google Sheet (mặc định True)",
    )
    max_pages: int = Field(
        5,
        ge=1,
        le=20,
        description="Số trang tìm kiếm tối đa duyệt qua cho mỗi từ khóa",
    )
    skip_empty_company: bool = Field(
        False,
        description="Bỏ qua các kết quả không bóc tách được tên công ty",
    )
    sync: bool = Field(
        False,
        description="Nếu False (mặc định cho cron-job): Chạy nền và trả về ngay thông báo 'running'. Nếu True: Chờ quét xong và trả về kết quả.",
    )
    sheet_id: Optional[str] = Field(
        None,
        description="Tùy chọn ghi đè Google Sheet ID",
    )
    worksheet_name: Optional[str] = Field(
        None,
        description="Tên tab worksheet cần lưu",
    )
    proxy: Optional[str] = Field(
        None,
        description="Tùy chọn proxy HTTP",
    )

    def resolve_keywords(self) -> List[str]:
        """Chuẩn hóa danh sách từ khóa từ keyword hoặc keywords."""
        res: List[str] = []
        if self.keywords:
            if isinstance(self.keywords, str):
                res.extend([k.strip() for k in self.keywords.split(",") if k.strip()])
            elif isinstance(self.keywords, list):
                res.extend([str(k).strip() for k in self.keywords if str(k).strip()])
        if self.keyword and self.keyword.strip():
            kw = self.keyword.strip()
            if kw not in res:
                res.append(kw)
        if not res:
            res.append("Fintech Vietnam")
        return res


class CEOJobTriggerResponse(BaseModel):
    """Response thông báo job đang chạy ngầm trong nền (phù hợp cho cron-job)."""

    status: str = Field("running", description="Trạng thái tiến trình: running")
    message: str = Field(..., description="Thông báo kết quả tiếp nhận job")
    job_id: str = Field(..., description="Mã định danh job chạy ngầm")
    mode: str = Field(..., description="Chế độ tìm kiếm (domains hoặc keyword)")
    target: str = Field(..., description="Đối tượng tìm kiếm")
    save_to_sheet: bool = Field(..., description="Có lưu kết quả vào Google Sheet hay không")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CEOSearchResponse(BaseModel):
    """Response trả về kết quả tìm kiếm CEO (dành cho chế độ đồng bộ sync=True)."""

    success: bool = Field(True, description="Trạng thái thực thi")
    message: str = Field(..., description="Thông báo kết quả")
    total_found: int = Field(..., description="Tổng số CEO tìm được")
    leads: List[CEOLeadSchema] = Field(default_factory=list, description="Danh sách chi tiết CEO")
    sheet_saved: bool = Field(False, description="Đã lưu vào Google Sheet hay chưa")


class CEOHealthResponse(BaseModel):
    """Response kiểm tra sức khỏe và trạng thái cấu hình của module CEO Finder."""

    status: str = Field("ok", description="Trạng thái dịch vụ")
    service: str = Field("linkedin-ceo-finder", description="Tên dịch vụ")
    sheet_configured: bool = Field(..., description="Đã cấu hình Google Sheet ID hay chưa")
    service_account_configured: bool = Field(..., description="File Service Account credentials có tồn tại không")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
