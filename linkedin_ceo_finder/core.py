"""Module điều phối chính (Core Coordinator) cho LinkedIn CEO Finder.

Hỗ trợ tìm kiếm song song theo tên miền (Multi-Tier Resolution) và từ khóa ngành nghề.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import time
from typing import List, Optional, Set, Union

from .config import (
    CEOConfig,
    DEFAULT_PROXY,
    DEFAULT_SERVICE_ACCOUNT,
    DEFAULT_SHEET_ID,
    DEFAULT_WORKSHEET_NAME,
    get_default_proxy,
)
from .models import CEOLead
from .network import _mask_proxy
from .parser import is_duplicate_ceo, print_lead
from .searcher import (
    extract_ceo_from_website,
    search_ceo_for_domain,
    search_ceos_by_keyword,
)
from .sheet import connect_google_sheet, get_existing_sheet_ceos, save_leads_to_sheet


class CEOFinder:
    """Class điều phối toàn diện cho quá trình tìm kiếm CEO / Lãnh đạo."""

    def __init__(self, config: Optional[CEOConfig] = None):
        self.config = config or CEOConfig()

    def find_by_domains(
        self,
        company_domains: Union[List[str], str],
        target_count: Optional[int] = None,
        save_to_sheet: bool = True,
        max_workers: Optional[int] = None,
        sheet_id: Optional[str] = None,
        worksheet_name: Optional[str] = None,
        proxy: Optional[str] = None,
        service_account_path: Optional[str] = None,
    ) -> List[CEOLead]:
        """Tìm kiếm CEO theo danh sách tên miền."""
        return find_ceos_by_domains(
            company_domains=company_domains,
            target_count=target_count,
            save_to_sheet=save_to_sheet,
            max_workers=max_workers or self.config.max_workers,
            sheet_id=sheet_id or self.config.sheet_id,
            worksheet_name=worksheet_name or self.config.worksheet_name,
            proxy=proxy if proxy is not None else self.config.proxy,
            service_account_path=service_account_path or self.config.service_account_path,
        )

    def find_by_keyword(
        self,
        keyword: Optional[str] = None,
        keywords: Optional[Union[List[str], str]] = None,
        target_count: int = 10,
        save_to_sheet: bool = True,
        max_workers: Optional[int] = None,
        sheet_id: Optional[str] = None,
        worksheet_name: Optional[str] = None,
        proxy: Optional[str] = None,
        service_account_path: Optional[str] = None,
        skip_empty_company: bool = False,
        max_pages: int = 10,
    ) -> List[CEOLead]:
        """Tìm kiếm CEO theo từ khóa ngành nghề (hỗ trợ cả từ khóa đơn lẻ lẫn danh sách)."""
        return find_ceos_by_keyword(
            keyword=keyword,
            keywords=keywords,
            target_count=target_count,
            save_to_sheet=save_to_sheet,
            max_workers=max_workers or self.config.max_workers,
            sheet_id=sheet_id or self.config.sheet_id,
            worksheet_name=worksheet_name or self.config.worksheet_name,
            proxy=proxy if proxy is not None else self.config.proxy,
            service_account_path=service_account_path or self.config.service_account_path,
            skip_empty_company=skip_empty_company,
            max_pages=max_pages,
        )


def find_ceos_by_domains(
    company_domains: Union[List[str], str],
    target_count: Optional[int] = None,
    save_to_sheet: bool = True,
    max_workers: int = 5,
    sheet_id: str = DEFAULT_SHEET_ID,
    worksheet_name: str = DEFAULT_WORKSHEET_NAME,
    proxy: Optional[str] = DEFAULT_PROXY,
    service_account_path: str = DEFAULT_SERVICE_ACCOUNT,
) -> List[CEOLead]:
    """Tìm kiếm CEO từ danh sách tên miền website công ty cụ thể theo cơ chế SONG SONG.

    Áp dụng thuật toán đa tầng (Multi-tier Resolution):
    - Tự động nhận diện chính xác CEO của các tập đoàn lớn (Google, Microsoft, Amazon, Nvidia, AMD...).
    - Hỗ trợ quét nhanh trang web đối với công ty vừa/nhỏ.

    Parameters:
        company_domains (list | str): Danh sách hoặc 1 tên miền (vd: ['https://www.google.com', 'nvidia.com'])
        target_count (int, optional): Số lượng CEO tối đa cần lấy (mặc định: lấy hết các domain hợp lệ)
        save_to_sheet (bool): Tự động lưu kết quả vào Google Sheet (mặc định: True)
        max_workers (int): Số luồng chạy song song đồng thời (mặc định: 5 luồng)
        sheet_id (str): ID của Google Sheet
        worksheet_name (str): Tên tab sheet cần lưu
        proxy (str): Proxy HTTP để cào dữ liệu
        service_account_path (str): Đường dẫn credentials Service Account

    Returns:
        List[CEOLead]: Danh sách leads CEO tìm được theo tên miền
    """
    if isinstance(company_domains, str):
        company_domains = [company_domains]

    # Làm sạch danh sách domain và loại bỏ trùng lặp đầu vào
    clean_domains = []
    seen_dom_set = set()
    for d in company_domains:
        d_clean = re.sub(r"^https?://(www\.)?", "", d).strip("/").split("/")[0]
        if d_clean and d_clean.lower() not in seen_dom_set:
            seen_dom_set.add(d_clean.lower())
            clean_domains.append(d_clean)

    if not clean_domains:
        print("⚠️ Không có tên miền hợp lệ để tìm kiếm.")
        return []

    effective_proxy = proxy or get_default_proxy()
    print(
        f"\n🌐 BẮT ĐẦU TÌM KIẾM CEO SONG SONG [Số lượng website: {len(clean_domains)} | Số luồng: {max_workers} | Proxy: {_mask_proxy(effective_proxy)}]"
    )
    leads: List[CEOLead] = []
    seen_urls: Set[str] = set()

    # 1. Tải trước danh sách CEO trong Google Sheet để tránh trùng lặp
    ws = None
    if save_to_sheet:
        ws = connect_google_sheet(
            service_account_path=service_account_path,
            sheet_id=sheet_id,
            worksheet_name=worksheet_name,
        )
        if ws:
            sheet_ceos = get_existing_sheet_ceos(ws)
            seen_urls.update(sheet_ceos)
            if sheet_ceos:
                print(
                    f"📋 Đã tải {len(sheet_ceos)} định danh CEO từ Sheet để bỏ qua CEO trùng lặp."
                )

    # 2. Định nghĩa hàm xử lý cho 1 domain với thuật toán đa tầng
    def _fetch_ceo_for_domain(idx: int, dom: str):
        # Giãn nhẹ giữa các luồng để tránh nghẽn request Yahoo
        time.sleep(idx * 0.15)
        # Bước 2.1: Thuật toán Executive Search & Targeted LinkedIn Lookup (Độ chính xác cao nhất)
        res = search_ceo_for_domain(dom, proxy=effective_proxy, seen_urls=seen_urls)
        # Bước 2.2: Fallback quét trực tiếp website nếu chưa tìm thấy
        if not res:
            res = extract_ceo_from_website(dom, proxy=effective_proxy, seen_urls=seen_urls)
        return dom, res

    # 3. Chạy song song qua ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_dom = {
            executor.submit(_fetch_ceo_for_domain, i, dom): dom
            for i, dom in enumerate(clean_domains)
        }
        for future in as_completed(future_to_dom):
            dom = future_to_dom[future]
            try:
                domain_name, res = future.result()
                if not res:
                    print(f"  ⚠️ Chưa tìm thấy thông tin CEO phù hợp cho: {domain_name}")
                    continue

                if is_duplicate_ceo(res.linkedin_link, res.name, seen_urls):
                    print(f"  ⏭️ Đã có trong Sheet: {res.name} ({domain_name}) -> Bỏ qua.")
                    continue

                # Cập nhật seen_urls
                seen_urls.add(res.linkedin_link)
                m = re.search(r"linkedin\.com/in/([^/]+)", res.linkedin_link, re.I)
                if m:
                    seen_urls.add(m.group(1).lower())
                seen_urls.add(res.name.strip().lower())

                leads.append(res)
                print_lead(res, len(leads), prefix="Domain")

                if target_count and len(leads) >= target_count:
                    print(f"🎯 Đã đạt đủ số lượng mục tiêu: {target_count} CEO.")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
            except Exception as e:
                print(f"  ❌ Lỗi khi quét {dom}: {e}")

    print(f"\n🎯 Tổng cộng tìm thấy: {len(leads)} CEO từ tên miền.")

    # 4. Lưu vào Sheet nếu được yêu cầu
    if save_to_sheet and leads:
        save_leads_to_sheet(
            leads,
            worksheet=ws,
            sheet_id=sheet_id,
            worksheet_name=worksheet_name,
            service_account_path=service_account_path,
        )

    return leads


def find_ceos_by_keyword(
    keyword: Optional[str] = None,
    keywords: Optional[Union[List[str], str]] = None,
    target_count: int = 10,
    save_to_sheet: bool = True,
    max_workers: int = 5,
    sheet_id: str = DEFAULT_SHEET_ID,
    worksheet_name: str = DEFAULT_WORKSHEET_NAME,
    proxy: Optional[str] = DEFAULT_PROXY,
    service_account_path: str = DEFAULT_SERVICE_ACCOUNT,
    skip_empty_company: bool = False,
    max_pages: int = 10,
) -> List[CEOLead]:
    """Tìm kiếm CEO theo từ khóa ngành nghề / vị trí (vd: 'Fintech', 'AI Vietnam').

    Hỗ trợ cả 1 từ khóa (keyword) hoặc danh sách nhiều từ khóa (keywords) chạy SONG SONG.

    Parameters:
        keyword (str, optional): Từ khóa đơn lẻ
        keywords (list | str, optional): Danh sách hoặc chuỗi nhiều từ khóa
        target_count (int): Số lượng CEO mục tiêu cần tìm cho mỗi từ khóa
        save_to_sheet (bool): Tự động lưu kết quả vào Google Sheet (mặc định: True)
        max_workers (int): Số luồng chạy song song đồng thời khi có nhiều từ khóa (mặc định: 5)
        sheet_id (str): ID của Google Sheet
        worksheet_name (str): Tên tab sheet cần lưu
        proxy (str): Proxy HTTP để cào dữ liệu
        service_account_path (str): Đường dẫn credentials Service Account
        skip_empty_company (bool): Bỏ qua nếu không trích xuất được công ty (mặc định: False)
        max_pages (int): Số trang Search Engine tối đa sẽ duyệt qua (mặc định: 10)

    Returns:
        List[CEOLead]: Danh sách leads CEO mới tìm được theo từ khóa
    """
    # Chuẩn hóa danh sách từ khóa
    clean_kws: List[str] = []
    seen_kw_set: Set[str] = set()

    raw_candidates = keywords if keywords is not None else keyword
    if isinstance(raw_candidates, str):
        candidates = [k.strip() for k in raw_candidates.split(",") if k.strip()]
    elif isinstance(raw_candidates, (list, set, tuple)):
        candidates = [str(k).strip() for k in raw_candidates if str(k).strip()]
    else:
        candidates = []

    if keyword and isinstance(keyword, str) and keyword.strip() and keyword.strip() not in candidates:
        candidates.append(keyword.strip())

    for k in candidates:
        if k and k.lower() not in seen_kw_set:
            seen_kw_set.add(k.lower())
            clean_kws.append(k)

    if not clean_kws:
        clean_kws = ["Fintech Vietnam"]

    effective_proxy = proxy or get_default_proxy()
    kw_display = clean_kws[0] if len(clean_kws) == 1 else f"{len(clean_kws)} từ khóa"
    print(
        f"\n🚀 BẮT ĐẦU TÌM KIẾM CEO THEO TỪ KHÓA [Từ khóa: '{kw_display}' | Mục tiêu: {target_count}/kw | Số luồng: {max_workers} | Proxy: {_mask_proxy(effective_proxy)}]"
    )
    leads: List[CEOLead] = []
    seen_urls: Set[str] = set()

    ws = None
    if save_to_sheet:
        ws = connect_google_sheet(
            service_account_path=service_account_path,
            sheet_id=sheet_id,
            worksheet_name=worksheet_name,
        )
        if ws:
            sheet_ceos = get_existing_sheet_ceos(ws)
            seen_urls.update(sheet_ceos)
            if sheet_ceos:
                print(
                    f"📋 Đã tải {len(sheet_ceos)} định danh CEO từ Sheet để bỏ qua CEO trùng lặp."
                )

    if len(clean_kws) == 1:
        # Chạy trực tiếp cho 1 từ khóa
        leads = search_ceos_by_keyword(
            keyword=clean_kws[0],
            target_count=target_count,
            proxy=effective_proxy,
            seen_urls=seen_urls,
            skip_empty_company=skip_empty_company,
            max_pages=max_pages,
        )
    else:
        # Chạy song song qua ThreadPoolExecutor khi có nhiều từ khóa
        def _fetch_kw(idx: int, kw: str) -> List[CEOLead]:
            time.sleep(idx * 0.2)
            return search_ceos_by_keyword(
                keyword=kw,
                target_count=target_count,
                proxy=effective_proxy,
                seen_urls=seen_urls,
                skip_empty_company=skip_empty_company,
                max_pages=max_pages,
            )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_kw = {
                executor.submit(_fetch_kw, i, kw): kw for i, kw in enumerate(clean_kws)
            }
            for future in as_completed(future_to_kw):
                kw_name = future_to_kw[future]
                try:
                    kw_leads = future.result()
                    for lead in kw_leads:
                        if not is_duplicate_ceo(lead.linkedin_link, lead.name, seen_urls):
                            seen_urls.add(lead.linkedin_link)
                            seen_urls.add(lead.name.strip().lower())
                            leads.append(lead)
                except Exception as e:
                    print(f"  ❌ Lỗi khi tìm kiếm từ khóa '{kw_name}': {e}")

    print(f"\n🎯 Tổng cộng tìm thấy: {len(leads)} CEO mới từ từ khóa.")

    # Lưu vào Sheet nếu được yêu cầu (các dòng mới luôn xếp lên trên đầu)
    if save_to_sheet and leads:
        save_leads_to_sheet(
            leads,
            worksheet=ws,
            sheet_id=sheet_id,
            worksheet_name=worksheet_name,
            service_account_path=service_account_path,
        )

    return leads
