"""LinkedIn CEO Finder Package.

Bộ công cụ tự động tìm kiếm thông tin CEO / Founder / Lãnh đạo cấp cao từ
danh sách tên miền website hoặc từ khóa ngành nghề, tích hợp đồng bộ Google Sheet.
"""

from .config import CEOConfig
from .core import CEOFinder, find_ceos_by_domains, find_ceos_by_keyword
from .models import CEOLead
from .network import http_get, unquote_yahoo_url
from .parser import is_duplicate_ceo, is_leadership_role, parse_linkedin_title, print_lead
from .searcher import (
    extract_ceo_from_website,
    search_ceo_for_domain,
    search_ceos_by_keyword,
)
from .sheet import (
    connect_google_sheet,
    format_sheet,
    get_existing_sheet_ceos,
    save_leads_to_sheet,
    sort_and_renumber_sheet,
)

__all__ = [
    "CEOFinder",
    "CEOConfig",
    "CEOLead",
    "find_ceos_by_domains",
    "find_ceos_by_keyword",
    "extract_ceo_from_website",
    "search_ceo_for_domain",
    "search_ceos_by_keyword",
    "parse_linkedin_title",
    "is_leadership_role",
    "is_duplicate_ceo",
    "print_lead",
    "connect_google_sheet",
    "format_sheet",
    "sort_and_renumber_sheet",
    "get_existing_sheet_ceos",
    "save_leads_to_sheet",
    "http_get",
    "unquote_yahoo_url",
]
