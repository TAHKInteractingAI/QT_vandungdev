"""Bóc tách dữ liệu, chuẩn hóa thông tin Lead và khử trùng lặp."""

import re
from typing import Any, Dict, Optional, Set, Tuple, Union

from .config import BAD_ROLE_PREFIXES, VALID_LEADERSHIP_ROLES
from .models import CEOLead


def is_leadership_role(role_text: Optional[str]) -> bool:
    """Kiểm tra role có phải là chức danh lãnh đạo cấp cao / CEO / Founder hợp lệ hay không.

    Parameters:
        role_text (str): Chuỗi chức danh cần kiểm tra.

    Returns:
        bool: True nếu là chức danh hợp lệ và hiện tại, False nếu là cựu nhân sự hoặc vai trò khác.
    """
    if not role_text:
        return False
    r_lower = role_text.lower()

    # Loại bỏ ngay nếu role chứa từ khóa quá khứ hoặc vị trí không phải lãnh đạo
    if any(b in r_lower for b in BAD_ROLE_PREFIXES):
        return False

    # Danh sách chức danh lãnh đạo hợp lệ
    return any(v in r_lower for v in VALID_LEADERSHIP_ROLES)


def parse_linkedin_title(title: str, snippet: str = "") -> Tuple[str, str, str]:
    """Bóc tách Họ tên, Chức vụ lãnh đạo và Công ty từ title và snippet kết quả tìm kiếm LinkedIn.

    Chỉ chấp nhận các chức danh lãnh đạo thực sự, loại bỏ các cựu nhân sự (ex-founder/ex-ceo).

    Parameters:
        title (str): Tiêu đề trang LinkedIn từ search engine.
        snippet (str): Đoạn trích dẫn mô tả đi kèm.

    Returns:
        Tuple[str, str, str]: (name, role, company)
    """
    clean = re.sub(r"\s*[\-|\-|\/|\|]\s*LinkedIn.*$", "", title, flags=re.IGNORECASE).strip()
    parts = [p.strip() for p in re.split(r"\s+[-–|]\s+", clean) if p.strip()]
    if not parts:
        return "", "", "N/A"

    name = parts[0]
    # Bỏ qua nếu tên có vẻ là chức danh hoặc quá dài
    if len(name.split()) > 7 or any(k in name.lower() for k in ["ceo", "founder", "hiring"]):
        name = ""

    role = ""
    company = ""

    # Duyệt qua các vế còn lại để tìm vế chứa chức danh lãnh đạo HIỆN TẠI
    for p in parts[1:]:
        p_lower = p.lower()
        if any(b in p_lower for b in BAD_ROLE_PREFIXES):
            continue

        # Tách role @ company (ưu tiên phân tách theo @, at, of)
        split_role = re.split(r"\s*(?:@|\bat\b|\bof\b)\s*", p, maxsplit=1, flags=re.I)
        candidate_role = split_role[0].strip()
        candidate_company = split_role[1].strip() if len(split_role) == 2 else ""

        if is_leadership_role(candidate_role):
            role = candidate_role
            if candidate_company:
                company = candidate_company
            break

    # Nếu chưa tìm thấy role lãnh đạo ở các vế ghép, kiểm tra các vế đơn lẻ
    if not role:
        for p in parts[1:]:
            if is_leadership_role(p):
                role = p
                break

    # Nếu vẫn không phải chức danh lãnh đạo, loại bỏ ngay ứng viên này
    if not is_leadership_role(role):
        return name, "", "N/A"

    # Bóc tách tên công ty từ snippet nếu tiêu đề chưa có
    if not company and snippet:
        m = re.search(
            r"(?:Experience:\s*([^·\n]+)|(?:at|of)\s+([A-Z0-9][a-zA-Z0-9\s\.\-]{2,30}))",
            snippet,
        )
        if m:
            company = (m.group(1) or m.group(2) or "").strip()

    if company:
        company = re.split(r"\s*[•|–—]\s*", company)[0].strip()
        company = re.sub(r"\.\.\.$", "", company).strip()

    return name, role, company or "N/A"


def is_duplicate_ceo(clean_url: str, name: str, seen_set: Optional[Set[str]]) -> bool:
    """Kiểm tra CEO đã tồn tại trong tập hợp (qua URL, username slug hoặc họ tên).

    Parameters:
        clean_url (str): Link LinkedIn đã chuẩn hóa.
        name (str): Tên CEO.
        seen_set (Set[str]): Tập hợp các định danh đã lưu.

    Returns:
        bool: True nếu đã tồn tại, False nếu chưa.
    """
    if not seen_set:
        return False
    norm_url = (clean_url or "").strip().split("?")[0].rstrip("/").lower()
    if norm_url and norm_url in seen_set:
        return True
    m = re.search(r"linkedin\.com/in/([^/]+)", norm_url, re.I)
    if m and m.group(1).lower() in seen_set:
        return True
    if name and name.strip().lower() in seen_set:
        return True
    return False


def make_lead(
    name: str,
    role: str,
    keyword: str,
    company: str,
    linkedin: str = "",
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Tạo dict lead tương thích hoàn toàn với notebook gốc."""
    lead = CEOLead(
        name=name,
        role=role,
        keyword=keyword,
        company=company,
        linkedin_link=linkedin,
    )
    if updated_at:
        lead.updated_at = updated_at
    return lead.to_dict()


def print_lead(lead: Union[CEOLead, Dict[str, Any]], index: int, prefix: str = "") -> None:
    """In log thông tin Lead tìm được một cách ngắn gọn, trực quan."""
    data = lead.to_dict() if isinstance(lead, CEOLead) else lead
    tag = f"[{prefix}] " if prefix else ""
    date_str = f" | {data.get('updated_at', '')}" if data.get("updated_at") else ""
    link = data.get("linkedin_link") or data.get("url") or "N/A"
    print(
        f" + [#{index}] {tag}{data.get('name')} | {data.get('role')} | "
        f"{data.get('company')} -> LinkedIn: {link}{date_str}"
    )
