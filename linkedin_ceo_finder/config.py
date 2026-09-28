"""Cấu hình cho LinkedIn CEO Finder.

Hỗ trợ đọc biến môi trường từ file .env hoặc tham số truyền vào,
tự động nhận diện môi trường Google Colab / Local.
"""

from dataclasses import dataclass, field
import os
import sys
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

# Nhận diện Google Colab
IN_COLAB: bool = "google.colab" in sys.modules or os.path.exists("/content")


def get_default_proxy() -> Optional[str]:
    """Tìm proxy từ nhiều nguồn cấu hình khả dĩ (biến môi trường, crawler settings, Webshare)."""
    if IN_COLAB:
        return None

    # 1. Quét các tên biến môi trường phổ biến
    candidate_keys = [
        "DEFAULT_BACKBONE_PROXY",
        "DEFAULT_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "PROXY",
    ]
    for key in candidate_keys:
        val = os.getenv(key)
        if val and val.strip():
            proxy_str = val.strip()
            if not proxy_str.startswith(("http://", "https://", "socks5://", "socks5h://")):
                proxy_str = f"http://{proxy_str}"
            return proxy_str

    # 2. Thử lấy từ settings của crawler nếu có
    try:
        from crawler.api.config import settings
        val = getattr(settings, "DEFAULT_BACKBONE_PROXY", None) or getattr(settings, "DEFAULT_PROXY", None)
        if val and val.strip():
            proxy_str = val.strip()
            if not proxy_str.startswith(("http://", "https://", "socks5://", "socks5h://")):
                proxy_str = f"http://{proxy_str}"
            return proxy_str
    except Exception:
        pass

    # 3. Thử lấy từ Webshare ProxyManager nếu có API key
    try:
        from crawler.proxy_manager import ProxyManager
        pm = ProxyManager.get_instance()
        proxies = pm.fetch_active_proxies()
        if proxies:
            return proxies[0]
    except Exception:
        pass

    return None


# Cấu hình Google Sheet & Proxy mặc định
DEFAULT_SHEET_ID: str = os.getenv("SHEET_CEO", "")
DEFAULT_WORKSHEET_NAME: str = os.getenv("SHEET_CEO_WORKSHEET", "sheet1")
DEFAULT_SERVICE_ACCOUNT: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
DEFAULT_PROXY: Optional[str] = get_default_proxy()


# Đường dẫn leadership website công ty
LEADERSHIP_PATHS: List[str] = [
    "/leadership",
    "/team",
    "/about-us",
    "/about",
    "/our-team",
    "/board-of-directors",
    "/ban-lanh-dao",
    "/gioi-thieu",
    "/people",
    "/management",
]

# Từ khóa CEO / Founder
CEO_KEYWORDS: List[str] = [
    "ceo",
    "chief executive",
    "founder",
    "co-founder",
    "tổng giám đốc",
    "giám đốc điều hành",
    "chủ tịch",
]

# Các tiền tố chức danh không hợp lệ (cựu nhân sự, cố vấn, v.v.)
BAD_ROLE_PREFIXES: List[str] = [
    "ex-",
    "ex ",
    "former",
    "cựu",
    "previously",
    "past ",
    "advisor",
    "investor",
    "intern",
]

# Danh sách chức danh lãnh đạo cấp cao hợp lệ
VALID_LEADERSHIP_ROLES: List[str] = [
    "ceo",
    "chief executive",
    "founder",
    "co-founder",
    "cofounder",
    "tổng giám đốc",
    "giám đốc điều hành",
    "chủ tịch",
    "president",
    "managing director",
]

# Mapping thương hiệu lớn để tăng độ chính xác tìm kiếm
BRAND_MAP = {
    "Google": "Google",
    "Microsoft": "Microsoft",
    "Nvidia": "NVIDIA",
    "Amd": "AMD",
    "Amazon": "Amazon",
    "Jetbrains": "JetBrains",
    "Apple": "Apple",
    "Meta": "Meta",
    "Openai": "OpenAI",
    "Vng": "VNG",
    "Fpt": "FPT",
}

# Tiêu đề 7 cột Google Sheet chuẩn
SHEET_HEADERS: List[str] = [
    "STT",
    "CEO Name",
    "Role / Title",
    "Keyword",
    "Company",
    "LinkedIn URL",
    "Ngày Cập Nhật",
]

# Độ rộng cột tương ứng (pixel)
SHEET_COL_WIDTHS: List[int] = [55, 200, 220, 120, 200, 320, 160]


@dataclass
class CEOConfig:
    """Class cấu hình tập trung cho LinkedIn CEO Finder."""

    sheet_id: str = field(default_factory=lambda: DEFAULT_SHEET_ID)
    worksheet_name: str = field(default_factory=lambda: DEFAULT_WORKSHEET_NAME)
    service_account_path: str = field(default_factory=lambda: DEFAULT_SERVICE_ACCOUNT)
    proxy: Optional[str] = field(default_factory=lambda: DEFAULT_PROXY)
    max_workers: int = 5
    timeout: int = 12
    retries: int = 2
    in_colab: bool = field(default_factory=lambda: IN_COLAB)
