"""Thuật toán tìm kiếm CEO và bóc tách dữ liệu từ domain và từ khóa."""

import re
import time
import urllib.parse
from typing import List, Optional, Set

from .config import BRAND_MAP, CEO_KEYWORDS, DEFAULT_PROXY
from .models import CEOLead
from .network import http_get, unquote_yahoo_url
from .parser import is_duplicate_ceo, is_leadership_role, parse_linkedin_title, print_lead


def extract_ceo_from_website(
    domain: str,
    proxy: Optional[str] = DEFAULT_PROXY,
    seen_urls: Optional[Set[str]] = None,
) -> Optional[CEOLead]:
    """Quét nhanh trang Leadership/About của website công ty (giới hạn 3s/path)."""
    domain_clean = re.sub(r"^https?://(www\.)?", "", domain).strip("/").split("/")[0]
    if not domain_clean:
        return None

    quick_paths = ["/about", "/leadership", "/team"]
    for path in quick_paths:
        url = f"https://{domain_clean}{path}"
        tree = http_get(url, proxy=proxy, timeout=3)
        if not tree:
            continue

        for a in tree.css('a[href*="linkedin.com/in/"]'):
            m = re.search(
                r"(https?://[a-z]{0,3}\.?linkedin\.com/in/[a-zA-Z0-9_\-%]+)",
                a.attributes.get("href", ""),
                re.I,
            )
            if not m:
                continue
            clean_url = m.group(1).split("?")[0].rstrip("/")

            parent = a.parent
            for _ in range(3):
                parent = parent.parent if parent and parent.parent else parent

            context = parent.text(separator=" ", strip=True) if parent else ""
            text_lower = context.lower()
            for kw in CEO_KEYWORDS:
                if kw in text_lower:
                    lines = [l.strip() for l in context.splitlines() if l.strip()]
                    fallback_name = (
                        clean_url.split("/in/")[-1].replace("-", " ").title()
                    )
                    name = lines[0] if lines and len(lines[0]) <= 50 else fallback_name
                    if is_duplicate_ceo(clean_url, name, seen_urls):
                        continue
                    return CEOLead(
                        name=name,
                        role=kw.upper(),
                        keyword=f"Domain: {domain_clean}",
                        company=domain_clean,
                        linkedin_link=clean_url,
                    )
    return None


def search_ceo_for_domain(
    domain: str,
    proxy: Optional[str] = DEFAULT_PROXY,
    seen_urls: Optional[Set[str]] = None,
) -> Optional[CEOLead]:
    """THUẬT TOÁN TÌM CEO TÊN MIỀN ĐA TẦNG (Multi-Tier Executive Resolution):

    Giải quyết triệt để lỗi sai CEO các tập đoàn lớn (Google, Microsoft, Amazon, Nvidia, AMD...)
    Tầng 1: Executive Search - Xác thực danh tính CEO thực tế từ tri thức toàn cầu (tránh cựu CEO, CEO chi nhánh).
    Tầng 2: Targeted LinkedIn Lookup - Truy xuất chính xác URL LinkedIn của vị CEO đó.
    Tầng 3: Direct LinkedIn Query - Fallback cho các công ty vừa và nhỏ / chuyên biệt (như JetBrains).
    """
    dom_clean = re.sub(r"^https?://(www\.)?", "", domain).strip("/").split("/")[0]
    raw_brand = dom_clean.split(".")[0].title()
    brand_name = BRAND_MAP.get(raw_brand, raw_brand)

    # TẦNG 1: Truy vấn danh tính CEO thực tế từ cơ sở dữ liệu tri thức toàn cầu
    ceo_name = None
    q_exec = f'"current CEO of {brand_name}" OR "CEO of {brand_name}" OR "Chief Executive Officer of {brand_name}"'
    tree_exec = http_get(
        f"https://search.yahoo.com/search?p={urllib.parse.quote(q_exec)}",
        proxy=proxy,
        timeout=10,
    )
    if tree_exec:
        for li in tree_exec.css("div#web ol > li")[:4]:
            h3 = li.css_first("h3")
            desc = li.css_first("div.compText") or li.css_first("p")
            title_text = h3.text(strip=True) if h3 else ""
            snippet = desc.text(strip=True) if desc else ""
            full_text = f"{title_text}. {snippet}"

            # Tiêu đề Wikipedia cá nhân (vd: 'Sundar Pichai - Wikipedia', 'Satya Nadella - Wikipedia')
            m_wiki = re.search(
                r"^([A-ZÀ-Ỹ][a-zA-ZÀ-ỹ\.\s]{2,30})\s*[-–|]\s*Wikipedia",
                title_text,
            )
            if m_wiki and not any(
                k in m_wiki.group(1).lower()
                for k in ["list", "history", "criticism", brand_name.lower()]
            ):
                ceo_name = m_wiki.group(1).strip()
                break

            # '[Tên] is [the] President and CEO of [Thương hiệu]'
            m_ceo = re.search(
                r"([A-ZÀ-Ỹ][a-zA-ZÀ-ỹ\.\s]{2,30})\s+(?:is\s+(?:the\s+)?(?:President\s+and\s+)?(?:CEO|Chief Executive Officer)\s+of|là\s+Tổng\s+Giám\s+Đốc\s+của)\s+"
                + re.escape(brand_name),
                full_text,
                re.I,
            )
            if m_ceo:
                candidate = m_ceo.group(1).strip()
                if len(candidate.split()) <= 4 and not any(
                    w in candidate.lower() for w in ["who", "he", "she", "former", "why"]
                ):
                    ceo_name = candidate
                    break

            # '[Thương hiệu] CEO, [Tên]'
            m_ceo2 = re.search(
                re.escape(brand_name)
                + r"\s+CEO[,\s]+([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,3})",
                full_text,
                re.I,
            )
            if m_ceo2:
                ceo_name = m_ceo2.group(1).strip()
                break

    # Nếu Tầng 1 đã xác thực được danh tính CEO, tìm đúng LinkedIn URL của người đó
    if ceo_name:
        q_li = f'site:linkedin.com/in/ "{ceo_name}" "{brand_name}"'
        tree_li = http_get(
            f"https://search.yahoo.com/search?p={urllib.parse.quote(q_li)}",
            proxy=proxy,
            timeout=10,
        )
        if tree_li:
            for li in tree_li.css("div#web ol > li")[:3]:
                link_tag = li.css_first('a[href*="RU="]') or li.css_first(
                    'a[href*="linkedin.com"]'
                )
                if not link_tag:
                    continue
                clean_url = unquote_yahoo_url(link_tag.attributes.get("href", ""))
                if "linkedin.com/in/" in clean_url:
                    return CEOLead(
                        name=ceo_name,
                        role="CEO",
                        keyword=f"Domain: {dom_clean}",
                        company=brand_name,
                        linkedin_link=clean_url,
                    )

    # Direct LinkedIn Query (Fallback cho công ty vừa/nhỏ, chuyên biệt)
    q_dir = (
        f'site:linkedin.com/in/ ("CEO" OR "Chief Executive Officer" OR "Founder" OR "Tổng Giám Đốc") '
        f'("{dom_clean}" OR "{brand_name}") -intitle:former -intitle:ex -intitle:"ex-" '
        f"-intitle:assistant -intitle:intern"
    )
    tree_dir = http_get(
        f"https://search.yahoo.com/search?p={urllib.parse.quote(q_dir)}",
        proxy=proxy,
        timeout=12,
    )
    if tree_dir:
        for li in tree_dir.css("div#web ol > li")[:5]:
            h3 = li.css_first("h3")
            link_tag = li.css_first('a[href*="RU="]') or li.css_first(
                'a[href*="linkedin.com"]'
            )
            if not h3 or not link_tag:
                continue

            title_text = h3.text(strip=True)
            clean_url = unquote_yahoo_url(link_tag.attributes.get("href", ""))
            if "linkedin.com/in/" not in clean_url:
                continue

            desc_tag = li.css_first("div.compText") or li.css_first("p")
            snippet = desc_tag.text(strip=True) if desc_tag else ""

            name, role, company = parse_linkedin_title(title_text, snippet=snippet)
            if not name or not is_leadership_role(role):
                continue

            # Đảm bảo title hoặc snippet có liên quan đến thương hiệu
            if (
                brand_name.lower() not in title_text.lower()
                and dom_clean.lower() not in title_text.lower()
            ):
                continue

            comp_final = company if company not in ("", "N/A") else brand_name
            return CEOLead(
                name=name,
                role=role,
                keyword=f"Domain: {dom_clean}",
                company=comp_final,
                linkedin_link=clean_url,
            )

    return None


def search_ceos_by_keyword(
    keyword: str,
    target_count: int = 10,
    proxy: Optional[str] = DEFAULT_PROXY,
    seen_urls: Optional[Set[str]] = None,
    skip_empty_company: bool = False,
    max_pages: int = 10,
) -> List[CEOLead]:
    """Tìm kiếm CEO theo từ khóa qua Search Engine (xác thực chức danh nghiêm ngặt, tự động bỏ qua CEO cũ)."""
    seen_urls = seen_urls if seen_urls is not None else set()
    leads: List[CEOLead] = []
    page = 0

    while len(leads) < target_count and page < max_pages:
        offset = page * 7 + 1
        page += 1
        kw_parts = (
            " ".join(f'"{w}"' for w in keyword.strip().split() if len(w) > 1)
            if " " in keyword
            else f'"{keyword}"'
        )
        query = (
            f'site:linkedin.com/in/ ("CEO" OR "Chief Executive Officer" OR "Founder") '
            f'{kw_parts} -intitle:former -intitle:ex -intitle:"ex-" -intitle:assistant -intitle:intern'
        )
        url = f"https://search.yahoo.com/search?p={urllib.parse.quote(query)}&b={offset}"
        tree = http_get(url, proxy=proxy, timeout=12)
        if not tree:
            time.sleep(0.5)
            continue

        results = tree.css("div#web ol > li")
        if not results:
            time.sleep(0.5)
            continue

        for li in results:
            h3 = li.css_first("h3")
            link_tag = li.css_first('a[href*="RU="]') or li.css_first(
                'a[href*="linkedin.com"]'
            )
            if not h3 or not link_tag:
                continue

            title_text = h3.text(strip=True)
            clean_url = unquote_yahoo_url(link_tag.attributes.get("href", ""))
            if "linkedin.com/in/" not in clean_url or clean_url in seen_urls:
                continue

            desc_tag = li.css_first("div.compText") or li.css_first("p")
            snippet = desc_tag.text(strip=True) if desc_tag else ""

            name, role, company = parse_linkedin_title(title_text, snippet=snippet)

            if not name or len(name) <= 2 or not is_leadership_role(role):
                continue
            if skip_empty_company and company in ("", "N/A"):
                continue

            if is_duplicate_ceo(clean_url, name, seen_urls):
                print(
                    f"  ⏭️ Bỏ qua CEO đã có trong Sheet: {name} ({company}) -> Tiếp tục tìm CEO khác..."
                )
                continue

            seen_urls.add(clean_url)
            m = re.search(r"linkedin\.com/in/([^/]+)", clean_url, re.I)
            if m:
                seen_urls.add(m.group(1).lower())
            seen_urls.add(name.strip().lower())

            lead = CEOLead(
                name=name,
                role=role,
                keyword=keyword,
                company=company,
                linkedin_link=clean_url,
            )
            leads.append(lead)
            print_lead(lead, len(leads))
            if len(leads) >= target_count:
                break
        time.sleep(0.5)
    return leads
